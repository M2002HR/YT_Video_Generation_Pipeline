#!/usr/bin/env python3
"""Check the root-configured Ajil UAG health endpoint."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.getenv("YT_ENV_FILE", ROOT / ".env")).expanduser()

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)

base_url = os.getenv("YT_AJIL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
# Local Ajil traffic must never be routed through HTTP_PROXY/HTTPS_PROXY/ALL_PROXY.
# This is especially important when the root env enables an outbound proxy for
# Ajil's provider requests.
with httpx.Client(trust_env=False, timeout=10.0) as client:
    response = client.get(base_url + "/health")

print(f"GET {base_url}/health -> HTTP {response.status_code}")
try:
    payload = response.json()
except Exception:
    payload = response.text

print(payload)

if response.status_code >= 400:
    raise SystemExit(
        "Ajil health check failed. The response body above is the authoritative "
        "server-side error. Local proxy environment variables were bypassed."
    )

# A generic process listening on the configured port may also expose /health.
# Do not accept it as Ajil: accepting Headscale's {"status": "pass"} here
# previously sent transcription requests to the wrong service.
if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("providers"), dict):
    raise SystemExit(
        "Configured endpoint is not the Ajil Unified AI Gateway. Expected "
        '{"status":"ok","providers":{...}} from /health.'
    )
