#!/usr/bin/env python3
"""``music/MUSIC_PLAN.json`` — the segment list a video's background music follows (T9.7).

Today an episode uses one track for its whole length, but the shape here is a *list of
segments* so a second cue can be added by appending an entry and its file. Nothing in the
schema, the validator or the audio-mix builder assumes there is exactly one.

Each segment records the search prompt that chose it, so the selection is auditable and a
resumed run can reuse the prompt rather than asking again.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1

#: How far segment boundaries may drift from the narration length before the plan is wrong.
COVERAGE_TOLERANCE_SECONDS = 0.25


class MusicPlanError(ValueError):
    """The plan does not describe a usable music timeline."""


@dataclass
class MusicSegment:
    """One continuous stretch of background music."""

    segment_id: str
    start_seconds: float
    end_seconds: float
    role: str = "bed"
    provider: str = "mixkit"
    query_prompt: str = ""
    source_url: str | None = None
    file: str | None = None
    gain_db: float = -20.0
    fade_in_seconds: float = 0.8
    fade_out_seconds: float = 1.4
    notes: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "duration_seconds": self.duration_seconds,
            "role": self.role,
            "provider": self.provider,
            "query_prompt": self.query_prompt,
            "source_url": self.source_url,
            "file": self.file,
            "gain_db": self.gain_db,
            "fade_in_seconds": self.fade_in_seconds,
            "fade_out_seconds": self.fade_out_seconds,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MusicSegment":
        return cls(
            segment_id=str(payload.get("segment_id") or "segment"),
            start_seconds=float(payload.get("start_seconds") or 0.0),
            end_seconds=float(payload.get("end_seconds") or 0.0),
            role=str(payload.get("role") or "bed"),
            provider=str(payload.get("provider") or "mixkit"),
            query_prompt=str(payload.get("query_prompt") or ""),
            source_url=payload.get("source_url"),
            file=payload.get("file"),
            gain_db=float(payload.get("gain_db", -20.0)),
            fade_in_seconds=float(payload.get("fade_in_seconds", 0.8)),
            fade_out_seconds=float(payload.get("fade_out_seconds", 1.4)),
            notes=[str(note) for note in (payload.get("notes") or [])],
        )


def plan_path(project: Path) -> Path:
    return Path(project) / "music" / "MUSIC_PLAN.json"


def validate_segments(segments: Sequence[MusicSegment], *, narration_seconds: float | None = None) -> None:
    """Ordered, positive-length, non-overlapping, and covering the narration."""
    if not segments:
        raise MusicPlanError("A music plan needs at least one segment.")
    identifiers = [segment.segment_id for segment in segments]
    if len(set(identifiers)) != len(identifiers):
        raise MusicPlanError(f"Duplicate music segment ids: {identifiers}")
    previous_end = 0.0
    for index, segment in enumerate(segments):
        if segment.end_seconds <= segment.start_seconds:
            raise MusicPlanError(
                f"Segment {segment.segment_id!r} ends at or before it starts "
                f"({segment.start_seconds} -> {segment.end_seconds})."
            )
        if index == 0 and segment.start_seconds > COVERAGE_TOLERANCE_SECONDS:
            raise MusicPlanError(
                f"The first music segment starts at {segment.start_seconds}s, leaving the "
                "opening without a bed."
            )
        if segment.start_seconds + COVERAGE_TOLERANCE_SECONDS < previous_end:
            raise MusicPlanError(
                f"Segment {segment.segment_id!r} overlaps the previous one "
                f"({segment.start_seconds} < {previous_end})."
            )
        if segment.start_seconds - COVERAGE_TOLERANCE_SECONDS > previous_end:
            raise MusicPlanError(
                f"Silence between {previous_end}s and {segment.start_seconds}s before "
                f"segment {segment.segment_id!r}."
            )
        previous_end = segment.end_seconds
    if narration_seconds:
        if abs(previous_end - narration_seconds) > COVERAGE_TOLERANCE_SECONDS:
            raise MusicPlanError(
                f"The plan covers {previous_end}s but the narration is {narration_seconds}s."
            )


def single_bed(
    *,
    narration_seconds: float,
    provider: str,
    query_prompt: str,
    source_url: str | None = None,
    file: str | None = None,
) -> list[MusicSegment]:
    """The one-track case, expressed in the same segment shape as everything else."""
    return [
        MusicSegment(
            segment_id="bed_001",
            start_seconds=0.0,
            end_seconds=round(float(narration_seconds), 3),
            role="bed",
            provider=provider,
            query_prompt=query_prompt,
            source_url=source_url,
            file=file,
        )
    ]


def write_plan(
    project: Path,
    segments: Sequence[MusicSegment],
    *,
    narration_seconds: float | None = None,
    status: str = "PLANNED",
) -> Path:
    validate_segments(segments, narration_seconds=narration_seconds)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "narration_seconds": round(float(narration_seconds), 3) if narration_seconds else None,
        "segment_count": len(segments),
        "segments": [segment.to_dict() for segment in segments],
    }
    path = plan_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_plan(project: Path) -> tuple[list[MusicSegment], dict[str, Any]]:
    path = plan_path(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = [MusicSegment.from_dict(entry) for entry in (payload.get("segments") or [])]
    return segments, payload


def segment_at(segments: Sequence[MusicSegment], moment: float) -> MusicSegment | None:
    for segment in segments:
        if segment.start_seconds <= moment < segment.end_seconds:
            return segment
    return None


def audio_mix_music_entries(segments: Sequence[MusicSegment]) -> list[dict[str, Any]]:
    """Segments in the shape the audio-mix profile consumes.

    One entry today, N entries the moment the plan has N segments — the mix builder reads
    this list rather than a single ``file`` key, so a second cue needs no code change.
    """
    return [
        {
            "file": segment.file,
            "start_seconds": round(segment.start_seconds, 3),
            "end_seconds": round(segment.end_seconds, 3),
            "gain_db": segment.gain_db,
            "fade_in_sec": segment.fade_in_seconds,
            "fade_out_sec": segment.fade_out_seconds,
            "segment_id": segment.segment_id,
        }
        for segment in segments
        if segment.file
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Show or validate a video's music plan.")
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    segments, payload = load_plan(args.project.expanduser().resolve())
    validate_segments(segments, narration_seconds=payload.get("narration_seconds"))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"MUSIC PLAN: OK ({len(segments)} segment(s))")


if __name__ == "__main__":
    main()
