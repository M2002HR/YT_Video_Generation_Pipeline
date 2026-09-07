"""Offline contract tests for the SFX planner, library, and acquire cache behavior."""
from __future__ import annotations
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from sfx_plan import SFXPlanError,validate
from sfx_library import SFXLibrary
def plan(events=None):
 return {'schema_version':1,'episode_duration_seconds':60,'planner':{'provider':'test'},'events':events if events is not None else [{'event_id':'sfx_001','at':5,'window_start':4.5,'window_end':5.5,'category':'foley','intent':'book','search_query':'book page turn','alternate_queries':['page turn'],'desired_duration_seconds':1,'max_duration_seconds':2,'priority':'high','suggested_gain_db':-14,'speech_overlap':False,'reason':'visible'}]}
def test_plan_normalizes_and_rejects_invalid():
 assert validate(plan())['events'][0]['event_id']=='sfx_001'
 bad=plan();bad['events'][0]['at']=61
 with pytest.raises(SFXPlanError):validate(bad)
 bad=plan();bad['events'].append(dict(bad['events'][0]))
 with pytest.raises(SFXPlanError):validate(bad)
 bad=plan();bad['events'][0]['category']='meme'
 with pytest.raises(SFXPlanError):validate(bad)
def test_library_metadata_search_duplicate_and_usage(tmp_path:Path):
 source=tmp_path/'sound.wav';source.write_bytes(b'not-decoded-but-library-metadata-test')
 with SFXLibrary(tmp_path/'lib') as library:
  asset=library.install({'provider':'freesound','provider_id':123,'name':'Old Book Page Turn','description':'soft paper','tags':['book','page'],'aliases':['book page turn'],'category':'foley','license':'CC0','duration_seconds':1.1},source)
  found=library.search('book page turn',category='foley',max_duration=2)
  assert found and found[0]['library_id']==asset['library_id']
  library.use(asset['library_id'],'antique book opening')
  row=library.db.execute('select usage_count,aliases from assets where library_id=?',(asset['library_id'],)).fetchone()
  assert row['usage_count']==1 and 'antique book opening' in row['aliases']
  second=tmp_path/'second.wav';second.write_bytes(Path(asset['file']).read_bytes())
  assert library.install({'provider':'freesound','provider_id':999,'name':'duplicate','license':'CC0'},second)['library_id']==asset['library_id']
def test_mix_receipt_integration(tmp_path:Path):
 from run_sfx_acquire import update_mix
 p=tmp_path/'audio_mix';p.mkdir();(p/'AUDIO_MIX_PROFILE.json').write_text(json.dumps({'sfx':{'enabled':False,'events':[]}}))
 update_mix(tmp_path,{'events':[{'selection_mode':'LOCAL_REUSE','file':'/safe/a.wav','at':2,'gain_db':-14,'duration_seconds':1}]})
 data=json.loads((p/'AUDIO_MIX_PROFILE.json').read_text());assert data['sfx']['enabled'] and data['sfx']['events'][0]['trim_sec']==1
