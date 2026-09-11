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
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier, format_duration
from pipeline_stages import stage_title
ROOT = Path(__file__).resolve().parents[1]
ELEVENLABS_HOME_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".ogg")

# ElevenLabs owns the markup, but these attributes are its explicit automation and
# accessibility contract.  Keep every browser action anchored to one of them.  In
# particular, never identify a control from its viewport coordinates: the settings
# rail scrolls independently and valid controls routinely sit just outside the fold.
TEXTAREA_SELECTOR = 'textarea[data-testid="tts-editor"], textarea[aria-label="Main textarea"]'
VOICE_TRIGGER_SELECTOR = 'button[data-testid="tts-voice-selector"]'
MODEL_TRIGGER_SELECTOR = 'button[data-testid="tts-model-selector"]'
SETTINGS_TAB_SELECTOR = 'button[data-testid="tts-settings-tab"]'
OUTPUT_FORMAT_SELECTOR = 'button[aria-label="Output format"][role="combobox"]'
GENERATE_SELECTOR = 'button[data-testid="tts-generate"]'
VOICE_SEARCH_SELECTOR = '[role="dialog"] input[aria-label="Start typing to search..."]'
VOICE_OPTION_SELECTOR = '[role="dialog"] button[data-type="list-item-trigger-overlay"][aria-labelledby]'
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
    return bool(wanted) and (actual == wanted or (" - " in wanted and actual.startswith(wanted + " ")))


@dataclass(frozen=True)
class VoiceSettings:
    voice: str | None
    model: str | None
    speed: float | None
    stability: float | None
    similarity: float | None
    style: float | None
    speaker_boost: bool | None
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
            return actual===wanted || (!identity && wanted.includes(' - ') && actual.startsWith(wanted+' '));
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

    def open_and_verify(self) -> dict[str, Any]:
        expected = os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL).rstrip("/")
        existing = next((tab for tab in self._list_tabs() if tab.url.rstrip("/").startswith(expected)), None)
        self.tab = existing.ref if existing is not None else self._open_url(os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL))
        deadline = time.monotonic() + 45
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.snapshot()
            if last.get("ready"):
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
            loading, progress, captcha, downloads: download, summary: text.slice(0, 1600), generate
          };
        })()"""
        return self._json(expression.replace("__TEXTAREA_SELECTOR__", json.dumps(TEXTAREA_SELECTOR)).replace("__GENERATE_SELECTOR__", json.dumps(GENERATE_SELECTOR)).replace("__DOWNLOAD_SELECTOR__", json.dumps(DOWNLOAD_SELECTOR)))

    def set_text(self, text: str) -> None:
        encoded = json.dumps(text)
        result = self._json(f"""(() => {{
          const e = document.querySelector({json.dumps(TEXTAREA_SELECTOR)});
          if (!e) return {{ok:false, reason:'narration textarea not found'}};
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          setter.call(e, {encoded});
          e.dispatchEvent(new Event('input', {{bubbles:true}}));
          e.dispatchEvent(new Event('change', {{bubbles:true}}));
          e.focus();
          return {{ok:true, characters:e.value.length}};
        }})()""")
        if not result.get("ok") or int(result.get("characters") or 0) != len(text):
            raise RuntimeError(f"ElevenLabs narration input failed: {result.get('reason', 'text length mismatch')}")

    def select_option(self, kind: str, requested: str) -> None:
        """Choose a voice/model through its semantic trigger and option selectors.

        Defaults are intentionally left untouched; this is used only for an
        explicit CLI/env parameter and fails loudly rather than guessing.
        """
        if kind not in {"voice", "model"}:
            raise ValueError(f"Unsupported ElevenLabs selection kind: {kind}")
        trigger = VOICE_TRIGGER_SELECTOR if kind == "voice" else MODEL_TRIGGER_SELECTOR
        option = VOICE_OPTION_SELECTOR if kind == "voice" else MODEL_OPTION_SELECTOR
        probe = f"""(() => {{
          const e=document.querySelector({json.dumps(trigger)});
          return e?{{ok:true,text:(e.innerText||e.getAttribute('aria-label')||'').trim(),open:e.getAttribute('data-state')==='open'}}:{{ok:false}};
        }})()"""
        # The composer becomes usable before its selectors finish rendering, so the control
        # is waited for rather than demanded on the first look. Still fails loudly: a
        # control that never appears is a UI change, not something to guess around.
        control: dict[str, Any] = {}
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
        if setting_label_matches(requested, str(control.get("text") or "")):
            return
        if not control.get("open"):
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
                self._activate_selector(option, requested=requested)
                break
            except RuntimeError as exc:
                last_error = str(exc)
            time.sleep(0.5)
        else:
            raise RuntimeError(f"ElevenLabs did not show requested {kind} option '{requested}': {last_error}")

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
              const sliders=[...document.querySelectorAll('[role=slider][aria-label]')];
              return {ok:sliders.length>0};
            })()""")
            if present.get("ok"):
                return
            try:
                self._activate_selector(SETTINGS_TAB_SELECTOR)
            except RuntimeError:
                pass
            time.sleep(self.poll_seconds)
        raise RuntimeError(
            "ElevenLabs voice-settings sliders never appeared, even after opening the "
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

    def apply_settings(self, settings: VoiceSettings) -> dict[str, Any]:
        self.dismiss_overlays()
        applied: dict[str, Any] = {}
        if settings.model:
            self.select_option("model", settings.model)
        if settings.voice:
            self.select_option("voice", settings.voice)
            self.dismiss_overlays()
        if any(value is not None for value in (settings.speed, settings.stability, settings.similarity, settings.style)):
            self.open_settings_tab()
        for label, value in (("Speed", settings.speed), ("Stability", settings.stability), ("Similarity", settings.similarity), ("Style Exaggeration", settings.style)):
            if value is not None:
                self.apply_numeric_setting(label, value)
        if settings.speaker_boost is not None:
            wanted = bool(settings.speaker_boost)
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
        return applied

    def effective_settings(self) -> dict[str, Any]:
        """Read back controls from the DOM, independent of the settings-rail scroll."""
        expression = """(() => {
          const buttonText=selector=>{const e=document.querySelector(selector);return (e?.innerText||e?.getAttribute('aria-label')||'').trim()||null};
          const slider=label=>{const e=[...document.querySelectorAll('[role=slider]')].find(x=>x.getAttribute('aria-label')===label);return e?Number(e.getAttribute('aria-valuenow')):null};
          return {voice:buttonText(__VOICE__),model:buttonText(__MODEL__),speed:slider('Speed'),stability:slider('Stability'),similarity:slider('Similarity'),style:slider('Style Exaggeration'),output_format:buttonText(__FORMAT__)};
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
        for field, requested in (("speed", settings.speed), ("stability", settings.stability), ("similarity", settings.similarity), ("style", settings.style)):
            observed = effective.get(field)
            if requested is not None and (observed is None or abs(float(observed) - requested) > 0.011):
                raise RuntimeError(f"ElevenLabs did not retain requested {field} {requested}; observed {observed}.")
        return effective

    def textarea_characters(self) -> int:
        """Read-only length of the visible narration box (-1 when it is gone)."""
        result = self._json(f"""(() => {{const e=document.querySelector({json.dumps(TEXTAREA_SELECTOR)});return {{characters:e?e.value.length:-1}};}})()""")
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
        if before.get("loading") or before.get("progress") or before.get("downloads"):
            return {"acknowledged": True, "method": "existing_ui_state", "delay_seconds": 0.0}
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
            if current.get("busy") or current.get("downloads"):
                return {"acknowledged": True, "method": "selector_keyboard", "delay_seconds": round(time.monotonic() - started, 3), "generate": current.get("generate")}
            time.sleep(min(0.5, self.poll_seconds))
        raise RuntimeError(f"ElevenLabs did not acknowledge Generate after selector keyboard activation; no request was recorded as submitted (composer holds {self.textarea_characters()} characters now).")

    def refresh(self) -> None:
        self._json("""(() => { location.reload(); return {ok:true}; })()""")

    def download_best_available(self) -> dict[str, Any]:
        """Activate ElevenLabs' canonical latest-result download selector."""
        try:
            choice = self._pointer_activate_selector(DOWNLOAD_SELECTOR)
        except RuntimeError as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": True, "choice": choice.get("text") or "Download latest"}


def narration_input(project: Path) -> tuple[Path, str]:
    canonical = project / "voiceover" / "VOICEOVER_INPUT.txt"
    source = canonical if canonical.exists() else project / "SCRIPT_FINAL.md"
    if not source.is_file():
        raise RuntimeError("No voiceover input found: create voiceover/VOICEOVER_INPUT.txt or complete SCRIPT_FINAL.md first.")
    text = source.read_text(encoding="utf-8").replace("\ufeff", "").strip()
    # The visual-script UI can prepend its own editor affordance as a lone
    # first line. It is not narration and must never reach ElevenLabs. Keep
    # this deliberately narrow so valid narration is never rewritten.
    lines = text.splitlines()
    if lines and lines[0].strip().casefold() == "edit":
        text = "\n".join(lines[1:]).lstrip()
    if not text:
        raise RuntimeError("Voiceover input is empty.")
    if source != canonical or canonical.read_text(encoding="utf-8") != text + "\n":
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(text + "\n", encoding="utf-8")
    return canonical, text


def find_download(download_dir: Path, started_at: float) -> Path | None:
    candidates = [path for path in download_dir.glob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and path.stat().st_mtime >= started_at - 2]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


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
    def choose(name: str, cli_value: Any) -> Any:
        return cli_value if cli_value is not None else profile.get(name)
    settings = VoiceSettings(choose("voice", args.voice), choose("model", args.model), choose("speed", args.speed), choose("stability", args.stability), choose("similarity", args.similarity), choose("style", args.style), choose("speaker_boost", None if args.speaker_boost is None else args.speaker_boost == "true"), choose("output_format", args.output_format))
    voiceover_dir = project / "voiceover"
    state = State(voiceover_dir / "ELEVENLABS_RUNTIME_STATE.json", video_id=args.video_id, input_path=input_path, text=text, settings=settings, allow_input_reset=args.force)
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
    if existing and not args.force:
        state.data.update({"status": "DONE", "output": str(existing.relative_to(project))})
        state.data.pop("error", None); state.data.pop("failed_at", None)
        state.event("elevenlabs_download_recovered", started if "started" in locals() else time.perf_counter(), bytes=existing.stat().st_size, output=str(existing.relative_to(project)))
        state.save()
        json_dump(voiceover_dir / "VOICE_PROFILE.json", {"provider": "ElevenLabs web UI", "settings": settings.supplied(), "input_sha256": digest(text), "output": str(existing.relative_to(project)), "generated_at": utcnow(), "recovered_from_existing_download": True})
        print(f"ELEVENLABS VOICEOVER: PASS (reused {existing})")
        return
    notifier = PipelineNotifier(args.video_id, project.name, state_path=project / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json")
    started = time.perf_counter()
    title = stage_title("elevenlabs_voiceover")
    stage_message = notifier.stage_started(title, key="elevenlabs_voiceover")
    ui = ElevenLabsUI(poll_seconds=float(os.getenv("YT_ELEVENLABS_POLL_SECONDS", "5")), stall_seconds=float(os.getenv("YT_ELEVENLABS_STALL_REFRESH_SECONDS", "90")), max_refreshes=int(os.getenv("YT_ELEVENLABS_MAX_STALL_REFRESHES", "3")))
    try:
        ui.open_and_verify()
        state.data["status"] = "UI_READY"; state.save()
        state.event("elevenlabs_ui_ready", started)
        if args.dry_run:
            notifier.stage_update(stage_message, title, ["✅ Dry run complete", f"⏱ Duration: {format_duration(time.perf_counter() - started)}", f"📄 Input: {input_path.relative_to(project)}"])
            print("ELEVENLABS VOICEOVER: DRY RUN PASS")
            return
        configured_at = time.perf_counter()
        applied_settings = ui.apply_settings(settings)
        effective_settings = ui.verify_settings(settings)
        state.event("elevenlabs_settings_applied", configured_at, settings=settings.supplied(), effective_settings=effective_settings, ui_capabilities=applied_settings)
        ui.set_text(text)
        state.data["status"] = "TEXT_ENTERED"; state.save()
        state.event("elevenlabs_text_entered", configured_at, characters=len(text))
        submit_at = time.perf_counter()
        acknowledgement = ui.submit()
        state.data.update({"status": "SUBMITTED", "submitted_at": utcnow()}); state.save()
        state.event("elevenlabs_submit", submit_at, acknowledgement=acknowledgement)
        notifier.stage_update(stage_message, title, ["🎙️ Generation submitted", f"📝 Characters: {len(text)}", "👀 Waiting for the web UI result"])
        download_dir = Path(os.getenv("YT_ELEVENLABS_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
        download_dir.mkdir(parents=True, exist_ok=True)
        last_change, refreshes, download_started = time.monotonic(), 0, time.time()
        prior_signature = ""
        deadline = time.monotonic() + float(os.getenv("YT_ELEVENLABS_GENERATION_TIMEOUT_SECONDS", "900"))
        while time.monotonic() < deadline:
            snapshot = ui.snapshot()
            signature = json.dumps({"busy": snapshot.get("busy"), "loading": snapshot.get("loading"), "generate": snapshot.get("generate"), "downloads": snapshot.get("downloads"), "summary": snapshot.get("summary", "")[:500]}, sort_keys=True)
            if signature != prior_signature:
                prior_signature, last_change = signature, time.monotonic()
            downloaded = find_download(download_dir, download_started)
            if downloaded:
                destination = output_dir / f"narration{downloaded.suffix.lower()}"
                shutil.move(str(downloaded), destination)
                if destination.stat().st_size < 1024:
                    raise RuntimeError("ElevenLabs download is unexpectedly small.")
                state.data.update({"status": "DONE", "output": str(destination.relative_to(project)), "completed_at": utcnow()})
                state.data.pop("error", None); state.data.pop("failed_at", None)
                state.event("elevenlabs_download", submit_at, bytes=destination.stat().st_size, output=str(destination.relative_to(project)))
                json_dump(voiceover_dir / "VOICE_PROFILE.json", {"provider": "ElevenLabs web UI", "settings": settings.supplied(), "input_sha256": digest(text), "output": str(destination.relative_to(project)), "generated_at": utcnow()})
                notifier.stage_update(stage_message, title, ["✅ Stage complete", f"⏱ Duration: {format_duration(time.perf_counter() - started)}", f"📄 Saved: {destination.relative_to(project)}"])
                print(f"ELEVENLABS VOICEOVER: PASS\nAudio: {destination}")
                return
            retry_after = float(os.getenv("YT_ELEVENLABS_DOWNLOAD_RETRY_SECONDS", "30"))
            prior_download_at = float(state.data.get("download_requested_at") or 0)
            if snapshot.get("downloads") and (not state.data.get("download_choice") or time.time() - prior_download_at >= retry_after):
                choice = ui.download_best_available()
                if choice.get("ok"):
                    state.data["download_choice"] = choice.get("choice"); state.data["download_requested_at"] = time.time(); state.data["status"] = "DOWNLOAD_TRIGGERED"; state.save()
                    download_started = time.time()
                    state.event("elevenlabs_download_requested", submit_at, choice=choice.get("choice"), retry=bool(prior_download_at))
                    notifier.stage_update(stage_message, title, ["⬇️ Download requested", f"🎚️ Option: {choice.get('choice', 'Download')[:180]}", "👀 Waiting for the browser download"])
            if not snapshot.get("busy") and time.monotonic() - last_change >= ui.stall_seconds:
                if refreshes >= ui.max_refreshes:
                    raise RuntimeError("ElevenLabs UI made no progress and did not expose a downloadable result after all recovery refreshes.")
                refreshes += 1
                ui.refresh()
                # A refresh can restore the text field but cancel the browser
                # action.  Re-open, re-apply every requested control, and only
                # then resubmit after the page has visibly acknowledged it.
                ui.open_and_verify()
                recovered_settings = ui.apply_settings(settings)
                recovered_effective = ui.verify_settings(settings)
                ui.set_text(text)
                acknowledgement = ui.submit()
                state.data.update({"status": "SUBMITTED", "submitted_at": utcnow()}); state.save()
                state.event("elevenlabs_stall_refresh", started, refresh_number=refreshes, recovery_settings=recovered_settings, effective_settings=recovered_effective, acknowledgement=acknowledgement)
                notifier.stage_update(stage_message, title, ["↻ Recovery refresh completed", f"⏱ No UI progress for {format_duration(ui.stall_seconds)}", f"📍 Refresh {refreshes}/{ui.max_refreshes}"])
                last_change = time.monotonic()
            time.sleep(ui.poll_seconds)
        raise RuntimeError("ElevenLabs generation exceeded the configured timeout.")
    except Exception as exc:
        state.data.update({"status": "FAILED", "error": str(exc), "failed_at": utcnow()}); state.save()
        notifier.stage_failure(stage_message, title, time.perf_counter() - started, str(exc))
        raise


if __name__ == "__main__":
    main()
