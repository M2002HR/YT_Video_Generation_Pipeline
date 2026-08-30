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
response = httpx.get(base_url + "/health", timeout=10.0)
response.raise_for_status()
print(response.json())
