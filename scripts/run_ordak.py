#!/usr/bin/env python3
"""Run the Ordak submodule using the parent repository's root .env.

The video pipeline owns runtime configuration. This launcher maps root
YT_ORDAK_* variables into Ordak's native environment and points Ordak at the
same root env file so a submodule-local .env is never required.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ORDAK_DIR = ROOT / "services" / "ordak"


ENV_MAP = {
    "YT_ORDAK_APP_HOST": "APP_HOST",
    "YT_ORDAK_APP_PORT": "APP_PORT",
    "YT_ORDAK_BROWSER_PLATFORM": "BROWSER_PLATFORM",
    "YT_ORDAK_BROWSER_EXECUTABLE_PATH": "BROWSER_EXECUTABLE_PATH",
    "YT_ORDAK_BROWSER_USER_DATA_DIR": "BROWSER_USER_DATA_DIR",
    "YT_ORDAK_BROWSER_PROFILE_NAME": "BROWSER_PROFILE_NAME",
    "YT_ORDAK_BROWSER_REMOTE_DEBUGGING_URL": "BROWSER_REMOTE_DEBUGGING_URL",
    "YT_ORDAK_BROWSER_REMOTE_DEBUGGING_AUTO_LAUNCH": "BROWSER_REMOTE_DEBUGGING_AUTO_LAUNCH",
    "YT_ORDAK_BROWSER_REMOTE_DEBUGGING_LAUNCH_TIMEOUT_MS": "BROWSER_REMOTE_DEBUGGING_LAUNCH_TIMEOUT_MS",
    "YT_ORDAK_BROWSER_TIMEOUT_MS": "BROWSER_TIMEOUT_MS",
    "YT_ORDAK_CHATGPT_URL": "CHATGPT_URL",
    "YT_ORDAK_CHATGPT_PROJECT_URL": "CHATGPT_PROJECT_URL",
    "YT_ORDAK_CHATGPT_RESPONSE_TIMEOUT_MS": "CHATGPT_RESPONSE_TIMEOUT_MS",
    "YT_ORDAK_CHATGPT_STABLE_RESPONSE_SECONDS": "CHATGPT_STABLE_RESPONSE_SECONDS",
    "YT_ORDAK_CHATGPT_STALL_REFRESH_SECONDS": "CHATGPT_STALL_REFRESH_SECONDS",
    "YT_ORDAK_CHATGPT_MAX_STALL_REFRESHES": "CHATGPT_MAX_STALL_REFRESHES",
}


def _root_env_file() -> Path:
    configured = os.getenv("YT_ENV_FILE", ".env")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _ensure_loopback_no_proxy(env: dict[str, str]) -> None:
    required = ["127.0.0.1", "localhost", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        current = [item.strip() for item in env.get(key, "").split(",") if item.strip()]
        for item in required:
            if item not in current:
                current.append(item)
        env[key] = ",".join(current)


def main() -> None:
    env_file = _root_env_file()
    if not env_file.exists():
        raise SystemExit(
            f"Root env file not found: {env_file}\n"
            "Create it first with: cp .env.example .env"
        )

    if not (ORDAK_DIR / "app" / "main.py").exists():
        raise SystemExit(
            "Ordak submodule is not initialized. Run:\n"
            "  git submodule sync --recursive\n"
            "  git submodule update --init --recursive"
        )

    load_dotenv(env_file, override=False)

    if os.getenv("YT_ORDAK_ENABLED", "true").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise SystemExit("YT_ORDAK_ENABLED is false.")

    provider = os.getenv("YT_ORDAK_PROVIDER", "chatgpt").strip().lower()
    if provider != "chatgpt":
        raise SystemExit(
            "Current video-pipeline Ordak integration is intentionally ChatGPT-only. "
            "Set YT_ORDAK_PROVIDER=chatgpt."
        )

    child_env = os.environ.copy()
    child_env["ORDAK_ENV_FILE"] = str(env_file)

    for source, target in ENV_MAP.items():
        value = os.getenv(source)
        if value is not None and value.strip() != "":
            child_env[target] = value

    # Keep the current integration deterministic and visible.
    child_env["BROWSER_HEADLESS"] = "false"
    child_env["BROWSER_LINUX_X11_FALLBACK_ENABLED"] = "false"

    _ensure_loopback_no_proxy(child_env)

    host = child_env.get("APP_HOST", "127.0.0.1")
    port = child_env.get("APP_PORT", "8000")

    print(f"Ordak dir: {ORDAK_DIR}")
    print(f"Root env: {env_file}")
    print(f"Provider: {provider}")
    print(
        "Chrome profile: "
        f"{child_env.get('BROWSER_USER_DATA_DIR', '<default>')} / "
        f"{child_env.get('BROWSER_PROFILE_NAME', 'Default')}"
    )
    print(
        "DevTools: "
        f"{child_env.get('BROWSER_REMOTE_DEBUGGING_URL', 'http://127.0.0.1:9222')}"
    )
    print(f"Ordak API: http://{host}:{port}")
    print()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=ORDAK_DIR,
        env=child_env,
        check=True,
    )


if __name__ == "__main__":
    main()
