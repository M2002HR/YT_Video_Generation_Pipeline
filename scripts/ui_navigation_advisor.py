"""Constrained GPT-OSS UI-navigation advisor via the local Ajil gateway.

The advisor receives a compact, redacted DOM snapshot and returns one JSON
action. It never receives credentials, full page HTML, narration text, or the
ability to execute browser actions.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


ALLOWED_ACTIONS = {"choose", "open_all", "search", "wait", "refresh", "fail"}


@dataclass(frozen=True)
class NavigationDecision:
    action: str
    target: str = ""
    reason: str = ""


class NavigationAdvisor:
    def __init__(self) -> None:
        self.base_url = os.getenv("YT_NAVIGATION_AJIL_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
        self.enabled = os.getenv("YT_NAVIGATION_ADVISOR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    def decide(self, *, goal: str, choices: list[str]) -> NavigationDecision:
        choices = [" ".join(item.split())[:180] for item in choices if item.strip()][:80]
        if not self.enabled:
            return NavigationDecision("choose", choices[0] if choices else "", "advisor disabled")
        prompt = {"goal": goal[:500], "choices": choices, "allowed_actions": sorted(ALLOWED_ACTIONS), "instruction": "Return JSON only: action, target, reason. Choose only an exact listed choice. Use open_all only when that exact option exists."}
        headers = {os.getenv("UAG_AUTH_HEADER_NAME", "x-api-token"): os.getenv("UAG_AUTH_TOKEN", "")}
        payload = {"model": [{"provider": "groq", "model": "openai/gpt-oss-120b", "priority": 0}], "messages": [{"role": "system", "content": "You are a cautious browser navigation planner. Never invent UI labels."}, {"role": "user", "content": json.dumps(prompt)}], "temperature": 0, "response_format": {"type": "json_object"}}
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        value = json.loads(content)
        action, target = str(value.get("action", "fail")), str(value.get("target", ""))
        if action not in ALLOWED_ACTIONS or (action == "choose" and target not in choices):
            return NavigationDecision("fail", "", "advisor returned an unsafe decision")
        return NavigationDecision(action, target, str(value.get("reason", ""))[:300])
