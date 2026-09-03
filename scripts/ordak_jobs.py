#!/usr/bin/env python3
"""Typed Ordak job client for the Question Harvest pipeline.

Everything the pipeline sends to a browser provider goes through here, so the explicit
generation contract (master_prompt §5, §18-21) and the reference-role contract
(§12-16, §61) are always transmitted — never inferred by the worker and never encoded
into the prompt text.

There is no provider fallback and no synthetic substitute: a failed provider call raises
``OrdakJobError`` carrying the provider's structured ``error_code`` so the orchestrator can
map it onto a PAUSED_* / FAILED_* pipeline state.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

#: Provider error codes that mean "a human must act", not "retry harder".
PAUSE_ERROR_CODES = {
    "login_required": "PAUSED_LOGIN_REQUIRED",
    "flow_login_required": "PAUSED_LOGIN_REQUIRED",
    "manual_verification_required": "PAUSED_MANUAL_VERIFICATION",
    "flow_manual_verification_required": "PAUSED_MANUAL_VERIFICATION",
    "flow_credits_exhausted": "PAUSED_CREDITS",
}

#: Provider error codes that mean the request itself is wrong; retrying cannot help.
FATAL_ERROR_CODES = {
    "model_not_available": "FAILED_MODEL_SELECTION",
    "model_selection_failed": "FAILED_MODEL_SELECTION",
    "model_feature_incompatible": "FAILED_MODEL_COMPATIBILITY",
    "flow_reference_policy_violation": "FAILED_VALIDATION",
    "flow_policy_violation": "FAILED_VALIDATION",
    "agent_disabled": "FAILED_VALIDATION",
}

#: Transient conditions where a bounded retry in a fresh tab is legitimate.
RETRYABLE_ERROR_CODES = {
    "tab_lost",
    "flow_tab_lost",
    "submit_failed",
    "response_timeout",
    "provider_ui_changed",
    "flow_ui_changed",
    "chrome_control_unavailable",
    "chrome_not_open",
}

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "manual_verification_required"}


class OrdakJobError(RuntimeError):
    """A provider job that did not complete successfully."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        job_id: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = (error_code or "").strip().lower() or None
        self.job_id = job_id
        self.status = status
        self.payload = payload or {}

    @property
    def pipeline_state(self) -> str:
        """Map the provider error onto a pipeline state (master_prompt §81)."""
        if self.error_code in PAUSE_ERROR_CODES:
            return PAUSE_ERROR_CODES[self.error_code]
        if self.error_code in FATAL_ERROR_CODES:
            return FATAL_ERROR_CODES[self.error_code]
        if self.error_code in {"upload_incomplete", "flow_upload_failed", "flow_frame_upload_failed"}:
            return "FAILED_UPLOAD"
        if self.error_code in {"flow_download_failed", "result_not_extractable", "flow_result_not_found"}:
            return "FAILED_DOWNLOAD"
        if self.error_code in {"invalid_video_output"}:
            return "FAILED_VALIDATION"
        if self.error_code in {"provider_ui_changed", "flow_ui_changed"}:
            return "FAILED_UI_CHANGED"
        return "FAILED"

    @property
    def needs_human(self) -> bool:
        return self.error_code in PAUSE_ERROR_CODES

    @property
    def retryable(self) -> bool:
        return self.error_code in RETRYABLE_ERROR_CODES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Generation:
    """The explicit generation contract for one provider call."""

    model: str | None = None
    quality: str | None = None
    aspect_ratio: str | None = None
    duration_seconds: int | None = None
    resolution: str | None = None

    def as_form(self) -> dict[str, str]:
        form: dict[str, str] = {}
        if self.model:
            form["model"] = self.model
        if self.quality:
            form["quality"] = self.quality
        if self.aspect_ratio:
            form["aspect_ratio"] = self.aspect_ratio
        if self.duration_seconds is not None:
            form["duration_seconds"] = str(int(self.duration_seconds))
        if self.resolution:
            form["resolution"] = self.resolution
        return form

    def as_json(self) -> dict[str, Any] | None:
        payload = {
            "model": self.model,
            "quality": self.quality,
            "aspect_ratio": self.aspect_ratio,
            "duration_seconds": self.duration_seconds,
            "resolution": self.resolution,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return payload or None


@dataclass(frozen=True)
class Reference:
    """One upload plus the role it plays in the job."""

    role: str
    path: Path

    def sha256(self) -> str:
        return sha256_file(self.path)


@dataclass
class OrdakSettings:
    base_url: str = "http://127.0.0.1:8000"
    wait_seconds: int = 900
    poll_seconds: float = 3.0
    api_retry_window_seconds: float = 90.0

    @classmethod
    def from_environment(cls) -> "OrdakSettings":
        return cls(
            base_url=os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            wait_seconds=int(os.getenv("YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS", "900")),
            poll_seconds=float(os.getenv("YT_ORDAK_JOB_POLL_SECONDS", "3")),
        )


@dataclass
class JobResult:
    job_id: str
    status: str
    answer: str | None
    output_images: list[str] = field(default_factory=list)
    output_videos: list[str] = field(default_factory=list)
    generation_receipt: dict[str, Any] = field(default_factory=dict)
    references: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class OrdakJobs:
    """Thin, retry-aware client over the Ordak job API."""

    def __init__(self, settings: OrdakSettings | None = None) -> None:
        self.settings = settings or OrdakSettings.from_environment()
        # trust_env=False keeps local Ordak traffic off any ambient HTTP(S)_PROXY.
        self.http = httpx.Client(
            timeout=httpx.Timeout(60.0, read=max(90.0, self.settings.poll_seconds * 10)),
            trust_env=False,
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "OrdakJobs":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Survive a brief Ordak API restart without losing an in-flight job."""
        url = f"{self.settings.base_url}{path}"
        deadline = time.monotonic() + self.settings.api_retry_window_seconds
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.http.request(method, url, **kwargs)
                if response.status_code not in {502, 503, 504}:
                    return response
                error: Exception = RuntimeError(f"Ordak API returned HTTP {response.status_code}")
            except httpx.TransportError as exc:
                error = exc
            if time.monotonic() >= deadline:
                raise OrdakJobError(
                    f"Ordak API unavailable for {int(self.settings.api_retry_window_seconds)}s "
                    f"while {method} {path}: {error}"
                ) from error
            time.sleep(min(8.0, 2.0 ** min(attempt - 1, 3)))

    # -- readiness ---------------------------------------------------------

    def health(self) -> dict[str, Any]:
        response = self._request("GET", "/api/health")
        response.raise_for_status()
        return response.json()

    def diagnostics(self) -> dict[str, Any]:
        response = self._request("GET", "/api/diagnostics")
        response.raise_for_status()
        return response.json()

    def require_ready(self, providers: Sequence[str] = ()) -> dict[str, Any]:
        """Fail before spending anything when the browser stack is not usable (§65).

        Ordak can only report a provider's login state once a tab for it exists, so a
        provider with no open tab is reported as *unverified* rather than "ready" — the
        authoritative check happens when the worker opens the tab.
        """
        self.health()
        data = self.diagnostics()
        if not data.get("chrome_running"):
            raise OrdakJobError(
                "Chrome is not running; the browser automation stack is unavailable.",
                error_code="chrome_not_open",
            )
        sessions = data.get("provider_sessions") or {}
        blocked: list[str] = []
        unverified: list[str] = []
        for provider in providers:
            session = sessions.get(provider) or {}
            state = str(session.get("login_state") or "").lower()
            if state in {"login_required", "manual_verification_required"}:
                blocked.append(f"{provider}={state}")
            elif not session.get("logged_in"):
                unverified.append(provider)
        if blocked:
            raise OrdakJobError(
                "Provider session needs a human: " + ", ".join(blocked),
                error_code="login_required",
            )
        data["_unverified_providers"] = unverified
        return data

    # -- job submission ----------------------------------------------------

    def submit(
        self,
        question: str,
        *,
        provider: str,
        mode: str,
        generation: Generation | None = None,
        references: Sequence[Reference] = (),
        start_new_chat: bool = True,
        conversation_id: str | None = None,
    ) -> str:
        """Create a job and return its id. Uploads carry an explicit role each."""
        if references:
            files: list[tuple[str, tuple[str, bytes, str]]] = []
            form: dict[str, Any] = {
                "question": question,
                "provider": provider,
                "mode": mode,
                "start_new_chat": "true" if start_new_chat else "false",
                "wait_for_completion": "false",
            }
            if conversation_id:
                form["conversation_id"] = conversation_id
            form.update(generation.as_form() if generation else {})
            roles: list[str] = []
            for ref in references:
                path = Path(ref.path)
                if not path.is_file():
                    raise OrdakJobError(f"Reference {ref.role} missing on disk: {path}")
                roles.append(ref.role)
                files.append(("image", (path.name, path.read_bytes(), "image/png")))
            form["role"] = roles
            response = self._request("POST", "/api/jobs", data=form, files=files)
        else:
            payload: dict[str, Any] = {
                "question": question,
                "provider": provider,
                "mode": mode,
                "start_new_chat": start_new_chat,
            }
            if conversation_id:
                payload["conversation_id"] = conversation_id
            if generation is not None and generation.as_json():
                payload["generation"] = generation.as_json()
            response = self._request("POST", "/api/jobs", json=payload)

        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail") or "")
            except Exception:
                detail = response.text[:400]
            raise OrdakJobError(
                f"Ordak rejected the {provider}/{mode} job: {detail}",
                error_code="flow_reference_policy_violation" if "style-sheet" in detail else None,
            )
        return str(response.json()["job_id"])

    def fetch(self, job_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/api/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def wait(
        self,
        job_id: str,
        *,
        timeout_seconds: int | None = None,
        on_log: Any = None,
    ) -> JobResult:
        """Poll a job to a terminal status. Raises OrdakJobError unless it completed."""
        limit = timeout_seconds or self.settings.wait_seconds
        started = time.perf_counter()
        deadline = time.monotonic() + limit
        seen_logs = 0
        payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            payload = self.fetch(job_id)
            if on_log is not None:
                logs = payload.get("logs") or []
                for entry in logs[seen_logs:]:
                    on_log(str(entry.get("message") or ""))
                seen_logs = len(logs)
            status = str(payload.get("status") or "")
            if status in TERMINAL_STATUSES:
                elapsed = round(time.perf_counter() - started, 3)
                if status != "completed":
                    raise OrdakJobError(
                        payload.get("error_message")
                        or f"{payload.get('provider')} job {job_id} ended as {status}",
                        error_code=payload.get("error_code"),
                        job_id=job_id,
                        status=status,
                        payload=payload,
                    )
                return JobResult(
                    job_id=job_id,
                    status=status,
                    answer=payload.get("answer"),
                    output_images=list(payload.get("output_images") or []),
                    output_videos=list(payload.get("output_videos") or []),
                    generation_receipt=dict(payload.get("generation_receipt") or {}),
                    references=list(payload.get("references") or []),
                    elapsed_seconds=elapsed,
                    raw=payload,
                )
            time.sleep(self.settings.poll_seconds)
        raise OrdakJobError(
            f"Job {job_id} did not reach a terminal status within {limit}s",
            error_code="response_timeout",
            job_id=job_id,
            status=str(payload.get("status") or "unknown"),
            payload=payload,
        )

    def run(
        self,
        question: str,
        *,
        provider: str,
        mode: str,
        generation: Generation | None = None,
        references: Sequence[Reference] = (),
        start_new_chat: bool = True,
        timeout_seconds: int | None = None,
        attempts: int = 1,
        on_log: Any = None,
    ) -> JobResult:
        """Submit and wait. ``attempts`` only ever retries transient browser faults.

        A model/policy/credit/login failure is never retried: retrying those either
        cannot succeed or would spend provider credits blindly (§22, §80).
        """
        last: OrdakJobError | None = None
        for attempt in range(1, max(1, attempts) + 1):
            job_id = self.submit(
                question,
                provider=provider,
                mode=mode,
                generation=generation,
                references=references,
                start_new_chat=start_new_chat,
            )
            try:
                return self.wait(job_id, timeout_seconds=timeout_seconds, on_log=on_log)
            except OrdakJobError as exc:
                last = exc
                if not exc.retryable or attempt >= attempts:
                    raise
                time.sleep(min(20.0, 3.0 * attempt))
        raise last or OrdakJobError(f"{provider}/{mode} job failed")

    # -- artifact download -------------------------------------------------

    def download(self, artifact: str, destination: Path) -> Path:
        """Download one job artifact to ``destination`` atomically."""
        url = artifact if artifact.startswith("http") else f"{self.settings.base_url}/{artifact.lstrip('/')}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".part")
        with self.http.stream("GET", url, timeout=300.0) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 256):
                    handle.write(chunk)
        tmp.replace(destination)
        return destination


def submission_fingerprint(parts: Iterable[str]) -> str:
    """Stable fingerprint for a paid generation, used for credit-safe reconciliation."""
    joined = "\n".join(str(part) for part in parts)
    return sha256_text(joined)[:32]


__all__ = [
    "FATAL_ERROR_CODES",
    "Generation",
    "JobResult",
    "OrdakJobError",
    "OrdakJobs",
    "OrdakSettings",
    "PAUSE_ERROR_CODES",
    "RETRYABLE_ERROR_CODES",
    "Reference",
    "sha256_file",
    "sha256_text",
    "submission_fingerprint",
]
