from __future__ import annotations
import sys
from pathlib import Path
import pytest
import json, subprocess
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from motion_compiler import plan_render_units, solve_target
from motion_schema import MotionPlanError, motion_qc, validate_plan

TIMELINE={"duration":4.0,"beats":[{"beat_id":1,"media_type":"image","start":0.0,"end":4.0,"duration":4.0,"image":"assets/raw_beats/beat_001.png"}]}
PLAN={"schema_version":1,"duration_seconds":4.0,"settings":{"max_micro_shots_per_beat":3,"min_micro_shot_duration":.5},"beats":[{"beat_id":1,"start":0,"end":4,"micro_shots":[{"shot_id":"b1a","start":0,"end":1.2,"motion":"establish","target":{"label":"left","x":.2,"y":.4,"w":.2,"h":.3},"zoom_start":1,"zoom_end":1.04,"easing":"gentle"},{"shot_id":"b1b","start":1.2,"end":2.4,"motion":"reframe_cut","target":{"label":"right","x":.8,"y":.4,"w":.2,"h":.3},"zoom_start":1.15,"zoom_end":1.15,"easing":"snappy"},{"shot_id":"b1c","start":2.4,"end":4,"motion":"pan_pull","target":{"label":"right","x":.75,"y":.4,"w":.2,"h":.3},"zoom_start":1.2,"zoom_end":1.04,"easing":"ease_out"}],"transition_out":{"type":"cut","duration":0}}]}

def test_plan_accepts_same_image_multiple_microshots_and_real_cut():
    valid=validate_plan(PLAN,TIMELINE)
    units=plan_render_units(valid,TIMELINE["beats"])
    assert len(units)==3 and sum(x["duration"] for x in units)==pytest.approx(4)
    assert all(x["transition_in"]=="cut" for x in units)
    assert motion_qc(valid)["hard_cut_count"] >= 1

@pytest.mark.parametrize("mutator",[
    lambda p:p["beats"][0]["micro_shots"][0].update(motion="unknown"),
    lambda p:p["beats"][0]["micro_shots"][1].update(start=1.0),
    lambda p:p["beats"][0]["micro_shots"][0]["target"].update(w=-1),
    lambda p:p.update(duration_seconds=-1),
])
def test_plan_rejects_invalid_editorial_contract(mutator):
    import copy
    bad=copy.deepcopy(PLAN); mutator(bad)
    with pytest.raises(MotionPlanError): validate_plan(bad,TIMELINE)

def test_target_solver_clamps_edges_and_subtitle_collision():
    solved, changes=solve_target({"x":2,"y":1.3,"w":.1,"h":.2},subtitle_top=.78)
    assert 0 < solved["x"] < 1 and 0 < solved["y"] < .8
    assert changes

def test_dynamic_renderer_renders_one_image_as_multiple_shots(tmp_path: Path):
    """Regression: a semantic reframe cut is a real FFmpeg concat, with no duration drift."""
    video=tmp_path/"episode"; (video/"assets/raw_beats").mkdir(parents=True); (video/"assets/audio").mkdir(parents=True); (video/"timeline").mkdir(); (video/"render").mkdir(); (video/"motion").mkdir()
    image=Image.new("RGB",(640,360),(20,20,20)); image.paste((240,40,40),(20,80,220,280)); image.paste((40,240,40),(420,80,620,280)); image.save(video/"assets/raw_beats/beat_001.png")
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t","4","-c:a","aac",str(video/"assets/audio/narration.m4a")],check=True,capture_output=True)
    timeline={**TIMELINE,"audio":"assets/audio/narration.m4a","resolution":{"width":320,"height":568},"fps":15,"render_profile":"render/RENDER_PROFILE.json"}
    (video/"timeline/TIMELINE.json").write_text(json.dumps(timeline)); (video/"motion/MOTION_PLAN.json").write_text(json.dumps(PLAN)); (video/"render/RENDER_PROFILE.json").write_text(json.dumps({"motion":{"enabled":True,"supersample":1},"subtitles":{"enabled":False},"resource_limits":{"ffmpeg_threads":1,"filter_threads":1,"filter_complex_threads":1}}))
    out=video/"assets/renders/dynamic.mp4"
    result=subprocess.run([sys.executable,str(ROOT/"scripts/render_video.py"),str(video),"--output",str(out),"--no-telegram-progress"],capture_output=True,text=True,timeout=90)
    assert result.returncode==0, result.stderr+result.stdout
    probe=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(out)],capture_output=True,text=True,check=True)
    assert float(probe.stdout) == pytest.approx(4,.08)
