#!/usr/bin/env python3
"""Ask ChatGPT through Ordak for a strict SFX plan, never for asset acquisition."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from ordak_jobs import OrdakJobs,OrdakJobError
from sfx_plan import SCHEMA_VERSION,SFXPlanError,load,path,validate,write
def compact(project:Path)->dict:
 timeline=json.loads((project/'timeline'/'TIMELINE.json').read_text()); words=json.loads((project/'timing'/'WORD_TIMINGS.json').read_text()).get('words',[])
 beats=[{k:b.get(k) for k in ('beat_id','start','end','narration','transition_in','transition_seconds','media_type')} for b in timeline.get('beats',[])]
 return {'duration':timeline['duration'],'opening':[b for b in beats if str(b.get('beat_id','')).startswith('video_opening')],'beats':beats,'words':[{k:w.get(k) for k in ('text','start','end')} for w in words], 'script':(project/'SCRIPT_FINAL.md').read_text(encoding='utf-8')[:12000], 'visual_beats':(project/'VISUAL_BEATS.md').read_text(encoding='utf-8')[:12000]}
def main():
 p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('--style',choices=('restrained','balanced','expressive'),default='restrained');p.add_argument('--max-events-per-minute',type=float,default=4);p.add_argument('--minimum-gap-seconds',type=float,default=2);p.add_argument('--force',action='store_true');a=p.parse_args(); project=a.project.resolve()
 context=compact(project); prompt=f'''You are a restrained video sound designer. Most moments need NO SFX. Return ONLY JSON, schema_version {SCHEMA_VERSION}, with episode_duration_seconds, planner, and events. Event fields: event_id, at, window_start, window_end, category (foley|ambience|transition|impact|water|weather|mechanical|crowd), intent, search_query, alternate_queries, desired_duration_seconds, max_duration_seconds, priority, suggested_gain_db, speech_overlap, reason. Max {a.max_events_per_minute}/minute; minimum gap {a.minimum_gap_seconds}s. Avoid whooshes on cuts, meme sounds, and narration competition. Use final visual/narration timing:\n{json.dumps(context,ensure_ascii=False,separators=(',',':'))}'''
 fingerprint=hashlib.sha256(json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if path(project).is_file() and not a.force:
  old=load(project)
  if old.get('timeline_context_sha256')==fingerprint:
   validate(old,max_events_per_minute=a.max_events_per_minute,minimum_gap_seconds=a.minimum_gap_seconds); print('SFX PLAN: REUSED');return
 raw=''; err=''
 with OrdakJobs() as jobs:
  for attempt in range(2):
   raw=jobs.run(prompt if not attempt else f'Previous output was invalid: {err}. Return corrected raw JSON only.\n{prompt}',provider='chatgpt',mode='chat').answer or ''
   try:
    payload=json.loads(raw.strip().removeprefix('```json').removesuffix('```').strip())
    if not isinstance(payload, dict):
     raise SFXPlanError("planner response must be a JSON object")
    planner = payload.get('planner')
    payload['planner'] = dict(planner) if isinstance(planner, dict) else {}
    payload['planner'].update({'provider':'chatgpt_ordak','style':a.style})
    payload['timeline_context_sha256']=fingerprint
    write(project,payload,max_events_per_minute=a.max_events_per_minute,minimum_gap_seconds=a.minimum_gap_seconds)
    (project/'sfx'/'SFX_PLAN_RECEIPT.json').write_text(json.dumps({'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'timeline_context_sha256':fingerprint,'attempt':attempt+1},indent=2)+'\n')
    print('SFX PLAN: PASS');return
   except (ValueError,SFXPlanError) as e: err=str(e)
 raise SystemExit('SFX planner returned invalid JSON after 2 attempts: '+err)
if __name__=='__main__':main()
