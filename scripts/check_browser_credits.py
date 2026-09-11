#!/usr/bin/env python3
"""Read account and credit information from configured, signed-in Chrome profiles.

This is deliberately browser-only: it neither calls provider billing APIs nor reads
cookies/passwords from a Chrome profile.  A short-lived tab is opened in each configured
DevTools session, the visible account menu is opened with real CDP input, and only the
visible account/usage text is normalised into the state file.

``YT_CREDIT_CHECK_PROFILES`` may contain a JSON array for more profiles, e.g.::

  [{"id":"ordak","label":"Ordak","debugging_url":"http://127.0.0.1:9222",
    "vnc_port":4143}]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = [{
    "id": "ordak",
    "label": "Ordak Chrome",
    "debugging_url": "http://127.0.0.1:9222",
    "vnc_port": 4143,
}]
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
NUMBER_RE = r"([\d][\d,]*(?:\.\d+)?(?:\s*[KM])?)"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically publish every transition so the panel can render partial results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utcnow()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def profiles_from_environment() -> list[dict[str, Any]]:
    raw = os.getenv("YT_CREDIT_CHECK_PROFILES", "").strip()
    if not raw:
        return [dict(item) for item in DEFAULT_PROFILES]
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("YT_CREDIT_CHECK_PROFILES must be a JSON array.") from exc
    if not isinstance(candidate, list) or not candidate:
        raise RuntimeError("YT_CREDIT_CHECK_PROFILES must contain at least one profile.")
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(candidate):
        if not isinstance(item, dict):
            raise RuntimeError(f"Credit-check profile #{index + 1} must be an object.")
        profile_id = str(item.get("id") or "").strip().lower()
        debugging_url = str(item.get("debugging_url") or "").strip().rstrip("/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile_id) or profile_id in seen:
            raise RuntimeError("Every credit-check profile needs a unique safe id.")
        if not re.fullmatch(r"https?://[^/]+", debugging_url):
            raise RuntimeError(f"Credit-check profile '{profile_id}' has an invalid debugging_url.")
        seen.add(profile_id)
        profiles.append({
            "id": profile_id,
            "label": str(item.get("label") or profile_id).strip()[:120],
            "debugging_url": debugging_url,
            "vnc_port": int(item["vnc_port"]) if item.get("vnc_port") is not None else None,
        })
    return profiles


def _opener():
    return build_opener(ProxyHandler({}))


def _json_request(url: str, *, method: str = "GET") -> Any:
    request = Request(url, method=method)
    with _opener().open(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def open_tab(debugging_url: str, target_url: str) -> dict[str, Any]:
    """Open a dedicated, short-lived account-check tab.

    The provider worker owns its existing Flow/Gemini tab.  A credit check must never
    replace or close it: doing so makes diagnostics bind to the account/profile page and
    falsely report that Flow needs manual verification.  The caller is responsible for
    closing only the target returned here after it has finished reading visible account
    data.
    """
    encoded = quote(target_url, safe=":/?&=%#")
    payload = _json_request(f"{debugging_url}/json/new?{encoded}", method="PUT")
    if not isinstance(payload, dict) or not payload.get("webSocketDebuggerUrl"):
        raise RuntimeError("Chrome did not return a DevTools target for the account check.")
    target_id = str(payload.get("id") or "").strip()
    if not target_id:
        raise RuntimeError("Chrome returned an account-check tab without a target id.")
    return payload


def close_check_tab(debugging_url: str, target_id: str) -> None:
    """Close the one tab created by this checker; never touch provider-owned tabs."""
    version = _json_request(f"{debugging_url}/json/version")
    browser_ws = str((version or {}).get("webSocketDebuggerUrl") or "") if isinstance(version, dict) else ""
    if not browser_ws:
        raise RuntimeError("Chrome did not expose a browser DevTools target for tab cleanup.")
    try:
        from websockets.sync.client import connect
        with connect(browser_ws, proxy=None, open_timeout=10, close_timeout=3) as websocket:
            cdp_call(websocket, 100, "Target.closeTarget", {"targetId": target_id})
    except (RuntimeError, OSError, TimeoutError) as exc:
        raise RuntimeError("Chrome could not close the temporary account-check tab.") from exc


def cdp_call(websocket: Any, request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    websocket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
    while True:
        reply = json.loads(websocket.recv())
        if reply.get("id") != request_id:
            continue
        if reply.get("error"):
            raise RuntimeError(f"Chrome rejected {method}: {reply['error'].get('message', 'unknown error')}")
        return reply.get("result") or {}


def evaluate(websocket: Any, expression: str) -> Any:
    result = cdp_call(websocket, 10, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
        "userGesture": True,
    })
    if result.get("exceptionDetails"):
        raise RuntimeError("The provider page rejected the account check script.")
    return (result.get("result") or {}).get("value")


def page_snapshot(websocket: Any) -> dict[str, Any]:
    # Do not collect inputs or HTML.  Account and plan data must be visibly rendered text.
    raw = evaluate(websocket, """JSON.stringify((() => {
      const visible = e => { const r=e.getBoundingClientRect(); return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length) && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth; };
      const controls = [...document.querySelectorAll('button,a,[role=button]')].filter(visible).map(e => ({
        text:(e.innerText||'').trim().slice(0,240), aria:e.getAttribute('aria-label')||'', title:e.getAttribute('title')||'',
        testid:e.getAttribute('data-testid')||'', expanded:e.getAttribute('aria-expanded')||'',
        x:(() => { const r=e.getBoundingClientRect(); return Math.round(r.left+r.width/2); })(),
        y:(() => { const r=e.getBoundingClientRect(); return Math.round(r.top+r.height/2); })()
      }));
      return {url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,50000),controls};
    })())""")
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Chrome returned an unreadable provider page.") from exc
    return data if isinstance(data, dict) else {}


def profile_button(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    def score(control: dict[str, Any]) -> int:
        hint = " ".join(str(control.get(key) or "") for key in ("aria", "title", "testid", "text")).casefold()
        if re.search(r"sign\s*out|log\s*out|logout", hint):
            return -100
        points = 0
        if re.search(r"account|profile|avatar|user menu|google account", hint): points += 8
        if re.search(r"account menu|profile menu", hint): points += 4
        if EMAIL_RE.search(hint): points += 3
        if str(control.get("expanded")) == "false": points += 1
        return points
    candidates = [item for item in snapshot.get("controls") or [] if isinstance(item, dict)]
    candidates.sort(key=score, reverse=True)
    return candidates[0] if candidates and score(candidates[0]) > 0 else None


def trusted_click(websocket: Any, control: dict[str, Any]) -> bool:
    try:
        x, y = float(control["x"]), float(control["y"])
    except (KeyError, TypeError, ValueError):
        return False
    cdp_call(websocket, 20, "Page.bringToFront")
    for request_id, params in enumerate((
        {"type": "mouseMoved", "x": x, "y": y},
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
    ), start=21):
        cdp_call(websocket, request_id, "Input.dispatchMouseEvent", params)
    return True


def click_usage_destination(websocket: Any, snapshot: dict[str, Any]) -> bool:
    """If the profile menu exposes a usage page, follow it with a real click."""
    candidates: list[tuple[int, dict[str, Any]]] = []
    for control in snapshot.get("controls") or []:
        if not isinstance(control, dict):
            continue
        text = str(control.get("text") or "").strip().casefold()
        hint = " ".join(str(control.get(key) or "") for key in ("text", "aria", "title")).casefold()
        if re.search(r"sign\s*out|logout|upgrade", hint):
            continue
        score = 0
        if text == "subscription": score = 10
        elif text in {"usage analytics", "usage"}: score = 9
        elif text in {"billing", "manage subscription"}: score = 8
        elif re.fullmatch(r"(?:account )?settings", text): score = 3
        if score:
            candidates.append((score, control))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return trusted_click(websocket, candidates[0][1]) if candidates else False


def number(value: str) -> float | int | None:
    try:
        compact = value.replace(",", "").replace(" ", "").upper()
        multiplier = 1_000_000 if compact.endswith("M") else 1_000 if compact.endswith("K") else 1
        compact = compact.rstrip("KM")
        parsed = float(compact) * multiplier
        return int(parsed) if parsed.is_integer() else parsed
    except ValueError:
        return None


def credit_summary(text: str) -> dict[str, Any] | None:
    clean = re.sub(r"\s+", " ", text)
    patterns = (
        (rf"{NUMBER_RE}\s*(credits?|characters?|tokens?)\s*(?:left|remaining|available)(?:\s*(?:out of|of|/)\s*{NUMBER_RE})?", "remaining_first"),
        (rf"{NUMBER_RE}\s*(?:/|of|out of)\s*{NUMBER_RE}\s*(credits?|characters?|tokens?)", "ratio"),
        (rf"(?:used|usage)\s*{NUMBER_RE}\s*(?:of|/)\s*{NUMBER_RE}\s*(credits?|characters?|tokens?)", "used_ratio"),
    )
    for pattern, kind in patterns:
        match = re.search(pattern, clean, re.I)
        if not match:
            continue
        groups = match.groups()
        raw = match.group(0)
        values = [number(group) for group in groups if re.fullmatch(NUMBER_RE, group or "", re.I)]
        unit = next((group.casefold() for group in groups if group and re.fullmatch(r"credits?|characters?|tokens?", group, re.I)), "credits")
        result: dict[str, Any] = {"unit": unit.rstrip("s"), "raw": raw[:240]}
        if kind == "remaining_first":
            result["remaining"] = values[0] if values else None
            if len(values) > 1: result["total"] = values[1]
        elif kind == "ratio":
            if len(values) > 1:
                result.update({"used": values[0], "total": values[1], "remaining": max(values[1] - values[0], 0)})
        else:
            if len(values) > 1:
                result.update({"used": values[0], "total": values[1], "remaining": max(values[1] - values[0], 0)})
        return result
    # Both current account menus show a bare balance (for example "10,000 credits"
    # and "1,050 Google Flow credits") rather than a used/total sentence.  Select the
    # most account-like occurrence and ignore promotional "additional ... daily" text.
    balances: list[tuple[int, dict[str, Any]]] = []
    for match in re.finditer(rf"{NUMBER_RE}\s*((?:google\s+flow\s+)?credits?|characters?|tokens?)\b", clean, re.I):
        raw = match.group(0)
        context = clean[max(0, match.start() - 48):match.end() + 48].casefold()
        score = 1
        if "google flow" in raw.casefold(): score += 15
        if re.search(r"additional|daily|per day|generating|will use", context): score -= 10
        amount = number(match.group(1))
        unit = re.sub(r"^google\s+flow\s+", "", match.group(2), flags=re.I).casefold().rstrip("s")
        if amount is not None:
            balances.append((score, {"remaining": amount, "unit": unit, "raw": raw[:240]}))
    if balances:
        balances.sort(key=lambda item: item[0], reverse=True)
        if balances[0][0] > 0:
            return balances[0][1]
    return None


def account_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    # Menus frequently expose identity/credits through aria-labels while their visible
    # glyph is just an avatar.  Those labels are browser-rendered accessibility text, not
    # profile storage or hidden DOM, and are required for a useful account report.
    control_text = "\n".join(
        " ".join(str(control.get(key) or "") for key in ("text", "aria", "title"))
        for control in snapshot.get("controls") or []
        if isinstance(control, dict)
    )
    text = f"{str(snapshot.get('text') or '')}\n{control_text}"
    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    plan_match = re.search(r"\b(?:current\s+)?plan\s*:\s*([^\n]{2,80})", text, re.I)
    if not plan_match:
        plan_match = re.search(r"\b([A-Za-z][A-Za-z -]{0,40}\s+plan)\b", text, re.I)
    return {
        "email": emails[0] if emails else None,
        "plan": re.sub(r"\s+", " ", plan_match.group(1)).strip() if plan_match else None,
        "credits": credit_summary(text),
        "page_title": str(snapshot.get("title") or "")[:180],
        "page_url": str(snapshot.get("url") or "")[:500],
    }


def elevenlabs_balance(websocket: Any) -> dict[str, Any] | None:
    """Read the labelled Total/Remaining rows from ElevenLabs' open profile card.

    The card also renders a compact ``10,000 credits`` label.  That is explicitly the
    *Total* in ElevenLabs' own DOM, so it must never be presented as the remaining balance.
    Rather than infer from the percentage ring, read the sibling value on the ``Remaining``
    row that the provider renders beside it.
    """
    raw = evaluate(websocket, """JSON.stringify((() => {
      const visible = e => { const r=e.getBoundingClientRect(); return !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length) && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth; };
      const clean = value => (value||'').replace(/\\s+/g,' ').trim();
      const rowValue = label => {
        const labelNode = [...document.querySelectorAll('div,span,p')].find(e => visible(e) && clean(e.textContent) === label);
        if (!labelNode || !labelNode.parentElement) return null;
        const leaves = [...labelNode.parentElement.querySelectorAll('div,span,p')]
          .filter(e => visible(e) && e.children.length === 0)
          .map(e => clean(e.textContent))
          .filter(Boolean);
        return leaves.find(value => value !== label) || null;
      };
      return {total:rowValue('Total'), remaining:rowValue('Remaining')};
    })())""")
    try:
        values = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(values, dict):
        return None
    remaining_text = str(values.get("remaining") or "")
    total_text = str(values.get("total") or "")
    remaining_match = re.search(NUMBER_RE, remaining_text, re.I)
    total_match = re.search(NUMBER_RE, total_text, re.I)
    if not remaining_match:
        return None
    remaining = number(remaining_match.group(1))
    total = number(total_match.group(1)) if total_match else None
    if remaining is None:
        return None
    result: dict[str, Any] = {
        "remaining": remaining,
        "unit": "credit",
        "raw": f"Remaining {remaining_text}"[:240],
    }
    if total is not None:
        result["total"] = total
        result["used"] = max(total - remaining, 0)
        result["raw"] = f"Total {total_text} · Remaining {remaining_text}"[:240]
    return result


def login_required(text: str) -> bool:
    lower = text.casefold()
    return bool(re.search(r"\b(sign in|log in|login|create an account)\b", lower)) and not bool(EMAIL_RE.search(text))


def check_service(profile: dict[str, Any], service: dict[str, str]) -> dict[str, Any]:
    try:
        from websockets.sync.client import connect
    except ImportError as exc:
        raise RuntimeError("The CDP websocket dependency is unavailable in the panel Python environment.") from exc
    debugging_url = str(profile["debugging_url"])
    target = open_tab(debugging_url, service["url"])
    target_id = str(target.get("id") or "").strip()
    if not target_id:
        raise RuntimeError("Chrome returned an account-check tab without a target id.")
    websocket_url = str(target["webSocketDebuggerUrl"])
    try:
        with connect(websocket_url, proxy=None, open_timeout=10, close_timeout=3) as websocket:
            cdp_call(websocket, 1, "Page.bringToFront")
            deadline = time.monotonic() + 35
            snapshot: dict[str, Any] = {}
            while time.monotonic() < deadline:
                snapshot = page_snapshot(websocket)
                # Shells render before their menus.  Wait for the actual account control so
                # the following click is directed at the provider profile, never a page shell.
                if profile_button(snapshot):
                    break
                time.sleep(0.5)
            # Provider SPA shells expose the avatar before their click handler and account
            # panel data are hydrated.  Let that final client-side hydration finish; otherwise
            # CDP faithfully clicks a control that the page has not wired up yet.
            time.sleep(3)
            snapshot = page_snapshot(websocket)
            initial = snapshot
            profile_control = profile_button(snapshot)
            clicked_profile = trusted_click(websocket, profile_control) if profile_control else False
            if clicked_profile:
                menu_deadline = time.monotonic() + 6
                while time.monotonic() < menu_deadline:
                    time.sleep(0.5)
                    snapshot = page_snapshot(websocket)
                    refreshed = profile_button(snapshot)
                    if refreshed and str(refreshed.get("expanded") or "").lower() == "true":
                        # A short settling interval lets React mount menu contents such as the
                        # balance chip, which otherwise lands a frame after aria-expanded.
                        time.sleep(0.7)
                        snapshot = page_snapshot(websocket)
                        break
            summary = account_summary(snapshot)
            if service["key"] == "elevenlabs":
                # ElevenLabs has a compact total label and a distinct Remaining row.  Do not
                # let the generic bare-number parser turn the total into a false balance.
                summary["credits"] = elevenlabs_balance(websocket)
            clicked_usage = False
            if summary.get("credits") is None and clicked_profile:
                clicked_usage = click_usage_destination(websocket, snapshot)
                if clicked_usage:
                    time.sleep(1.5)
                    snapshot = page_snapshot(websocket)
                    summary = account_summary(snapshot)
            if not summary.get("email"):
                fallback = account_summary(initial)
                summary["email"] = fallback.get("email")
            if login_required(str(snapshot.get("text") or "")):
                status, message = "login_required", "The signed-in session is unavailable; sign in through VNC, then retry."
            elif summary.get("credits"):
                status, message = "ready", "Account and visible credit balance read from the browser."
            else:
                status, message = "partial", "Account page opened, but this provider did not expose a readable credit balance."
            return {
                "key": service["key"], "label": service["label"], "status": status, "message": message,
                "profile_menu_opened": clicked_profile, "usage_opened": clicked_usage, **summary,
            }
    finally:
        # This cleanup is deliberately target-scoped.  In particular, never close or
        # navigate the existing Flow work tab that readiness checks and jobs rely on.
        close_check_tab(debugging_url, target_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--check-id", default="")
    args = parser.parse_args()
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    path = Path(args.state_path).resolve()
    check_id = args.check_id or uuid.uuid4().hex
    services = [
        {"key": "elevenlabs", "label": "ElevenLabs", "url": os.getenv("YT_ELEVENLABS_HOME_URL", "https://elevenlabs.io/app")},
        {"key": "google_flow", "label": "Google Flow", "url": os.getenv("YT_FLOW_URL", "https://flow.google.com/")},
    ]
    try:
        profiles = profiles_from_environment()
    except RuntimeError as exc:
        write_state(path, {"check_id": check_id, "status": "failed", "started_at": utcnow(), "error": str(exc), "profiles": []})
        raise SystemExit(2)
    state: dict[str, Any] = {
        "check_id": check_id, "status": "running", "started_at": utcnow(), "completed_at": None,
        "profiles": [{
            "id": profile["id"], "label": profile["label"], "debugging_url": profile["debugging_url"],
            "vnc_port": profile.get("vnc_port"), "status": "queued", "services": [
                {"key": service["key"], "label": service["label"], "status": "queued"} for service in services
            ],
        } for profile in profiles],
    }
    write_state(path, state)
    for profile, result_profile in zip(profiles, state["profiles"]):
        result_profile["status"] = "checking"
        write_state(path, state)
        for service, result_service in zip(services, result_profile["services"]):
            result_service.update({"status": "checking", "started_at": utcnow()})
            write_state(path, state)
            try:
                result_service.update(check_service(profile, service))
            except (RuntimeError, URLError, HTTPError, TimeoutError, OSError) as exc:
                result_service.update({"status": "error", "message": f"{type(exc).__name__}: {exc}"[:500]})
            result_service["completed_at"] = utcnow()
            write_state(path, state)
        statuses = {service["status"] for service in result_profile["services"]}
        result_profile["status"] = "ready" if statuses == {"ready"} else ("partial" if statuses & {"ready", "partial"} else "error")
        write_state(path, state)
    state["status"] = "completed"
    state["completed_at"] = utcnow()
    write_state(path, state)


if __name__ == "__main__":
    main()
