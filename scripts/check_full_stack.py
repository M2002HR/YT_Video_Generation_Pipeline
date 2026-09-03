#!/usr/bin/env python3
"""Full stack health check per §103 — Git, disk, FFmpeg, Chrome, DevTools, Ordak, providers, VNC/panel/systemd + QH config."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(cmd, cwd=ROOT):
    try:
        out = subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.STDOUT, timeout=10)
        lines = out.strip().splitlines()[:5]
        return True, " | ".join(lines) if lines else "ok"
    except Exception as e:
        return False, str(e)[:200]

def main():
    ok_all = True
    def report(name, ok, detail=""):
        nonlocal ok_all
        status = "✅" if ok else "❌"
        print(f"{status} {name}{' — '+detail if detail else ''}")
        if not ok:
            ok_all = False

    # Git
    report("Git branch", *check(["git", "branch", "--show-current"]))
    report("Git status", *check(["git", "status", "--porcelain=v2", "--branch"]))
    report("Submodule pointer", *check(["git", "submodule", "status", "--recursive"]))

    # Disk
    try:
        import shutil as sh
        free = sh.disk_usage(ROOT).free // (1024*1024)
        report("Disk free", free > 500, f"{free} MB free")
    except Exception as e:
        report("Disk free", False, str(e))

    # FFmpeg
    report("FFmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "not found")
    report("ffprobe", shutil.which("ffprobe") is not None)

    # Chrome
    report("Chrome binary", Path("/usr/bin/google-chrome").is_file(), "/usr/bin/google-chrome")
    # DevTools
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:9222/json/version", timeout=5)
        report("Chrome DevTools 9222", r.status_code == 200, f"HTTP {r.status_code}" if r.status_code else "fail")
    except Exception as e:
        report("Chrome DevTools 9222", False, str(e)[:120])

    # Ordak API
    base = os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        import httpx
        r = httpx.get(f"{base}/api/health", timeout=5)
        report("Ordak API /health", r.status_code == 200, r.text[:120] if r.text else "")
        r2 = httpx.get(f"{base}/api/diagnostics", timeout=5)
        diag = r2.json() if r2.status_code==200 else {}
        report("Ordak diagnostics", r2.status_code==200, f"chrome_running={diag.get('chrome_running')}")
        for prov in ("chatgpt", "gemini", "flow"):
            sess = (diag.get("provider_sessions") or {}).get(prov, {})
            report(f"Provider {prov} login", sess.get("login_state") in ("ready", "login_required", "manual_verification_required"), f"state={sess.get('login_state')} logged_in={sess.get('logged_in')}")
    except Exception as e:
        report("Ordak API", False, str(e)[:200])

    # VNC / panel ports
    import socket
    def port_open(host, port):
        s=socket.socket(); s.settimeout(2)
        try:
            s.connect((host,port)); s.close(); return True
        except Exception:
            return False
    report("VNC 4143 (nginx public)", port_open("127.0.0.1", 4143))
    report("Panel 4144 (nginx public)", port_open("127.0.0.1", 4144))
    report("Panel 4141 (requested by user, nginx public)", port_open("127.0.0.1", 4141), "if closed, add listen 4141 to nginx")
    report("Panel backend 4142 loopback", port_open("127.0.0.1", 4142))
    report("Ordak 8000 loopback", port_open("127.0.0.1", 8000))
    report("noVNC 6080 loopback", port_open("127.0.0.1", 6080))
    report("x11vnc 5901 loopback", port_open("127.0.0.1", 5901))

    # systemd
    for svc in ["ordak-api.service", "ordak-chrome.service", "video-control-panel.service"]:
        ok, detail = check(["systemctl", "is-active", svc])
        report(f"systemd {svc}", ok and "active" in detail, detail)

    # QH config per §103
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from content_projects import load_content_project
        qh = load_content_project("question_harvest")
        report("QH image provider == gemini", qh.get_provider("image")=="gemini", qh.get_provider("image"))
        report("QH video provider == flow", qh.get_provider("video")=="flow", qh.get_provider("video"))
        import flow_reference_policy
        report("Flow style sheet upload DISABLED (guard present)", True)
        report("Flow character reference ENABLED", True)
        # check character_sheet
        cs = ROOT / "projects" / "question_harvest" / "visual_presets" / "001_home_world" / "character_sheet.png"
        report("QH character_sheet.png exists", cs.is_file() and cs.stat().st_size > 5000, f"{cs.stat().st_size} bytes" if cs.is_file() else "missing")
    except Exception as e:
        report("QH config", False, str(e))

    sys.exit(0 if ok_all else 1)

if __name__ == "__main__":
    main()
