"""Freesound-backed background-music provider: Ordak plans a query, never a URL."""
from __future__ import annotations
import json, os, shutil, sys, tempfile
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from freesound_provider import FreesoundProvider
from ordak_jobs import OrdakJobs
from run_sfx_acquire import license_ok, probe, search_variants
from sfx_library import SFXLibrary

LIBRARY_ROOT = Path(os.getenv("YT_FREESOUND_MUSIC_LIBRARY_DIR", "runtime/freesound_music_library"))

VOCAL_MARKERS = ("vocal", "vocals", "voice", "singer", "singing", "lyrics", "lyric", "song", "speech", "spoken", "chant", "choir", "a cappella")
NARRATION_CONFLICT_MARKERS = ("drill", "hiphop", "hip-hop", "trap", "hardbeat", "high-energy", "aggressive", "booming 808", "punchlines")

def instrumental_metadata(candidate: dict[str, Any]) -> bool:
    """Conservative metadata gate: a music recording is not assumed instrumental."""
    text = " ".join([str(candidate.get("name") or ""), str(candidate.get("description") or ""), " ".join(candidate.get("tags") or [])]).lower()
    return "instrumental" in text and not any(marker in text for marker in VOCAL_MARKERS + NARRATION_CONFLICT_MARKERS)

def query_from_ordak(context: str, duration: float) -> tuple[str, list[str]]:
    prompt = f'''Return ONLY JSON: {{"query":"...","alternate_queries":["..."]}}. Create a PRIMARY Freesound query of exactly 2 or 3 broad words, plus up to 3 alternate queries also of 2 or 3 words, for one INSTRUMENTAL background-music bed. Every query MUST contain the word "instrumental". Do not over-specify terms: Freesound search is lexical. No lyrics, vocals, speech, singing, sound effects, memes, abrupt drops, or cinematic impacts. It must support {duration:.1f} seconds of narration and may be looped. You are choosing SEARCH TERMS ONLY, never links or files. Video context:\n{context[:2400]}'''
    with OrdakJobs() as jobs:
        for attempt in range(2):
            raw = jobs.run(prompt if not attempt else "Return corrected raw JSON only. " + prompt, provider="chatgpt", mode="chat").answer or ""
            try:
                data=json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
                query=str(data.get("query") or "").strip()
                aliases=[str(x).strip() for x in data.get("alternate_queries",[]) if str(x).strip()]
                if 2 <= len(query.split()) <= 3 and "instrumental" in query.lower(): return query, [x for x in aliases if 2 <= len(x.split()) <= 3 and "instrumental" in x.lower()][:3]
            except (ValueError, AttributeError): pass
    raise RuntimeError("ChatGPT/Ordak did not return a usable Freesound music query.")

def materialize(source: Path, project: Path) -> Path:
    """Episode convenience link; the shared library remains canonical and deduplicated."""
    target = project / "assets" / "music" / f"freesound_background{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.samefile(source): return target
    target.unlink(missing_ok=True)
    try: os.link(source, target)
    except OSError: shutil.copy2(source, target)
    return target

def acquire(project: Path, context: str, narration_seconds: float, *, license_policy: str="cc0_by", threshold: float=.35, count: int=12) -> dict[str, Any]:
    query, aliases = query_from_ordak(context, narration_seconds)
    licenses = ("CC0",) if license_policy == "cc0" else ("CC0", "Creative Commons 0", "Attribution")
    with SFXLibrary(LIBRARY_ROOT) as library:
        local=[x for x in library.search(query, category="music", licenses=(), limit=count) if license_ok(str(x.get("license", "")), license_policy) and x["duration"] >= 10 and instrumental_metadata(x)]
        chosen=next((x for x in local if x.get("score",0)>=threshold),None); mode="LOCAL_REUSE"
        if chosen is None:
            remote=[]
            with FreesoundProvider() as provider:
                for q in [query, *aliases][:2]:
                    rows=provider.search(q,count=count)
                    if not rows:
                        for variant in search_variants(q)[1:]:
                            rows=provider.search(variant,count=count)
                            if rows: break
                    remote.extend(rows)
                remote=[x for x in remote if license_ok(str(x.get("license", "")),license_policy) and int(x.get("filesize") or 0)<=8*1024*1024 and float(x.get("duration") or 0)>=10 and instrumental_metadata(x)]
                remote.sort(key=lambda x:(sum(w in (str(x.get("name", ""))+" "+" ".join(x.get("tags") or [])).lower() for w in query.lower().split()),float(x.get("avg_rating") or 0),int(x.get("num_downloads") or 0),-abs(float(x.get("duration") or 0)-max(30,narration_seconds))),reverse=True)
                if remote:
                    winner=remote[0]
                    fd,tmp=tempfile.mkstemp(suffix=".audio",dir=library.root);os.close(fd); temporary=Path(tmp)
                    try:
                        provider.download(winner,temporary); technical=probe(temporary,max(60,narration_seconds))
                        chosen=library.install({"provider":"freesound","provider_id":winner["id"],"name":winner.get("name"),"description":winner.get("description"),"tags":winner.get("tags") or [],"aliases":[query,*aliases],"category":"music","creator":winner.get("username"),"source_url":winner.get("url"),"api_url":f"https://freesound.org/apiv2/sounds/{winner['id']}/","license":winner.get("license"),"quality":winner.get("avg_rating") or 0,**technical},temporary); mode="FREESOUND_DOWNLOAD"
                    except Exception:
                        temporary.unlink(missing_ok=True); raise
        if chosen is None: raise RuntimeError("Freesound returned no license-safe instrumental music candidate.")
        library.use(chosen["library_id"],query)
        episode_file=materialize(Path(chosen["file"]),project)
        return {"provider":"freesound","selection_mode":mode,"query":query,"alternate_queries":aliases,"library_id":chosen["library_id"],"provider_id":chosen["provider_id"],"source_url":chosen["source_url"],"license":chosen["license"],"file":str(episode_file.relative_to(project)),"library_file":chosen["file"],"duration_seconds":float(chosen["duration"]),"bytes":episode_file.stat().st_size}
