#!/usr/bin/env python3
"""Continuously observe the existing ElevenLabs tab without creating TTS jobs.

This is deliberately read-only with respect to ElevenLabs: it neither edits the
composer nor activates Generate.  It records whether an existing work tab is
ready, busy, blocked by login/captcha, or has drifted away from the composer.
The voiceover runner itself owns input recovery and submission safety.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ordak"))

ELEVENLABS_HOME_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
EDITOR_SELECTOR = 'textarea[data-testid="tts-editor"], textarea[aria-label="Main textarea"], .tiptap.ProseMirror[contenteditable="true"], [contenteditable="true"][data-testid="tts-editor"], [contenteditable="true"][role="textbox"]'


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def assess_snapshot(snapshot: dict[str, Any] | None) -> tuple[str, str]:
    """Classify a DOM snapshot without changing the provider page."""
    if snapshot is None:
        return "idle", "no ElevenLabs work tab is open"
    if snapshot.get("login_required"):
        return "blocked", "ElevenLabs requires login"
    if snapshot.get("captcha"):
        return "blocked", "ElevenLabs requires visible human verification"
    if snapshot.get("ready"):
        return "healthy", "composer is present"
    if snapshot.get("busy"):
        return "transitional", "provider page is still loading or generating"
    return "degraded", "composer is absent from the ElevenLabs work tab"


def inspect_existing_tab() -> dict[str, Any] | None:
    from app.automation.existing_chrome import execute_javascript, list_google_chrome_tabs  # type: ignore[import-not-found]

    expected = os.getenv("YT_ELEVENLABS_HOME_URL", ELEVENLABS_HOME_URL).rstrip("/")
    tab = next((item for item in list_google_chrome_tabs() if item.url.rstrip("/").startswith(expected)), None)
    if tab is None:
        return None
    raw = execute_javascript(tab.ref, f"""JSON.stringify((()=>{{
      const visible=e=>{{const r=e.getBoundingClientRect();return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;}};
      const e=document.querySelector({json.dumps(EDITOR_SELECTOR)});
      const body=document.body?.innerText||'';
      const captcha=[...document.querySelectorAll('iframe')].some(x=>visible(x)&&x.offsetWidth>=20&&x.offsetHeight>=20&&/hcaptcha|recaptcha|turnstile/i.test(`${{x.src||''}} ${{x.title||''}} ${{x.name||''}}`));
      const busy=!!document.querySelector('[aria-busy=true],[role=progressbar]')||/loading|generating|queued|creating audio|processing/i.test(body);
      return {{url:location.href,title:document.title,ready:!!e&&location.pathname.includes('app/speech-synthesis/text-to-speech'),busy,login_required:/sign in|log in|create an account/i.test(body)&&!e,captcha,editor_kind:e?(e.tagName==='TEXTAREA'?'textarea':'contenteditable'):null,editor_characters:e?((e.querySelector('[data-node-view-content]')||e).innerText||'').length:-1}};
    }})())""")
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", type=Path, default=Path("/var/lib/ordak-elevenlabs-monitor/state.json"))
    args = parser.parse_args()
    snapshot = inspect_existing_tab()
    status, detail = assess_snapshot(snapshot)
    report = {"checked_at": utcnow(), "status": status, "detail": detail, "tab": snapshot}
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.state_file)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    # A blocked/degraded provider state is recorded for the operator but must not
    # disable the timer.  The next 30-second probe is the recovery observation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
