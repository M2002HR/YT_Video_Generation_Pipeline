#!/usr/bin/env python3
"""Resolve SFX_PLAN locally first; Freesound is only a bounded cache-miss fallback."""
from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from freesound_provider import FreesoundProvider,FreesoundError
from sfx_library import SFXLibrary
from sfx_plan import load,validate
def allowed(policy:str)->tuple[str,...]: return ('CC0','Creative Commons 0') if policy=='cc0' else ('CC0','Creative Commons 0','Attribution')
def license_ok(value:str,policy:str)->bool:
 v=value.lower(); return ('zero' in v or 'cc0' in v) or (policy=='cc0_by' and 'attribution' in v and 'noncommercial' not in v)
def probe(path:Path,max_duration:float)->dict[str,Any]:
 if not path.is_file() or path.stat().st_size<512: raise ValueError('download is empty or too small')
 if not shutil.which('ffprobe'): raise RuntimeError('ffprobe is required to validate downloaded SFX')
 r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,format_name:stream=codec_type,channels,sample_rate,bits_per_sample','-of','json',str(path)],capture_output=True,text=True,timeout=20)
 try:data=json.loads(r.stdout); duration=float(data['format']['duration'])
 except Exception as e: raise ValueError('download is not decodable audio') from e
 if r.returncode or duration<=0 or duration>max(35,max_duration*5): raise ValueError('download has an invalid/absurd duration')
 stream=next((x for x in data.get('streams',[]) if x.get('codec_type')=='audio'),None)
 if not stream: raise ValueError('download has no audio stream')
 return {'duration_seconds':duration,'channels':stream.get('channels'),'sample_rate':stream.get('sample_rate'),'bit_depth':stream.get('bits_per_sample'),'format':str(data['format'].get('format_name') or path.suffix.lstrip('.')).split(',')[0]}
def selection_path(project:Path)->Path:return project/'sfx'/'SFX_SELECTION.json'
def search_variants(query: str) -> list[str]:
 """Keep planner prose useful while making Freesound's lexical search resilient.

 The provider returns no rows for some otherwise sensible six-to-eight-word phrases.
 Compact fallbacks are tried only after the exact planner query and remain ranked against
 the original intent, so this is not an unrelated broad search.
 """
 words = [word for word in query.split() if word]
 variants = [query]
 if len(words) > 3:
  variants.extend((" ".join(words[:3]), " ".join(words[-3:])))
 if len(words) > 2:
  variants.append(" ".join(words[:2]))
 return list(dict.fromkeys(item for item in variants if item.strip()))
def update_mix(project:Path, selection:dict, *, enabled:bool=True)->None:
 profile=project/'audio_mix'/'AUDIO_MIX_PROFILE.json'; data=json.loads(profile.read_text()) if profile.is_file() else {}
 events=[]
 for item in selection['events']:
  if item['selection_mode'] in ('LOCAL_REUSE','FREESOUND_DOWNLOAD'):
   events.append({'file':item['file'],'at':item['at'],'gain_db':item['gain_db'],'trim_sec':item['duration_seconds']})
 data['sfx']={'enabled':bool(enabled and events),'events':events}; profile.parent.mkdir(parents=True,exist_ok=True);profile.write_text(json.dumps(data,indent=2)+'\n')
def checkpoint(project: Path, plan: dict[str, Any], events: list[dict[str, Any]]) -> None:
 receipt={'schema_version':1,'status':'RUNNING','plan_context_sha256':plan.get('timeline_context_sha256'),'events':events}
 selection_path(project).parent.mkdir(parents=True,exist_ok=True)
 selection_path(project).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 update_mix(project,receipt)
def main():
 p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('--library-dir',type=Path,default=None);p.add_argument('--local-threshold',type=float,default=.35);p.add_argument('--license-policy',choices=('cc0','cc0_by'),default='cc0');p.add_argument('--candidate-count',type=int,default=12);p.add_argument('--max-queries-per-event',type=int,default=2);p.add_argument('--freesound-enabled',action=argparse.BooleanOptionalAction,default=True);p.add_argument('--default-gain-db',type=float,default=-14);p.add_argument('--min-gain-db',type=float,default=-28);p.add_argument('--max-gain-db',type=float,default=-6);a=p.parse_args(); project=a.project.resolve(); plan=validate(load(project)); previous=json.loads(selection_path(project).read_text()) if selection_path(project).is_file() else {}; existing={x['event_id']:x for x in previous.get('events',[]) if previous.get('plan_context_sha256')==plan.get('timeline_context_sha256')}; output=[]
 with SFXLibrary(a.library_dir) as lib:
  provider=None
  for event in plan['events']:
   prior=existing.get(event['event_id'])
   if prior and prior.get('selection_mode') in {'LOCAL_REUSE','FREESOUND_DOWNLOAD'} and Path(prior.get('file','')).is_file(): output.append(prior);checkpoint(project,plan,output);continue
   query=str(event['search_query']); candidates=[x for x in lib.search(query,category=event['category'],max_duration=event['max_duration_seconds'],licenses=()) if license_ok(str(x.get('license','')),a.license_policy)]
   chosen=next((x for x in candidates if x['score']>=a.local_threshold),None); mode='LOCAL_REUSE'
   if not chosen and a.freesound_enabled:
    if provider is None: provider=FreesoundProvider()
    remote=[]
    for q in [query,*event.get('alternate_queries',[])][:a.max_queries_per_event]:
     rows = provider.search(q,count=a.candidate_count,max_duration=event['max_duration_seconds'])
     # A duration-constrained request is preferred, but a short usable excerpt may be
     # trimmed from a longer validated file when Freesound has no exact short result.
     if not rows:
      for variant in search_variants(q)[1:]:
       rows = provider.search(variant,count=a.candidate_count)
       if rows:
        break
     remote.extend(rows)
     remote=[x for x in remote if license_ok(str(x.get('license','')),a.license_policy) and int(x.get('filesize') or 0) <= 8 * 1024 * 1024]
     # Drop candidates whose declared duration is already absurd vs the probe threshold
     # (max 35s or 5x max_duration). This avoids downloading a 90s podcast for a 2s window.
     remote=[x for x in remote if 0 < float(x.get('duration') or 0) <= max(35, event['max_duration_seconds']*5)]
     # deterministic text/duration/rating rank; no download before a candidate wins.
     remote.sort(key=lambda x:(sum(w in (' '.join(x.get('tags') or [])+' '+str(x.get('name',''))).lower() for w in query.lower().split()),-abs(float(x.get('duration') or 0)-event['desired_duration_seconds']),float(x.get('avg_rating') or 0),int(x.get('num_downloads') or 0)),reverse=True)
     if remote:
      for winner in remote:
       fd,tmp=tempfile.mkstemp(suffix='.'+str(winner.get('type') or 'mp3'),dir=lib.root);os.close(fd);temp=Path(tmp)
       try:
        provider.download(winner,temp); technical=probe(temp,event['max_duration_seconds']); meta={'provider':'freesound','provider_id':winner['id'],'name':winner.get('name'),'description':winner.get('description'),'tags':winner.get('tags') or [],'aliases':[query],'category':event['category'],'creator':winner.get('username'),'source_url':winner.get('url'),'api_url':f"https://freesound.org/apiv2/sounds/{winner['id']}/",'license':winner.get('license'),'quality':winner.get('avg_rating') or 0,**technical};chosen=lib.install(meta,temp);mode='FREESOUND_DOWNLOAD';break
       except Exception as e:
        temp.unlink(missing_ok=True); print(f"warn: freesound candidate {winner.get('id')} failed ({e}); trying next", file=sys.stderr); continue
   if chosen:
    # The panel's default is a narration-safe loudness floor, not merely a fallback
    # for missing planner fields. A planner may request a louder accent, never quietly
    # override the operator's chosen baseline.
    lib.use(chosen['library_id'],query); gain=max(a.min_gain_db,min(a.max_gain_db,max(a.default_gain_db,float(event.get('suggested_gain_db',a.default_gain_db))))); output.append({'event_id':event['event_id'],'at':event['at'],'intent':event['intent'],'query':query,'selection_mode':mode,'library_id':chosen['library_id'],'provider':chosen['provider'],'provider_id':chosen['provider_id'],'source_url':chosen['source_url'],'license':chosen['license'],'file':chosen['file'],'duration_seconds':min(float(chosen['duration']),event['max_duration_seconds']),'gain_db':gain,'score':chosen.get('score',1.0)})
   else: output.append({'event_id':event['event_id'],'at':event['at'],'intent':event['intent'],'query':query,'selection_mode':'SKIPPED_NO_GOOD_MATCH','gain_db':a.default_gain_db})
   checkpoint(project,plan,output)
  if provider: provider.close()
  receipt={'schema_version':1,'status':'DONE','plan_context_sha256':plan.get('timeline_context_sha256'),'events':output};selection_path(project).parent.mkdir(parents=True,exist_ok=True);selection_path(project).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');update_mix(project,receipt);print(f"SFX ACQUIRE: PASS ({sum(x['selection_mode']!='SKIPPED_NO_GOOD_MATCH' for x in output)}/{len(output)} resolved)")
if __name__=='__main__':main()
