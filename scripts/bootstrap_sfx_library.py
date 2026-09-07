#!/usr/bin/env python3
"""Conservative reusable-library bootstrap using the same acquisition path."""
from __future__ import annotations
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CORE=['book page turn','book open','paper movement','soft whoosh','door open','footsteps','cloth movement','room ambience','wind','rain','water','metal impact','sports mat impact','soft applause']
def main():
 p=argparse.ArgumentParser();p.add_argument('--preset',choices=('core',),default='core');p.add_argument('--library-dir',type=Path);p.add_argument('--per-query',type=int,default=1);a=p.parse_args()
 with tempfile.TemporaryDirectory() as d:
  project=Path(d);(project/'sfx').mkdir();(project/'audio_mix').mkdir();(project/'audio_mix'/'AUDIO_MIX_PROFILE.json').write_text('{}')
  events=[{'event_id':f'bootstrap_{i:03d}','at':i*3.,'window_start':i*3.,'window_end':i*3.+1,'category':'foley','intent':q,'search_query':q,'alternate_queries':[],'desired_duration_seconds':2.,'max_duration_seconds':8.,'priority':'low','suggested_gain_db':-14.,'speech_overlap':False,'reason':'library bootstrap'} for i,q in enumerate(CORE)]
  (project/'sfx'/'SFX_PLAN.json').write_text(json.dumps({'schema_version':1,'episode_duration_seconds':max(60,len(events)*3+2),'planner':{'provider':'bootstrap','style':'restrained'},'events':events}))
  subprocess.run([sys.executable,str(ROOT/'scripts'/'run_sfx_acquire.py'),str(project),'--library-dir',str(a.library_dir) if a.library_dir else 'runtime/sfx_library','--candidate-count',str(a.per_query),'--max-queries-per-event','1'],check=True)
if __name__=='__main__':main()
