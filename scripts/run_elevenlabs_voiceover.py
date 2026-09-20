#!/usr/bin/env python3
"""Create a resumable ElevenLabs narration through its authenticated web UI.

This runner deliberately does not call an ElevenLabs API.  It uses the same
Ordak Chrome/CDP control layer as the visual workflow, persists parent-owned
state, and downloads the completed audio through the visible web experience.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier, format_duration
from pipeline_stages import stage_title
from shorts_v2.elevenlabs_adapter import (
    AttemptStateMachine,
    CapabilityProbe,
    ElevenLabsAdapterError,
    bind_new_result,
    build_execution_plan,
    result_snapshot,
    text_fingerprint,
    validate_download_candidate,
)
from shorts_v2.state import FileLease
ROOT = Path(__file__).resolve().parents[1]
ELEVENLABS_HOME_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".ogg")

# ElevenLabs owns the markup, but these attributes are its explicit automation and
# accessibility contract.  Keep every browser action anchored to one of them.  In
# particular, never identify a control from its viewport coordinates: the settings
# rail scrolls independently and valid controls routinely sit just outside the fold.
TEXTAREA_SELECTOR = 'textarea[data-testid="tts-editor"], textarea[aria-label="Main textarea"], .tiptap.ProseMirror[contenteditable="true"], [contenteditable="true"][data-testid="tts-editor"], [contenteditable="true"][role="textbox"]'
VOICE_TRIGGER_SELECTOR = 'button[data-testid="tts-voice-selector"]'
MODEL_TRIGGER_SELECTOR = 'button[data-testid="tts-model-selector"]'
SETTINGS_TAB_SELECTOR = 'button[data-testid="tts-settings-tab"]'
OUTPUT_FORMAT_SELECTOR = 'button[aria-label="Output format"][role="combobox"]'
GENERATE_SELECTOR = 'button[data-testid="tts-generate"]'
VOICE_SEARCH_SELECTOR = '[role="dialog"] input[aria-label="Start typing to search..."]'
VOICE_OPTION_SELECTOR = '[role="dialog"] button[data-type="list-item-trigger-overlay"][aria-labelledby]'
VOICE_CONFIRM_BUTTON_SCOPE = '[role="dialog"] button'
MODEL_OPTION_SELECTOR = '[role="dialog"] button[role="radio"]'
OUTPUT_FORMAT_OPTION_SELECTOR = '[role="option"][aria-labelledby]'
DOWNLOAD_SELECTOR = 'button[data-testid="tts-download-latest-button"]'


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def output_format_identity(value: str | None) -> str:
    """Compare ElevenLabs format labels despite harmless UI typography changes."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def setting_label_matches(requested: str | None, observed: str | None) -> bool:
    """Match an exact setting label while allowing ElevenLabs' added descriptor."""
    wanted = re.sub(r"\s+", " ", str(requested or "").strip().casefold())
    actual = re.sub(r"\s+", " ", str(observed or "").strip().casefold())
    # Voice cards use a stable ``Name - Use case`` label, followed by mutable provider
    # copy.  Depending on the current UI experiment that copy starts with a space,
    # comma, colon, parenthesis, or an em/en dash.  Match only at one of those word
    # boundaries so a requested voice can never select a similarly prefixed name.
    return bool(wanted) and bool(
        re.match(re.escape(wanted) + r"(?:$|[\s,;:()\[\]—–])", actual)
        if " - " in wanted else actual == wanted
    )


@dataclass(frozen=True)
class VoiceSettings:
    voice: str | None
    model: str | None
    speed: float | None
    stability: float | None
    similarity: float | None
    style: float | None
    speaker_boost: bool | None
    stability_mode: str | None
    output_format: str | None

    def supplied(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class State:
    def __init__(self, path: Path, *, video_id: str, input_path: Path, text: str, settings: VoiceSettings, allow_input_reset: bool = False) -> None:
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if self.data.get("input_sha256") != digest(text):
                if not allow_input_reset:
                    raise RuntimeError("Existing voiceover state belongs to different narration text; use --force only after deliberate review.")
                self.data.update({"input_path": str(input_path), "input_sha256": digest(text), "status": "PENDING"})
                self.data.setdefault("events", []).append({"operation": "narration_input_reset", "finished_at": utcnow(), "reason": "explicit --force after narration review"})
                self.save()
        else:
            self.data = {
                "schema_version": 1,
                "video_id": video_id,
                "created_at": utcnow(),
                "input_path": str(input_path),
                "input_sha256": digest(text),
                "settings": settings.supplied(),
                "status": "PENDING",
                "events": [],
            }
            self.save()

    def save(self) -> None:
        self.data["updated_at"] = utcnow()
        json_dump(self.path, self.data)

    def event(self, operation: str, started: float, **metadata: Any) -> None:
        self.data.setdefault("events", []).append({
            "operation": operation,
            "finished_at": utcnow(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            **metadata,
        })
        self.save()


def search_term_for_voice(requested: str) -> str:
    """The name to type into the voice search.

    ElevenLabs labels a row "<name> - <use case>" ("Mark - Natural Conversations") but its
    search matches the name alone, so typing the whole label filters the list to nothing.
    The exact label is still what gets selected; this only widens what the search returns.
    """
    text = str(requested or "").strip()
    for separator in (" - ", " — ", " – "):
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text


class ElevenLabsUI:
    """Small, explicit UI state machine backed by Ordak's authenticated Chrome."""

    #: How long a settings control may take to render before it counts as absent.
    control_timeout_seconds: float = 25.0

    def __init__(self, *, poll_seconds: float, stall_seconds: float, max_refreshes: int) -> None:
        sys.path.insert(0, str(ROOT / "services" / "ordak"))
        try:
            from app.automation.existing_chrome import (  # type: ignore[import-not-found]
                dispatch_mouse_click,
                execute_javascript,
                get_tab_info,
                list_google_chrome_tabs,
                open_url_in_existing_chrome,
            )
        except ImportError as exc:
            raise RuntimeError("Ordak browser runtime is unavailable; run scripts/setup_services.py first.") from exc
        self._execute = execute_javascript
        self._dispatch_mouse_click = dispatch_mouse_click
        self._get_tab_info = get_tab_info
        self._list_tabs = list_google_chrome_tabs
        self._open_url = open_url_in_existing_chrome
        self.poll_seconds = poll_seconds
        self.stall_seconds = stall_seconds
        self.max_refreshes = max_refreshes
        self.tab: Any | None = None

    def _json(self, expression: str) -> dict[str, Any]:
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        raw = self._execute(self.tab, f"JSON.stringify(({expression}))")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ElevenLabs page returned an unreadable browser response.") from exc

    def _focus_selector(self, selector: str, *, requested: str | None = None, identity: bool = False) -> dict[str, Any]:
        """Focus one semantic DOM target, optionally matching its accessible label.

        React/Radix does not expose native ``select`` elements.  The reliable and
        accessibility-correct equivalent is: locate the exact trigger/option with a
        stable selector, focus that node, then send a trusted keyboard activation.
        This helper deliberately returns no coordinates and accepts no arbitrary JS.
        """
        # Bringing a tab forward *after* focusing an option lets Radix's dialog
        # focus trap restore focus to its search box.  Front the tab first, then
        # resolve and focus the selector as one uninterrupted action.
        self._bring_to_front()
        result = self._json(f"""(() => {{
          const selector={json.dumps(selector)};
          const requested={json.dumps(requested)};
          const identity={str(identity).lower()};
          const rendered=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const labelled=e=>{{
            const ids=(e.getAttribute('aria-labelledby')||'').trim().split(/\\s+/).filter(Boolean);
            const labels=ids.map(id=>document.getElementById(id)?.innerText||'').join(' ').trim();
            return (labels||e.innerText||e.getAttribute('aria-label')||'').trim();
          }};
          const normalize=text=>String(text||'').trim().toLowerCase().replace(/\\s+/g,' ');
          const compact=text=>normalize(text).replace(/[^a-z0-9]+/g,'');
          const wanted=identity?compact(requested):normalize(requested);
          const candidates=[...document.querySelectorAll(selector)].filter(rendered).filter(e=>
            !e.disabled && e.getAttribute('aria-disabled')!=='true' && !e.hasAttribute('data-disabled'));
          const matches=requested===null?candidates:candidates.filter(e=>{{
            // Voice/model cards include a long description in aria-labelledby.
            // Their first line is the actual option label; descriptions must never
            // participate in matching one requested setting.
            const primary=labelled(e).split(String.fromCharCode(10))[0].trim();
            const actual=identity?compact(primary):normalize(primary);
            // The provider appends mutable voice-description copy after the stable
            // "Name - Use case" label. Keep the match strict at a label boundary:
            // this accepts its current comma suffix as well as prior whitespace/dash
            // variants, without confusing similarly prefixed voices.
            return actual===wanted || (!identity && wanted.includes(' - ') &&
              (actual.startsWith(wanted+' ') || actual.startsWith(wanted+',') ||
               actual.startsWith(wanted+';') || actual.startsWith(wanted+':') ||
               actual.startsWith(wanted+'(') || actual.startsWith(wanted+'[') ||
               actual.startsWith(wanted+'—') || actual.startsWith(wanted+'–')));
          }});
          const e=matches[0];
          if(!e)return {{ok:false, available:candidates.map(labelled).filter(Boolean).slice(0,80)}};
          e.scrollIntoView({{block:'nearest',inline:'nearest'}});
          e.focus({{preventScroll:true}});
          return {{ok:document.activeElement===e,text:labelled(e),tag:e.tagName,role:e.getAttribute('role')}};
        }})()""")
        if not result.get("ok"):
            detail = f" matching '{requested}'" if requested is not None else ""
            raise RuntimeError(f"Could not focus ElevenLabs selector {selector!r}{detail}; available={result.get('available', [])}.")
        return result

    def _activate_selector(self, selector: str, *, requested: str | None = None, identity: bool = False, key: str = " ") -> dict[str, Any]:
        """Activate a selector-resolved control without mouse coordinates."""
        focused = self._focus_selector(selector, requested=requested, identity=identity)
        self._trusted_key(key)
        return focused

    def _pointer_activate_selector(self, selector: str) -> dict[str, Any]:
        """Dispatch a trusted pointer action to one freshly resolved selector.

        Chrome downloads require a provider-recognized user gesture.  ElevenLabs'
        download icon currently ignores keyboard activation, so this is reserved for
        that action button; voice/model/format selection remains keyboard-only.
        Coordinates are derived immediately from the exact selector, checked with
        ``elementFromPoint``, and never persisted or accepted from a caller.
        """
        self._bring_to_front()
        target = self._json(f"""(() => {{
          const e=document.querySelector({json.dumps(selector)});
          if(!e)return {{ok:false,reason:'selector not found'}};
          if(e.disabled||e.getAttribute('aria-disabled')==='true')return {{ok:false,reason:'selector disabled'}};
          e.scrollIntoView({{block:'nearest',inline:'nearest'}});
          const r=e.getBoundingClientRect();
          const x=r.left+r.width/2, y=r.top+r.height/2;
          const hit=document.elementFromPoint(x,y);
          if(!hit||!(hit===e||e.contains(hit)))return {{ok:false,reason:'selector is obscured'}};
          return {{ok:true,x,y,text:(e.innerText||e.getAttribute('aria-label')||'').trim()}};
        }})()""")
        if not target.get("ok"):
            raise RuntimeError(f"Could not pointer-activate ElevenLabs selector {selector!r}: {target.get('reason', 'unknown state')}.")
        self._dispatch_mouse_click(self.tab, float(target["x"]), float(target["y"]))
        return target

    def _pointer_activate_exact_selector(self, selector: str, *, requested: str, identity: bool = False) -> dict[str, Any]:
        """Click one freshly focused semantic option when its own keyboard action is broken.

        This is intentionally narrower than a general coordinate click: ``_focus_selector``
        first resolves the requested accessible label, then the coordinates are derived from
        that exact active element and checked against ``elementFromPoint`` immediately before
        dispatch. It is used only for the provider's current voice-card overlay buttons.
        """
        focused = self._focus_selector(selector, requested=requested, identity=identity)
        target = self._json("""(() => {
          const e=document.activeElement;
          if(!e)return {ok:false,reason:'no focused option'};
          const r=e.getBoundingClientRect();
          if(!r.width||!r.height)return {ok:false,reason:'focused option is not rendered'};
          const x=r.left+r.width/2, y=r.top+r.height/2;
          const hit=document.elementFromPoint(x,y);
          // ElevenLabs places the semantic overlay button behind visible card
          // copy. A hit inside that button's immediate list-item parent is still
          // the same labelled option and bubbles to its selection handler.
          if(!hit||!(hit===e||e.contains(hit)||e.parentElement?.contains(hit)))return {ok:false,reason:'focused option is obscured'};
          return {ok:true,x,y,text:(e.innerText||e.getAttribute('aria-label')||'').trim()};
        })()""")
        if not target.get("ok"):
            raise RuntimeError(f"Could not pointer-activate focused ElevenLabs option: {target.get('reason', 'unknown state')}.")
        self._dispatch_mouse_click(self.tab, float(target["x"]), float(target["y"]))
        return {**focused, **target}

    def _click_voice_confirm_button(self, requested: str) -> dict[str, Any]:
        """Press the picked voice card's explicit confirmation button.

        The current picker only highlights/previews a card on activation; the
        selection commits when that card's own confirmation button (exposed as
        ``Select <name>``, e.g. ``aria-label="Select Marv "``) is pressed. The
        button is resolved from the requested voice name on every call. The
        card overlay covers varying parts of the button depending on
        hover/focus state, so the click point is sampled inside the button
        rect until it actually hits the button; a trusted keypress on the
        focused button is the fallback. Nothing is stored or assumed from a
        previous layout.
        """
        self._bring_to_front()
        target = self._json(f"""(() => {{
          const requested={json.dumps(requested)};
          const norm=s=>String(s||'').trim().toLowerCase().replace(/\\s+/g,' ');
          const esc=s=>String(s||'').replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&');
          const wanted=norm(requested);
          // Same word-boundary rule as the Python label matcher so a requested
          // voice can never confirm a similarly prefixed name.
          const nameMatches=actual=>!!wanted && new RegExp('^'+esc(wanted)+'(?:$|[\\\\s,;:()\\\\[\\\\]\u2014\u2013-])').test(actual);
          const rendered=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const labelOf=e=>(e.getAttribute('aria-label')||e.innerText||'').trim();
          const enabled=e=>!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!e.hasAttribute('data-disabled');
          const cands=[...document.querySelectorAll({json.dumps(VOICE_CONFIRM_BUTTON_SCOPE)})].filter(e=>rendered(e)&&enabled(e));
          // Primary: an explicit confirmation button naming the voice.
          let hit=cands.find(e=>{{
            const m=norm(labelOf(e)).match(/^(use|select|choose)\\s+(.*)$/);
            return !!m && nameMatches(m[2]);
          }});
          // Fallback: a bare "Use" button scoped to the card that names the voice.
          if(!hit)hit=cands.find(e=>{{
            if(norm(e.innerText||'')!=='use')return false;
            const card=e.closest('li,[role="option"],[data-type="list-item"]')||e.parentElement;
            return !!card && nameMatches(norm(card.innerText||'').split(/\\s+[0-9]/)[0]);
          }});
          if(!hit)return {{ok:false,available:cands.map(e=>norm(labelOf(e))).filter(Boolean).slice(0,40)}};
          hit.scrollIntoView({{block:'nearest',inline:'nearest'}});
          hit.focus({{preventScroll:true}});
          if(document.activeElement!==hit)return {{ok:false,reason:'confirmation button refused focus'}};
          const r=hit.getBoundingClientRect();
          let point=null;
          for(const fx of [0.1,0.25,0.5,0.75,0.9])for(const fy of [0.25,0.5,0.75]){{
            const x=r.left+r.width*fx, y=r.top+r.height*fy;
            const under=document.elementFromPoint(x,y);
            if(under&&(under===hit||hit.contains(under))){{point={{x,y}};break;}}
          }}
          return {{ok:true,text:labelOf(hit),x:point?point.x:null,y:point?point.y:null}};
        }})()""")
        if not target.get("ok"):
            detail = target.get("reason") or f"available={target.get('available', [])}"
            raise RuntimeError(f"ElevenLabs voice '{requested}' has no activatable confirmation button: {detail}.")
        if target.get("x") is not None and target.get("y") is not None:
            self._dispatch_mouse_click(self.tab, float(target["x"]), float(target["y"]))
        else:
            self._trusted_key("Enter")
        return target

    def _bring_to_front(self) -> None:
        """Bring the ElevenLabs render widget forward before DOM focus is set."""
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        info = self._get_tab_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not attach a DevTools target for ElevenLabs.")
        from websockets.sync.client import connect
        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as websocket:
            websocket.send(json.dumps({"id": 1, "method": "Page.bringToFront", "params": {}}))
            while True:
                response = json.loads(websocket.recv())
                if response.get("id") == 1:
                    if response.get("error"):
                        raise RuntimeError("Chrome could not focus the ElevenLabs tab.")
                    break
        time.sleep(0.25)

    def _trusted_key(self, key: str, *, bring_to_front: bool = False) -> None:
        """Send a real keyboard event to the focused control through CDP."""
        self._trusted_keys(key, 1, bring_to_front=bring_to_front)

    def _trusted_keys(self, key: str, count: int, *, bring_to_front: bool = False) -> None:
        """Send repeated real key presses over one CDP connection."""
        if count < 1:
            return
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        info = self._get_tab_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not attach a DevTools target for ElevenLabs.")
        from websockets.sync.client import connect
        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as websocket:
            first_request_id = 1
            if bring_to_front:
                websocket.send(json.dumps({"id": 1, "method": "Page.bringToFront", "params": {}}))
                while True:
                    response = json.loads(websocket.recv())
                    if response.get("id") == 1:
                        if response.get("error"):
                            raise RuntimeError("Chrome could not focus the ElevenLabs tab.")
                        break
                time.sleep(0.25)
                first_request_id = 2
            key_metadata = {
                "Home": ("Home", 36), "End": ("End", 35),
                "ArrowRight": ("ArrowRight", 39), "ArrowLeft": ("ArrowLeft", 37),
                "Enter": ("Enter", 13), " ": ("Space", 32),
                "Escape": ("Escape", 27),
            }
            if key not in key_metadata:
                raise RuntimeError(f"Unsupported trusted key: {key!r}")
            code, keycode = key_metadata[key]
            events = []
            for _ in range(count):
                events.extend((
                    {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode},
                    {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode},
                ))
            for request_id, params in enumerate(events, start=first_request_id):
                websocket.send(json.dumps({"id": request_id, "method": "Input.dispatchKeyEvent", "params": params}))
                while True:
                    response = json.loads(websocket.recv())
                    if response.get("id") == request_id:
                        if response.get("error"):
                            raise RuntimeError("Chrome rejected the ElevenLabs keyboard action.")
                        break

    def _trusted_insert_text(self, text: str) -> None:
        """Insert text into the currently focused rich editor through CDP."""
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        info = self._get_tab_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not attach a DevTools target for ElevenLabs.")
        from websockets.sync.client import connect
        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as websocket:
            websocket.send(json.dumps({"id": 1, "method": "Input.insertText", "params": {"text": text}}))
            while True:
                response = json.loads(websocket.recv(timeout=5))
                if response.get("id") == 1:
                    if response.get("error"):
                        raise RuntimeError("Chrome rejected the ElevenLabs narration input.")
                    return

    def open_and_verify(self) -> dict[str, Any]:
        expected = os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL).rstrip("/")
        existing = next((tab for tab in self._list_tabs() if tab.url.rstrip("/").startswith(expected)), None)
        self.tab = existing.ref if existing is not None else self._open_url(os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL))
        deadline = time.monotonic() + 45
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.snapshot()
            if last.get("ready"):
                if last.get("captcha"):
                    raise RuntimeError(
                        "ElevenLabs requires manual verification in the authenticated browser. "
                        "Complete the visible verification, then resume the run."
                    )
                return last
            if last.get("login_required"):
                raise RuntimeError("ElevenLabs login is required in the configured Chrome profile.")
            time.sleep(self.poll_seconds)
        raise RuntimeError(f"ElevenLabs composer did not become ready: {last.get('summary', 'unknown page state')}")

    def snapshot(self) -> dict[str, Any]:
        expression = """(() => {
          const visible = e => { const r=e.getBoundingClientRect(); return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth; };
          const text = document.body?.innerText || '';
          const describe = e => ({text:(e.innerText||'').trim(), aria:e.getAttribute('aria-label')||'', title:e.getAttribute('title')||'', disabled:!!e.disabled, ariaDisabled:e.getAttribute('aria-disabled')==='true'});
          const input = document.querySelector(__TEXTAREA_SELECTOR__);
          const generateElement = document.querySelector(__GENERATE_SELECTOR__);
          const generate = generateElement ? describe(generateElement) : null;
          // Only an *enabled* download control means there is something to download.
          // ElevenLabs always renders "Download latest" and "Download previous in history
          // tab"; both sit disabled until a generation finishes. Counting them made submit()
          // believe a render was already in flight and skip Generate entirely.
          const enabled = e => !e.disabled && e.getAttribute('aria-disabled') !== 'true';
          const latestDownload = document.querySelector(__DOWNLOAD_SELECTOR__);
          const download = latestDownload && enabled(latestDownload) ? [describe(latestDownload)] : [];
          const resultNodes=[...document.querySelectorAll('[data-generation-id],[data-history-item-id],[data-testid^="history-item-"]')];
          const resultIdentities=[...new Set(resultNodes.map(e=>e.getAttribute('data-generation-id')||e.getAttribute('data-history-item-id')||e.getAttribute('data-testid')).filter(Boolean))];
          const generationText = `${generate?.text||''} ${generate?.aria||''}`;
          const loading = /loading|generating|queued|creating audio|please wait|processing/i.test(`${text}\n${generationText}`);
          const progress = !!document.querySelector('[aria-busy=true],[role=progressbar]');
          // Only a challenge widget a human could actually interact with counts.
          // Stripe's invisible 1911x1 hcaptcha beacon is always present and never
          // needs interaction; counting it blocked every submit as "verification".
          const captcha = [...document.querySelectorAll('iframe')].some(e => visible(e) && e.offsetWidth >= 20 && e.offsetHeight >= 20 && /hcaptcha|recaptcha|turnstile/i.test(`${e.src||''} ${e.title||''} ${e.name||''}`));
          return {
            url: location.href, title: document.title, ready: !!input && location.pathname.includes('app/speech-synthesis/text-to-speech'),
            login_required: /sign in|log in|create an account/i.test(text) && !input,
            busy: loading || !!generate?.disabled || !!generate?.ariaDisabled || progress,
            loading, progress, captcha, downloads: download, result_identities:resultIdentities,
            summary: text.slice(0, 1600), generate
          };
        })()"""
        return self._json(expression.replace("__TEXTAREA_SELECTOR__", json.dumps(TEXTAREA_SELECTOR)).replace("__GENERATE_SELECTOR__", json.dumps(GENERATE_SELECTOR)).replace("__DOWNLOAD_SELECTOR__", json.dumps(DOWNLOAD_SELECTOR)))

    def set_text(self, text: str) -> None:
        encoded = json.dumps(text)
        result = self._json(f"""(() => {{
          const e = document.querySelector({json.dumps(TEXTAREA_SELECTOR)});
          if (!e) return {{ok:false, reason:'narration textarea not found'}};
          if(e.tagName==='TEXTAREA'){{
            const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
            setter.call(e, {encoded});
            e.dispatchEvent(new InputEvent('input', {{bubbles:true,inputType:'insertText',data:{encoded}}}));
            e.dispatchEvent(new Event('change', {{bubbles:true}}));
            e.focus();
            return {{ok:true,kind:'textarea',text:e.value}};
          }}
          const content=e.querySelector('[data-node-view-content]')||e;
          e.focus();
          const selection=window.getSelection();
          const range=document.createRange();
          range.selectNodeContents(content);
          selection.removeAllRanges();selection.addRange(range);
          return {{ok:true,kind:'contenteditable'}};
        }})()""")
        if result.get("kind") == "contenteditable":
            self._trusted_insert_text(text)
            result["text"] = self.read_text()
        if not result.get("ok") or text_fingerprint(str(result.get("text") or "")) != text_fingerprint(text):
            raise RuntimeError(f"ElevenLabs narration input failed: {result.get('reason', 'text hash mismatch')}")

    def read_text(self) -> str:
        result = self._json(f"""(() => {{const e=document.querySelector({json.dumps(TEXTAREA_SELECTOR)});const content=e?.querySelector('[data-node-view-content]')||e;return {{text:e?(e.tagName==='TEXTAREA'?e.value:(content.innerText||content.textContent||'')):null}};}})()""")
        if result.get("text") is None:
            raise RuntimeError("ElevenLabs narration editor disappeared before verification.")
        return str(result["text"])

    def verify_text(self, expected: str) -> dict[str, Any]:
        observed = self.read_text()
        if text_fingerprint(observed) != text_fingerprint(expected):
            raise RuntimeError("ElevenLabs narration editor read-back does not match the compiled input hash.")
        return {"characters": len(observed), "text_sha256": text_fingerprint(observed)}

    def select_option(self, kind: str, requested: str) -> None:
        """Choose a voice/model through its semantic trigger and option selectors.

        Defaults are intentionally left untouched; this is used only for an
        explicit CLI/env parameter and fails loudly rather than guessing.
        """
        if kind not in {"voice", "model"}:
            raise ValueError(f"Unsupported ElevenLabs selection kind: {kind}")
        trigger = VOICE_TRIGGER_SELECTOR if kind == "voice" else MODEL_TRIGGER_SELECTOR
        option = VOICE_OPTION_SELECTOR if kind == "voice" else MODEL_OPTION_SELECTOR
        # A previous interrupted attempt can leave the voice picker open. In that
        # state Radix removes the trigger from the active DOM, but the picker is
        # already the correct place to search and select. Reuse it rather than
        # treating an already-open control as a provider UI failure.
        picker_open = kind == "voice" and bool(self._json(
            f"(() => ({{ok:!!document.querySelector({json.dumps(VOICE_SEARCH_SELECTOR)})}}))()"
        ).get("ok"))
        probe = f"""(() => {{
          const e=document.querySelector({json.dumps(trigger)});
          return e?{{ok:true,text:(e.innerText||e.getAttribute('aria-label')||'').trim(),open:e.getAttribute('data-state')==='open'}}:{{ok:false}};
        }})()"""
        # The composer becomes usable before its selectors finish rendering, so the control
        # is waited for rather than demanded on the first look. Still fails loudly: a
        # control that never appears is a UI change, not something to guess around.
        control: dict[str, Any] = {}
        if not picker_open:
            deadline = time.monotonic() + self.control_timeout_seconds
            while time.monotonic() < deadline:
                control = self._json(probe)
                if control.get("ok"):
                    break
                time.sleep(self.poll_seconds)
            if not control.get("ok"):
                raise RuntimeError(
                    f"Could not find the ElevenLabs {kind} control for explicit value "
                    f"'{requested}' after {self.control_timeout_seconds:g}s."
                )
        if control.get("ok") and setting_label_matches(requested, str(control.get("text") or "")):
            return
        if not picker_open and not control.get("open"):
            self._activate_selector(trigger)
        if kind == "voice":
            search_term = search_term_for_voice(requested)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                search = self._json(f"""(() => ({{ok:!!document.querySelector({json.dumps(VOICE_SEARCH_SELECTOR)})}}))()""")
                if search.get("ok"):
                    self._json(f"""(() => {{
                      const e=document.querySelector({json.dumps(VOICE_SEARCH_SELECTOR)});
                      const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
                      setter.call(e,{json.dumps(search_term)});
                      e.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText',data:{json.dumps(search_term)}}}));
                      e.dispatchEvent(new Event('change',{{bubbles:true}}));
                      return {{ok:e.value==={json.dumps(search_term)}}};
                    }})()""")
                    break
                time.sleep(0.5)
        deadline = time.monotonic() + 15
        last_error = ""
        while time.monotonic() < deadline:
            try:
                # Voice-card overlays in the current picker can ignore Space and
                # Enter. Use an actual click only after resolving and rechecking the
                # exact labelled card; never use a stored or arbitrary coordinate.
                if kind in {"voice", "model"}:
                    self._pointer_activate_exact_selector(option, requested=requested)
                else:
                    self._activate_selector(option, requested=requested, key="Enter")
                break
            except RuntimeError as exc:
                last_error = str(exc)
            time.sleep(0.5)
        else:
            raise RuntimeError(f"ElevenLabs did not show requested {kind} option '{requested}': {last_error}")

        if kind == "voice":
            # The current picker only highlights a card on activation; the
            # selection commits with that card's own confirmation button.
            # Layouts that still commit on card activation already show the
            # requested label, so they skip the extra press.
            confirm_deadline = time.monotonic() + 15
            confirm_error = ""
            while time.monotonic() < confirm_deadline:
                current = self._json(probe)
                if current.get("ok") and setting_label_matches(requested, str(current.get("text") or "")):
                    break
                try:
                    self._click_voice_confirm_button(requested)
                    break
                except RuntimeError as exc:
                    confirm_error = str(exc)
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    f"ElevenLabs voice '{requested}' was never confirmed: {confirm_error}"
                )

        # Selection is not complete merely because a key event was accepted.  Read
        # the stable trigger until React has committed the requested label.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            observed = self._json(probe)
            if observed.get("ok") and setting_label_matches(requested, str(observed.get("text") or "")):
                return
            time.sleep(0.25)
        raise RuntimeError(f"ElevenLabs did not retain requested {kind} '{requested}' after selector activation.")

    def open_settings_tab(self) -> None:
        """Show the voice-settings sliders, which live behind their own tab.

        The composer is "ready" as soon as the narration textarea exists, but the sliders
        are only in the DOM while the Settings tab is the active one. Without this, the
        first numeric setting fails with "slider not found" on a page that has the slider.
        """
        deadline = time.monotonic() + self.control_timeout_seconds
        while time.monotonic() < deadline:
            present = self._json("""(() => {
              const wanted=/^(speed|stability|similarity|style exaggeration)$/i;
              const sliders=[...document.querySelectorAll('[role=slider][aria-label]')].filter(e=>wanted.test(e.getAttribute('aria-label')||''));
              const modes=[...document.querySelectorAll('button,[role=radio]')].filter(e=>/^(creative|natural|robust)$/i.test((e.getAttribute('aria-label')||e.innerText||'').trim()));
              return {ok:sliders.length>0||modes.length>0};
            })()""")
            if present.get("ok"):
                return
            try:
                self._activate_selector(SETTINGS_TAB_SELECTOR)
            except RuntimeError:
                pass
            time.sleep(self.poll_seconds)
        raise RuntimeError(
            "ElevenLabs model-specific voice settings never appeared, even after opening the "
            f"Settings tab, within {self.control_timeout_seconds:g}s."
        )

    def apply_numeric_setting(self, label: str, value: float) -> None:
        """Set the canonical Text-to-Speech Radix slider with real keys.

        The UI exposes sliders as ARIA spans rather than HTML range inputs.
        Starting from Home then moving in 0.01 increments is deterministic and
        lets us verify the value after every real browser interaction.
        """
        selector = f'[role="slider"][aria-label={json.dumps(label)}]'
        probe = f"""(() => {{ const e=document.querySelector({json.dumps(selector)}); if(!e)return {{ok:false}};return {{ok:true,min:Number(e.getAttribute('aria-valuemin')),max:Number(e.getAttribute('aria-valuemax')),current:Number(e.getAttribute('aria-valuenow'))}}; }})()"""
        detail = self._json(probe)
        if not detail.get("ok"):
            self.open_settings_tab()
            detail = self._json(probe)
        if not detail.get("ok"):
            raise RuntimeError(f"Could not find ElevenLabs '{label}' slider on the canonical Text to Speech page.")
        if not float(detail["min"]) <= value <= float(detail["max"]):
            raise RuntimeError(f"ElevenLabs '{label}' value {value} is outside its current UI range {detail['min']}..{detail['max']}.")
        self._focus_selector(selector)
        time.sleep(0.2)
        self._trusted_key("Home")
        time.sleep(0.15)
        def observed_value() -> float:
            observed = self._json(f"""(() => {{ const e=[...document.querySelectorAll('[role=slider]')].find(x=>x.getAttribute('aria-label')==={json.dumps(label)}); return e?{{ok:true,value:Number(e.getAttribute('aria-valuenow'))}}:{{ok:false}}; }})()""")
            if not observed.get("ok"):
                raise RuntimeError(f"ElevenLabs '{label}' disappeared while it was being configured.")
            return float(observed["value"])

        # Step size differs by control (the current UI uses 0.01 for Speed
        # and 0.005 for Stability). Measure one actual increment instead of
        # baking either assumption into the workflow.
        minimum = observed_value()
        if abs(minimum - value) <= 1e-9:
            return
        self._trusted_key("ArrowRight")
        time.sleep(0.15)
        step = observed_value() - minimum
        if step <= 0:
            raise RuntimeError(f"ElevenLabs '{label}' did not respond to a real keyboard increment.")
        increments = round((value - minimum) / step) - 1
        self._trusted_keys("ArrowRight", max(0, increments))
        final_value = observed_value()
        if abs(final_value - value) > (step / 2 + 1e-9):
            raise RuntimeError(f"ElevenLabs '{label}' did not reach requested value {value}; observed {final_value}.")

    def select_output_format(self, requested: str | None) -> str | None:
        """Select an explicit format, or retain an already-matching current value.

        ElevenLabs' current output-format popup no longer exposes choices as
        ``role=option``.  More importantly, reopening it is needless when the
        visible control already has the requested setting, and made a correct
        configured state fail as if the setting were missing.
        """
        if requested is None:
            return None
        control = self._json(f"""(() => {{ const e=document.querySelector({json.dumps(OUTPUT_FORMAT_SELECTOR)});if(!e)return {{ok:false}};return {{ok:true,text:(e.innerText||'').trim(),open:e.getAttribute('data-state')==='open'}}; }})()""")
        if not control.get("ok"):
            raise RuntimeError("Could not find ElevenLabs Output format control.")
        if output_format_identity(str(control.get("text") or "")) == output_format_identity(requested):
            return str(control["text"])
        if not control.get("open"):
            self._activate_selector(OUTPUT_FORMAT_SELECTOR)
        deadline = time.monotonic() + 10
        selected: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                selected = self._activate_selector(OUTPUT_FORMAT_OPTION_SELECTOR, requested=requested, identity=True, key="Enter")
                break
            except RuntimeError:
                pass
            time.sleep(0.25)
        if selected is None:
            raise RuntimeError(f"ElevenLabs did not expose enabled output format '{requested}'.")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            observed = self._json(f"""(() => {{const e=document.querySelector({json.dumps(OUTPUT_FORMAT_SELECTOR)});return {{text:(e?.innerText||'').trim()}};}})()""").get("text")
            if output_format_identity(str(observed or "")) == output_format_identity(requested):
                return str(observed)
            time.sleep(0.25)
        raise RuntimeError(f"ElevenLabs did not retain requested output format '{requested}' after selector activation.")

    def dismiss_overlays(self) -> None:
        """Close any panel left open, because an open one hides the settings controls.

        A leftover voice or model panel makes the selectors unfindable, and the resulting
        "control not found" reads like a UI change rather than a stale overlay.
        """
        for _ in range(3):
            open_panel = self._json("""(() => {
              const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              const panes=[...document.querySelectorAll('[role=dialog],[data-radix-popper-content-wrapper]')].filter(visible);
              return {ok:panes.length>0};
            })()""")
            if not open_panel.get("ok"):
                return
            # ElevenLabs shows this one-time modal immediately after the first
            # switch to v3.  It leaves the settings sliders mounted behind the
            # focus trap, so capability discovery succeeds while every trusted
            # slider interaction fails.  Resolve its provider-owned semantic
            # control explicitly; Escape is intentionally ignored by this modal.
            v3_welcome = self._json("""(() => {
              const e=document.querySelector('[data-testid="v3-welcome-dialog-get-started"]');
              const visible=e&&!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              return {ok:!!visible};
            })()""")
            if v3_welcome.get("ok"):
                self._activate_selector('[data-testid="v3-welcome-dialog-get-started"]', requested="Get started")
                time.sleep(0.6)
                continue
            # This modal does not close on Escape and makes the main controls
            # unfocusable. Resolve its explicit button inside the dialog and use
            # keyboard activation; do not fall back to screen coordinates.
            credits = self._json("""(() => {
              const dlg=[...document.querySelectorAll('[role=dialog]')].find(d=>d.offsetWidth>0 && /credits remaining/i.test(d.innerText||''));
              return {ok:!!dlg};
            })()""")
            if credits.get("ok"):
                for label in ("Close", "Remind Me Later"):
                    try:
                        self._activate_selector('[role="dialog"] button', requested=label)
                        time.sleep(0.6)
                        break
                    except RuntimeError:
                        continue
                else:
                    raise RuntimeError("ElevenLabs credits dialog has no selector-addressable dismissal button.")
                continue
            try:
                self._trusted_key("Escape", bring_to_front=True)
            except RuntimeError:
                return
            time.sleep(0.4)
        unresolved = self._json("""(() => {
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          return {dialogs:[...document.querySelectorAll('[role=dialog]')].filter(visible).map(e=>(e.innerText||'').trim().slice(0,120))};
        })()""")
        if unresolved.get("dialogs"):
            raise RuntimeError(f"ElevenLabs overlay could not be dismissed safely: {unresolved['dialogs']}")

    def probe_capabilities(self) -> CapabilityProbe:
        """Observe the controls that exist after model and voice selection."""
        self.dismiss_overlays()
        try:
            self.open_settings_tab()
        except RuntimeError:
            # V3 layouts may expose mode buttons without any slider rail.
            pass
        raw = self._json(f"""(() => {{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const label=e=>(e.getAttribute('aria-label')||e.innerText||'').trim();
          const sliders=[...document.querySelectorAll('[role=slider][aria-label]')].filter(visible).map(e=>label(e).toLowerCase());
          const modes=[...document.querySelectorAll('button,[role=radio]')].filter(visible).map(e=>label(e)).filter(v=>/^(creative|natural|robust)$/i.test(v));
          const editor=document.querySelector({json.dumps(TEXTAREA_SELECTOR)})||document.querySelector('[contenteditable=true][role=textbox]');
          const boost=document.querySelector('[role="switch"][aria-label*="Speaker boost" i],input[type="checkbox"][aria-label*="Speaker boost" i]');
          const text=s=>{{const e=document.querySelector(s);return (e?.innerText||e?.getAttribute('aria-label')||'').trim()}};
          return {{
            model:text({json.dumps(MODEL_TRIGGER_SELECTOR)}),voice:text({json.dumps(VOICE_TRIGGER_SELECTOR)}),
            numeric_controls:sliders.map(v=>v==='style exaggeration'?'style':v),
            stability_modes:modes.map(v=>v.toLowerCase()),speaker_boost:!!boost,
            editor_kind:editor?(editor.tagName==='TEXTAREA'?'textarea':'contenteditable'):'missing'
          }};
        }})()""")
        return CapabilityProbe(
            observed_model=str(raw.get("model") or ""),
            observed_voice=str(raw.get("voice") or ""),
            numeric_controls=frozenset(str(value) for value in raw.get("numeric_controls") or []),
            stability_modes=frozenset(str(value) for value in raw.get("stability_modes") or []),
            speaker_boost_available=bool(raw.get("speaker_boost")),
            editor_kind=str(raw.get("editor_kind") or "missing"),
            observed_at=utcnow(),
        )

    def apply_stability_mode(self, requested: str) -> None:
        selector = 'button,[role="radio"]'
        self._activate_selector(selector, requested=requested, key="Enter")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self._json(f"""(() => {{
              const wanted={json.dumps(requested.casefold())};
              const label=e=>(e.getAttribute('aria-label')||e.innerText||'').trim().toLowerCase();
              const e=[...document.querySelectorAll('button,[role=radio]')].find(x=>label(x)===wanted);
              return {{selected:!!e&&(e.getAttribute('aria-checked')==='true'||e.getAttribute('data-state')==='on'||e.getAttribute('data-state')==='checked'||e.getAttribute('aria-pressed')==='true')}};
            }})()""")
            if result.get("selected"):
                return
            time.sleep(0.25)
        raise RuntimeError(f"ElevenLabs did not retain v3 stability mode {requested!r}.")

    def apply_settings(self, settings: VoiceSettings) -> dict[str, Any]:
        self.dismiss_overlays()
        if settings.model:
            self.select_option("model", settings.model)
        if settings.voice:
            self.select_option("voice", settings.voice)
            self.dismiss_overlays()
        probe = self.probe_capabilities()
        requested = {**settings.supplied(), "tts_model": settings.model}
        plan = build_execution_plan(requested, probe)
        applied: dict[str, Any] = {
            "capabilities": probe.receipt(),
            "execution_mode": plan.execution_mode,
            "inactive_settings": plan.inactive_settings,
        }
        if plan.stability_mode and "stability" not in plan.numeric_settings:
            self.apply_stability_mode(plan.stability_mode)
        if plan.numeric_settings:
            self.open_settings_tab()
        labels = {"speed": "Speed", "stability": "Stability", "similarity": "Similarity", "style": "Style Exaggeration"}
        for name, value in plan.numeric_settings.items():
            self.apply_numeric_setting(labels[name], value)
        if plan.speaker_boost is not None:
            wanted = bool(plan.speaker_boost)
            speaker_selector = '[role="switch"][aria-label*="Speaker boost" i], input[type="checkbox"][aria-label*="Speaker boost" i]'
            result = self._json(f"""(() => {{
              const e=document.querySelector({json.dumps(speaker_selector)});
              return e?{{available:true,checked:e.getAttribute('aria-checked')==='true'||!!e.checked}}:{{available:false}};
            }})()""")
            if result.get("available") and bool(result.get("checked")) != wanted:
                self._activate_selector(speaker_selector)
                time.sleep(0.25)
                result = self._json(f"""(() => {{
                  const e=document.querySelector({json.dumps(speaker_selector)});
                  return e?{{available:true,checked:e.getAttribute('aria-checked')==='true'||!!e.checked}}:{{available:false}};
                }})()""")
            if not result.get("available") and wanted:
                raise RuntimeError("Could not set ElevenLabs Speaker boost in the current UI.")
            if result.get("available") and bool(result.get("checked")) != wanted:
                raise RuntimeError("ElevenLabs Speaker boost did not retain the requested value.")
            # ElevenLabs hides Speaker Boost for some models (including the
            # current multilingual UI).  Its absence is semantically the same
            # as the requested default-off value, never a reason to abandon a
            # valid voiceover before submission.
            applied["speaker_boost"] = {
                "requested": wanted,
                "available_in_current_ui": bool(result.get("available")),
                "effective": bool(result.get("checked")) if result.get("available") else False,
            }
        selected_output = self.select_output_format(settings.output_format)
        if selected_output:
            settings_result = self._json(f"""(() => ({{format:(document.querySelector({json.dumps(OUTPUT_FORMAT_SELECTOR)})?.innerText||'').trim()}}))()""")
            if output_format_identity(str(settings_result.get("format") or "")) != output_format_identity(selected_output):
                raise RuntimeError("ElevenLabs did not retain the requested output format.")
        applied["effective_plan"] = {
            "model": plan.model.value,
            "numeric_settings": plan.numeric_settings,
            "stability_mode": plan.stability_mode,
            "speaker_boost": plan.speaker_boost,
        }
        return applied

    def effective_settings(self) -> dict[str, Any]:
        """Read back controls from the DOM, independent of the settings-rail scroll."""
        expression = """(() => {
          const buttonText=selector=>{const e=document.querySelector(selector);return (e?.innerText||e?.getAttribute('aria-label')||'').trim()||null};
          const slider=label=>{const e=[...document.querySelectorAll('[role=slider]')].find(x=>x.getAttribute('aria-label')===label);return e?Number(e.getAttribute('aria-valuenow')):null};
          const mode=[...document.querySelectorAll('button,[role=radio]')].find(e=>/^(creative|natural|robust)$/i.test((e.getAttribute('aria-label')||e.innerText||'').trim())&&(e.getAttribute('aria-checked')==='true'||e.getAttribute('data-state')==='on'||e.getAttribute('data-state')==='checked'||e.getAttribute('aria-pressed')==='true'));
          return {voice:buttonText(__VOICE__),model:buttonText(__MODEL__),speed:slider('Speed'),stability:slider('Stability'),similarity:slider('Similarity'),style:slider('Style Exaggeration'),stability_mode:(mode?.getAttribute('aria-label')||mode?.innerText||'').trim()||null,output_format:buttonText(__FORMAT__)};
        })()"""
        expression = expression.replace("__VOICE__", json.dumps(VOICE_TRIGGER_SELECTOR)).replace("__MODEL__", json.dumps(MODEL_TRIGGER_SELECTOR)).replace("__FORMAT__", json.dumps(OUTPUT_FORMAT_SELECTOR))
        return self._json(expression)

    def verify_settings(self, settings: VoiceSettings) -> dict[str, Any]:
        effective = self.effective_settings()
        for field, requested in (("voice", settings.voice), ("model", settings.model)):
            observed = effective.get(field)
            if requested is not None and not setting_label_matches(requested, str(observed or "")):
                raise RuntimeError(f"ElevenLabs did not retain requested {field} '{requested}'; observed '{observed}'.")
        if settings.output_format is not None and output_format_identity(str(effective.get("output_format") or "")) != output_format_identity(settings.output_format):
            raise RuntimeError(f"ElevenLabs did not retain requested output_format '{settings.output_format}'; observed '{effective.get('output_format')}'.")
        probe = self.probe_capabilities()
        plan = build_execution_plan({**settings.supplied(), "tts_model": settings.model}, probe)
        for field, requested in plan.numeric_settings.items():
            observed = effective.get(field)
            if requested is not None and (observed is None or abs(float(observed) - requested) > 0.011):
                raise RuntimeError(f"ElevenLabs did not retain requested {field} {requested}; observed {observed}.")
        if plan.stability_mode and "stability" not in plan.numeric_settings and str(effective.get("stability_mode") or "").casefold() != plan.stability_mode.casefold():
            raise RuntimeError(f"ElevenLabs did not retain requested stability mode {plan.stability_mode!r}; observed {effective.get('stability_mode')!r}.")
        effective["capability_probe"] = probe.receipt()
        effective["execution_mode"] = plan.execution_mode
        return effective

    def textarea_characters(self) -> int:
        """Read-only length of the visible narration box (-1 when it is gone)."""
        result = self._json(f"""(() => {{const e=document.querySelector({json.dumps(TEXTAREA_SELECTOR)});const content=e?.querySelector('[data-node-view-content]')||e;const text=e?(e.tagName==='TEXTAREA'?e.value:(content.innerText||content.textContent||'')):null;return {{characters:text===null?-1:text.length}};}})()""")
        try:
            return int(result.get("characters", -1))
        except (TypeError, ValueError):
            return -1

    def submit(self, *, acknowledgement_seconds: float = 12) -> dict[str, Any]:
        """Submit once and require visible UI acknowledgement before proceeding.

        A successful CDP input event alone is not proof that the React action
        was accepted.  ElevenLabs currently changes this button to
        ``Loading...``; other supported acknowledgement signals are a disabled
        generate control, a progress indicator, or an immediately available
        download.  This makes recovery safe: we never label a request submitted
        until the page confirms it.
        """
        before = self.snapshot()
        if before.get("captcha"):
            raise RuntimeError("ElevenLabs requires an on-screen human verification in Chrome; complete it in VNC, then resume.")
        if before.get("loading") or before.get("progress"):
            raise RuntimeError(
                "ElevenLabs already shows an in-progress generation. Reconcile its result identity before submitting another request."
            )
        # The narration box can lose its text between set_text and activation
        # (app re-render/reset). Activating Generate on an empty composer never
        # produces audio, so refuse loudly instead of burning a submit cycle.
        if self.textarea_characters() <= 0:
            raise RuntimeError("ElevenLabs narration text is missing from the composer; refusing to activate Generate on an empty box. Resume to re-enter the text.")
        # The generate control is disabled for a moment after the text lands while the app
        # prices the request, so it is waited for rather than demanded on the first look.
        # A control that never becomes clickable is still an error.
        deadline = time.monotonic() + self.control_timeout_seconds
        while time.monotonic() < deadline:
            try:
                self._focus_selector(GENERATE_SELECTOR)
                break
            except RuntimeError:
                pass
            time.sleep(self.poll_seconds)
        else:
            raise RuntimeError("ElevenLabs Generate selector did not become enabled before timeout.")
        started = time.monotonic()
        self._activate_selector(GENERATE_SELECTOR)
        deadline = started + acknowledgement_seconds
        while time.monotonic() < deadline:
            current = self.snapshot()
            if current.get("captcha"):
                raise RuntimeError("ElevenLabs requires an on-screen human verification in Chrome; complete it in VNC, then resume.")
            if current.get("busy"):
                return {"acknowledged": True, "method": "selector_keyboard", "delay_seconds": round(time.monotonic() - started, 3), "generate": current.get("generate")}
            time.sleep(min(0.5, self.poll_seconds))
        raise RuntimeError(f"ElevenLabs did not acknowledge Generate after selector keyboard activation; no request was recorded as submitted (composer holds {self.textarea_characters()} characters now).")

    def refresh(self) -> None:
        self._json("""(() => { location.reload(); return {ok:true}; })()""")

    def configure_downloads(self, directory: Path) -> None:
        """Route this attempt into its own directory through Chrome CDP."""
        if self.tab is None:
            raise RuntimeError("ElevenLabs browser tab has not been opened.")
        directory.mkdir(parents=True, exist_ok=True)
        info = self._get_tab_info(self.tab)
        websocket_url = getattr(info, "websocket_debugger_url", None)
        if not websocket_url:
            raise RuntimeError("Ordak could not configure Chrome downloads.")
        from websockets.sync.client import connect
        with connect(websocket_url, proxy=None, open_timeout=5, close_timeout=5) as websocket:
            websocket.send(json.dumps({
                "id": 1,
                "method": "Browser.setDownloadBehavior",
                "params": {"behavior": "allow", "downloadPath": str(directory.resolve()), "eventsEnabled": True},
            }))
            while True:
                reply = json.loads(websocket.recv(timeout=5))
                if reply.get("id") == 1:
                    if reply.get("error"):
                        raise RuntimeError("Chrome rejected the ElevenLabs attempt download directory.")
                    return

    def download_bound_result(self, result_id: str) -> dict[str, Any]:
        """Activate Download only inside the DOM row carrying the bound identity."""
        selector = (
            f'[data-generation-id={json.dumps(result_id)}],'
            f'[data-history-item-id={json.dumps(result_id)}],'
            f'[data-testid={json.dumps(result_id)}]'
        )
        target = self._json(f"""(() => {{
          const row=document.querySelector({json.dumps(selector)});
          if(!row)return {{ok:false,reason:'bound result row is not present'}};
          const button=row.matches({json.dumps(DOWNLOAD_SELECTOR)})?row:row.querySelector('button[data-testid="tts-download-latest-button"],button[aria-label*="download" i],[role=button][aria-label*="download" i]');
          if(!button||button.disabled||button.getAttribute('aria-disabled')==='true')return {{ok:false,reason:'bound result has no enabled download control'}};
          button.setAttribute('data-qstation-bound-download','true');
          return {{ok:true,text:(button.innerText||button.getAttribute('aria-label')||'Download').trim()}};
        }})()""")
        if not target.get("ok"):
            return target
        try:
            choice = self._pointer_activate_selector('[data-qstation-bound-download="true"]')
        finally:
            self._json("""(() => {document.querySelectorAll('[data-qstation-bound-download]').forEach(e=>e.removeAttribute('data-qstation-bound-download'));return {ok:true};})()""")
        return {"ok": True, "choice": choice.get("text") or target.get("text"), "result_id": result_id}

    def download_best_available(self) -> dict[str, Any]:
        """Activate ElevenLabs' canonical latest-result download selector."""
        try:
            choice = self._pointer_activate_selector(DOWNLOAD_SELECTOR)
        except RuntimeError as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": True, "choice": choice.get("text") or "Download latest"}


def _read_narration_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\ufeff", "").strip()
    # The visual-script UI can prepend its own editor affordance as a lone
    # first line. It is not narration and must never reach ElevenLabs. Keep
    # this deliberately narrow so valid narration is never rewritten.
    lines = text.splitlines()
    if lines and lines[0].strip().casefold() == "edit":
        text = "\n".join(lines[1:]).lstrip()
    return text


def _voiceover_input_sidecar(project: Path) -> Path:
    return project / "voiceover" / "VOICEOVER_INPUT.source.json"


def _read_input_sidecar(project: Path) -> dict[str, Any]:
    try:
        data = json.loads(_voiceover_input_sidecar(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_input_sidecar(project: Path, *, script_sha256: str, snapshot_sha256: str, operator_customized: bool) -> None:
    json_dump(
        _voiceover_input_sidecar(project),
        {
            "schema_version": 1,
            "script_sha256": script_sha256,
            "snapshot_sha256": snapshot_sha256,
            "operator_customized": operator_customized,
            "updated_at": utcnow(),
        },
    )


def narration_input(project: Path) -> tuple[Path, str]:
    """Resolve the narration text, keeping the snapshot in sync with the script.

    The pipeline-canonical script (``SCRIPT_FINAL.md``, rewritten on every
    script generation) is the single source of truth.
    ``voiceover/VOICEOVER_INPUT.txt`` is only a snapshot of it — except when an
    operator deliberately customized the file, which is detected via the
    provenance sidecar (or, for legacy snapshots without one, via mtimes) and
    then respected with a loud warning instead of being overwritten.
    """
    canonical_file = project / "SCRIPT_FINAL.md"
    snapshot = project / "voiceover" / "VOICEOVER_INPUT.txt"
    canonical_text = _read_narration_text(canonical_file) if canonical_file.is_file() else ""
    if not snapshot.is_file():
        if not canonical_text:
            raise RuntimeError("No voiceover input found: create voiceover/VOICEOVER_INPUT.txt or complete SCRIPT_FINAL.md first.")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(canonical_text + "\n", encoding="utf-8")
        _write_input_sidecar(
            project,
            script_sha256=digest(canonical_text),
            snapshot_sha256=digest(canonical_text),
            operator_customized=False,
        )
        return snapshot, canonical_text
    snapshot_text = _read_narration_text(snapshot)
    if not snapshot_text:
        raise RuntimeError("Voiceover input is empty.")
    if not canonical_text or snapshot_text == canonical_text:
        return snapshot, snapshot_text
    # The snapshot and the canonical script diverged: determine who moved.
    sidecar = _read_input_sidecar(project)
    if sidecar and sidecar.get("snapshot_sha256") != digest(snapshot_text):
        # Someone edited the snapshot after the pipeline wrote it: operator
        # customization wins, but beats are timed against the canonical script,
        # so say so loudly — alignment stays the final guard.
        _write_input_sidecar(
            project,
            script_sha256=digest(canonical_text),
            snapshot_sha256=digest(snapshot_text),
            operator_customized=True,
        )
        print(
            "WARNING: voiceover/VOICEOVER_INPUT.txt was customized by the operator and no "
            "longer matches SCRIPT_FINAL.md; synthesizing the customized text. Body timing "
            "is measured against the canonical script, so a mismatch will fail alignment.",
            flush=True,
        )
        return snapshot, snapshot_text
    if sidecar and sidecar.get("operator_customized"):
        print(
            "WARNING: using operator-customized voiceover input although SCRIPT_FINAL.md changed; "
            "a mismatch will fail alignment instead of drifting images.",
            flush=True,
        )
        return snapshot, snapshot_text
    if not sidecar:
        # Legacy snapshot without provenance: the newer file wins. A newer
        # canonical script means the pipeline moved on; a newer snapshot means
        # an operator touched it.
        try:
            if snapshot.stat().st_mtime >= canonical_file.stat().st_mtime:
                print(
                    "WARNING: voiceover/VOICEOVER_INPUT.txt is newer than SCRIPT_FINAL.md; keeping "
                    "it as a possible operator customization.",
                    flush=True,
                )
                _write_input_sidecar(
                    project,
                    script_sha256=digest(canonical_text),
                    snapshot_sha256=digest(snapshot_text),
                    operator_customized=True,
                )
                return snapshot, snapshot_text
        except OSError:
            pass
    # Pipeline-owned snapshot and the script moved on: refresh the snapshot so
    # narration, beats and timing always speak the same text.
    print("Narration input changed via pipeline script revision; refreshing voiceover input snapshot.", flush=True)
    snapshot.write_text(canonical_text + "\n", encoding="utf-8")
    _write_input_sidecar(
        project,
        script_sha256=digest(canonical_text),
        snapshot_sha256=digest(canonical_text),
        operator_customized=False,
    )
    return snapshot, canonical_text


def _input_change_is_pipeline_synced(project: Path, text: str) -> bool:
    """True when the narration text changed through a tracked script revision."""
    sidecar = _read_input_sidecar(project)
    return (
        bool(sidecar)
        and not sidecar.get("operator_customized")
        and sidecar.get("script_sha256") == digest(text)
    )


def narration_receipt_matches(project: Path, text: str, settings_supplied: dict[str, Any]) -> bool:
    """True only when the stored narration was made from exactly this text+settings.

    This is the reuse gate for both the wrapper and the voiceover stage: a usable
    audio file alone is never enough, otherwise a script revision would silently
    keep speaking stale words while beats move on.
    """
    try:
        receipt = json.loads((project / "voiceover" / "VOICE_PROFILE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(receipt, dict) or receipt.get("input_sha256") != digest(text):
        return False
    if receipt.get("settings") != settings_supplied:
        return False
    output = receipt.get("output")
    if not output:
        return False
    candidate = (project / str(output)).resolve()
    return candidate.is_file() and candidate.stat().st_size > 0 and candidate.suffix.lower() in AUDIO_EXTENSIONS


def settings_from_profile(profile: dict[str, Any], cli: dict[str, Any] | None = None) -> VoiceSettings:
    """Build effective voice settings exactly like the CLI (profile + overrides)."""
    cli = cli or {}

    def choose(name: str, env_name: str | None = None) -> Any:
        if cli.get(name) is not None:
            return cli[name]
        value = profile.get(name)
        if value is not None:
            return value
        if env_name:
            return os.getenv(env_name) or None
        return None

    boost = choose("speaker_boost")
    if isinstance(boost, str):
        boost = boost.strip().lower() == "true"
    return VoiceSettings(
        choose("voice", "YT_ELEVENLABS_DEFAULT_VOICE"),
        choose("model", "YT_ELEVENLABS_DEFAULT_MODEL"),
        choose("speed"),
        choose("stability"),
        choose("similarity"),
        choose("style"),
        boost,
        choose("stability_mode"),
        choose("output_format"),
    )


def find_download(download_dir: Path, started_at: float) -> Path | None:
    candidates = [path for path in download_dir.glob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and path.stat().st_mtime >= started_at - 0.5]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def verify_audio_decode(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,format_name", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ElevenLabs audio failed ffprobe decode: {completed.stderr.strip()[:300]}")
    try:
        payload = json.loads(completed.stdout)
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ElevenLabs audio has no readable positive duration.") from exc
    if duration <= 0:
        raise RuntimeError("ElevenLabs audio has no readable positive duration.")
    return {"duration_seconds": duration, "format_name": str((payload.get("format") or {}).get("format_name") or "")}


def configure_ordak_browser_environment() -> None:
    """Apply the same root-env mapping used by the Ordak service launcher."""
    from run_ordak import ENV_MAP

    env_file = (ROOT / os.getenv("YT_ENV_FILE", ".env")).resolve()
    os.environ["ORDAK_ENV_FILE"] = str(env_file)
    for source, target in ENV_MAP.items():
        value = os.getenv(source, "").strip()
        if value:
            os.environ[target] = value
    os.environ["BROWSER_HEADLESS"] = "false"
    os.environ["BROWSER_LINUX_X11_FALLBACK_ENABLED"] = "false"


def main() -> None:
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    configure_ordak_browser_environment()
    parser = argparse.ArgumentParser(description="Generate a full narration through the logged-in ElevenLabs web UI.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--project", type=Path, default=None, help="Defaults to the unique videos/<id>_* directory.")
    parser.add_argument("--voice", default=os.getenv("YT_ELEVENLABS_DEFAULT_VOICE") or None)
    parser.add_argument("--model", default=os.getenv("YT_ELEVENLABS_DEFAULT_MODEL") or None)
    parser.add_argument("--profile", type=Path, default=ROOT / "voice_profiles" / "elevenlabs_mark_default.json", help="Versioned JSON voice profile; CLI values override it.")
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--stability", type=float, default=None)
    parser.add_argument("--similarity", type=float, default=None)
    parser.add_argument("--style", type=float, default=None)
    parser.add_argument("--speaker-boost", choices=("true", "false"), default=None)
    parser.add_argument("--stability-mode", choices=("Creative", "Natural", "Robust"), default=None, help="Eleven v3 stability mode; v2 slider profiles leave this unset.")
    parser.add_argument("--output-format", default=None, help="Exact visible ElevenLabs output-format label; profile value is used by default.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Verify authenticated UI and persisted inputs without generating audio.")
    args = parser.parse_args()
    projects = list((ROOT / "videos").glob(f"{args.video_id}_*")) if args.project is None else [args.project]
    if len(projects) != 1:
        raise RuntimeError(f"Expected exactly one project for video ID {args.video_id}; pass --project explicitly.")
    project = projects[0].resolve()
    input_path, text = narration_input(project)
    profile: dict[str, Any] = {}
    if args.profile:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
    settings = settings_from_profile(
        profile,
        {
            "voice": args.voice, "model": args.model, "speed": args.speed,
            "stability": args.stability, "similarity": args.similarity, "style": args.style,
            "speaker_boost": args.speaker_boost, "stability_mode": args.stability_mode,
            "output_format": args.output_format,
        },
    )
    voiceover_dir = project / "voiceover"
    try:
        state = State(voiceover_dir / "ELEVENLABS_RUNTIME_STATE.json", video_id=args.video_id, input_path=input_path, text=text, settings=settings, allow_input_reset=args.force)
    except RuntimeError as exc:
        if "different narration text" not in str(exc) or args.force or not _input_change_is_pipeline_synced(project, text):
            raise
        # The text changed through a tracked pipeline script revision (not an
        # operator file swap): reset state via the audited path instead of dying.
        print("Narration input changed via pipeline script revision; resetting voiceover state.", flush=True)
        state = State(voiceover_dir / "ELEVENLABS_RUNTIME_STATE.json", video_id=args.video_id, input_path=input_path, text=text, settings=settings, allow_input_reset=True)
    # A failed/restarted run may predate a newer versioned profile.  Persist
    # exactly what this invocation is about to apply for traceability.
    state.data["settings"] = settings.supplied()
    # A prior process can die after recording a UI download click but before
    # Chrome writes a file.  That historical click must never suppress the
    # recovery process from clicking the *currently visible* result.
    state.data.pop("download_choice", None)
    state.data.pop("download_requested_at", None)
    state.data.pop("error", None)
    state.data.pop("failed_at", None)
    state.save()
    output_dir = project / "assets" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = next((output_dir / f"narration{extension}" for extension in AUDIO_EXTENSIONS if (output_dir / f"narration{extension}").is_file()), None)
    if existing and not args.force and narration_receipt_matches(project, text, settings.supplied()):
        state.data.update({"status": "DONE", "output": str(existing.relative_to(project))})
        state.data.pop("error", None); state.data.pop("failed_at", None)
        state.event("elevenlabs_download_recovered", started if "started" in locals() else time.perf_counter(), bytes=existing.stat().st_size, output=str(existing.relative_to(project)))
        state.save()
        print(f"ELEVENLABS VOICEOVER: PASS (reused {existing})")
        return
    if existing and not args.force:
        print(
            f"ELEVENLABS VOICEOVER: existing {existing.name} was not made from the current "
            "narration text/settings; regenerating so audio, beats and timing stay in sync.",
            flush=True,
        )
    notifier = PipelineNotifier(args.video_id, project.name, state_path=project / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json")
    started = time.perf_counter()
    title = stage_title("elevenlabs_voiceover")
    stage_message = notifier.stage_started(title, key="elevenlabs_voiceover")
    ui = ElevenLabsUI(poll_seconds=float(os.getenv("YT_ELEVENLABS_POLL_SECONDS", "5")), stall_seconds=float(os.getenv("YT_ELEVENLABS_STALL_REFRESH_SECONDS", "90")), max_refreshes=int(os.getenv("YT_ELEVENLABS_MAX_STALL_REFRESHES", "3")))
    attempt_id = "attempt-" + uuid.uuid4().hex
    state.data.update({"active_attempt_id": attempt_id, "attempt_owner": args.video_id})
    state.save()
    machine = AttemptStateMachine()
    lease = FileLease(
        ROOT / "runtime" / "locks" / "elevenlabs_browser.lock",
        owner="elevenlabs_web",
        run_id=f"run-{args.video_id}",
        revision_id="voiceover",
        attempt_id=attempt_id,
        ttl_seconds=max(30.0, float(os.getenv("YT_ELEVENLABS_GENERATION_TIMEOUT_SECONDS", "900"))),
    )
    try:
        lease.acquire()
        machine.advance("OPEN")
        ui.open_and_verify()
        machine.advance("VERIFY_SESSION")
        state.data["status"] = "UI_READY"; state.save()
        state.event("elevenlabs_ui_ready", started)
        configured_at = time.perf_counter()
        applied_settings = ui.apply_settings(settings)
        machine.advance("SELECT_MODEL")
        machine.advance("SELECT_VOICE")
        machine.advance("PROBE_CAPABILITIES")
        machine.advance("APPLY_EFFECTIVE_SETTINGS")
        effective_settings = ui.verify_settings(settings)
        machine.advance("VERIFY_SETTINGS")
        state.event("elevenlabs_settings_applied", configured_at, settings=settings.supplied(), effective_settings=effective_settings, ui_capabilities=applied_settings)
        json_dump(voiceover_dir / "VOICE_CAPABILITIES.json", applied_settings["capabilities"])
        if args.dry_run:
            notifier.stage_update(stage_message, title, ["✅ Dry run capability probe complete", f"⏱ Duration: {format_duration(time.perf_counter() - started)}", f"📄 Input: {input_path.relative_to(project)}"])
            print("ELEVENLABS VOICEOVER: DRY RUN PASS")
            return
        ui.set_text(text)
        machine.advance("ENTER_COMPILED_TEXT")
        text_evidence = ui.verify_text(text)
        machine.advance("VERIFY_TEXT")
        state.data["status"] = "TEXT_ENTERED"; state.save()
        state.event("elevenlabs_text_entered", configured_at, **text_evidence)
        download_dir = voiceover_dir / "downloads" / attempt_id
        ui.configure_downloads(download_dir)
        baseline_raw = ui.snapshot()
        baseline = result_snapshot(baseline_raw)
        machine.advance("CAPTURE_RESULT_BASELINE")
        state.data["result_baseline"] = {"identities": sorted(baseline.identities), "captured_at": utcnow()}
        state.save()
        submit_at = time.perf_counter()
        acknowledgement = ui.submit()
        machine.advance("SUBMIT_ONCE")
        machine.advance("ACKNOWLEDGED")
        state.data.update({"status": "SUBMITTED", "submitted_at": utcnow()}); state.save()
        state.event("elevenlabs_submit", submit_at, acknowledgement=acknowledgement)
        notifier.stage_update(stage_message, title, ["🎙️ Generation submitted", f"📝 Characters: {len(text)}", "👀 Waiting for the web UI result"])
        machine.advance("WAIT_FOR_BOUND_RESULT")
        last_change, download_started = time.monotonic(), 0.0
        prior_signature = ""
        bound_result_id: str | None = None
        download_requested = False
        deadline = time.monotonic() + float(os.getenv("YT_ELEVENLABS_GENERATION_TIMEOUT_SECONDS", "900"))
        while time.monotonic() < deadline:
            snapshot = ui.snapshot()
            signature = json.dumps({"busy": snapshot.get("busy"), "loading": snapshot.get("loading"), "generate": snapshot.get("generate"), "downloads": snapshot.get("downloads"), "result_identities": snapshot.get("result_identities")}, sort_keys=True)
            if signature != prior_signature:
                prior_signature, last_change = signature, time.monotonic()
                lease.heartbeat()
            if bound_result_id is None:
                bound_result_id = bind_new_result(baseline, result_snapshot(snapshot))
                if bound_result_id:
                    state.data.update({"bound_result_id": bound_result_id, "status": "RESULT_BOUND"})
                    state.save()
            if bound_result_id and not download_requested:
                choice = ui.download_bound_result(bound_result_id)
                if not choice.get("ok"):
                    raise RuntimeError(f"Bound ElevenLabs result cannot be downloaded: {choice.get('reason', 'unknown reason')}")
                machine.advance("DOWNLOAD_BOUND_RESULT")
                download_started = time.time()
                download_requested = True
                state.data.update({"download_choice": choice.get("choice"), "download_requested_at": download_started, "status": "DOWNLOAD_TRIGGERED"})
                state.save()
                state.event("elevenlabs_download_requested", submit_at, choice=choice.get("choice"), result_id=bound_result_id)
                notifier.stage_update(stage_message, title, ["⬇️ Bound result download requested", f"🆔 Result: {bound_result_id[:120]}", "👀 Waiting for the browser download"])
            downloaded = find_download(download_dir, download_started) if download_requested else None
            if downloaded:
                downloaded = validate_download_candidate(downloaded, attempt_root=download_dir, started_at=download_started)
                technical = verify_audio_decode(downloaded)
                machine.advance("VERIFY_DECODE_AND_IDENTITY")
                if state.data.get("active_attempt_id") != attempt_id or state.data.get("bound_result_id") != bound_result_id:
                    raise RuntimeError("Late ElevenLabs result no longer owns the active attempt; refusing promotion.")
                destination = output_dir / f"narration{downloaded.suffix.lower()}"
                shutil.move(str(downloaded), destination)
                output_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
                state.data.update({"status": "DONE", "output": str(destination.relative_to(project)), "completed_at": utcnow()})
                state.data.pop("error", None); state.data.pop("failed_at", None)
                state.event("elevenlabs_download", submit_at, bytes=destination.stat().st_size, output=str(destination.relative_to(project)), result_id=bound_result_id, **technical)
                receipt = {
                    "schema_version": 2,
                    "provider": "ElevenLabs web UI",
                    "transport": "elevenlabs_web",
                    "attempt_id": attempt_id,
                    "result_id": bound_result_id,
                    "input_sha256": digest(text),
                    "compiled_input_sha256": text_fingerprint(text),
                    "settings": settings.supplied(),
                    "effective_settings": effective_settings,
                    "capability_schema_version": applied_settings["capabilities"]["schema_version"],
                    "capabilities": applied_settings["capabilities"],
                    "result_baseline": {"identities": sorted(baseline.identities)},
                    "output": str(destination.relative_to(project)),
                    "output_sha256": output_sha256,
                    "technical": technical,
                    "generated_at": utcnow(),
                }
                json_dump(voiceover_dir / "TTS_EXECUTION_RECEIPT.json", receipt)
                json_dump(voiceover_dir / "VOICE_PROFILE.json", {"provider": "ElevenLabs web UI", "settings": settings.supplied(), "input_sha256": digest(text), "output": str(destination.relative_to(project)), "output_sha256": output_sha256, "result_id": bound_result_id, "generated_at": receipt["generated_at"]})
                machine.advance("COMMIT_RECEIPT")
                notifier.stage_update(stage_message, title, ["✅ Stage complete", f"⏱ Duration: {format_duration(time.perf_counter() - started)}", f"📄 Saved: {destination.relative_to(project)}"])
                print(f"ELEVENLABS VOICEOVER: PASS\nAudio: {destination}")
                return
            if not snapshot.get("busy") and time.monotonic() - last_change >= ui.stall_seconds:
                raise RuntimeError(
                    "ElevenLabs submission acknowledgement exists but no bound result made progress; "
                    "status is uncertain, so automatic refresh/resubmit is forbidden. Resume after reconciliation."
                )
            time.sleep(ui.poll_seconds)
        raise RuntimeError("ElevenLabs generation exceeded the configured timeout.")
    except Exception as exc:
        status = "PAUSED_AUTH" if "verification" in str(exc).casefold() or "login" in str(exc).casefold() else "FAILED"
        state.data.update({"status": status, "error": str(exc), "failed_at": utcnow(), "adapter_state": machine.current}); state.save()
        notifier.stage_failure(stage_message, title, time.perf_counter() - started, str(exc))
        raise
    finally:
        lease.release()


if __name__ == "__main__":
    main()
