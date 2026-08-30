#!/usr/bin/env python3
"""Run Ajil UAG from the git submodule using the parent project's root .env."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
AJIL_DIR = ROOT / "services" / "ajil_uag"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(os.getenv("YT_ENV_FILE", ROOT / ".env")),
        help="Root env file. Submodule-local env files are intentionally not used.",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    env_file = args.env_file.expanduser().resolve()

    if not (AJIL_DIR / "unified_gateway" / "app" / "main.py").exists():
        raise SystemExit(
            "Ajil submodule is not initialized. Run: "
            "python scripts/setup_services.py"
        )

    if not env_file.exists():
        raise SystemExit(
            f"Root env file not found: {env_file}\n"
            "Create it with: cp .env.example .env"
        )

    load_dotenv(env_file, override=False)

    # Never proxy loopback traffic. Ajil may intentionally expose an outbound
    # provider proxy via HTTP_PROXY/HTTPS_PROXY/ALL_PROXY inside its own process.
    existing_no_proxy = os.getenv("NO_PROXY", "")
    loopback_hosts = ["127.0.0.1", "localhost", "::1"]
    merged_no_proxy = [item.strip() for item in existing_no_proxy.split(",") if item.strip()]
    for host_name in loopback_hosts:
        if host_name not in merged_no_proxy:
            merged_no_proxy.append(host_name)
    os.environ["NO_PROXY"] = ",".join(merged_no_proxy)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    # Ajil natively supports UAG_ENV_FILE. Force it to the parent root env so
    # the submodule and its nested provider libraries never require local .env files.
    os.environ["UAG_ENV_FILE"] = str(env_file)

    sys.path.insert(0, str(AJIL_DIR))
    import uvicorn

    host = args.host or os.getenv("UAG_APP_HOST", "127.0.0.1")
    port = args.port or int(os.getenv("UAG_APP_PORT", "8080"))
    log_level = os.getenv("UAG_APP_LOG_LEVEL", "INFO").lower()

    print(f"Ajil submodule: {AJIL_DIR}")
    print(f"Authoritative env: {env_file}")
    print(f"Listening on: http://{host}:{port}")

    uvicorn.run(
        "unified_gateway.app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
