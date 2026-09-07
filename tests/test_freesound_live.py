"""Opt-in API smoke test; excluded from ordinary CI and never uses episode storage."""
from __future__ import annotations
import os,sys,tempfile
from pathlib import Path
import pytest
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
load_dotenv(ROOT / '.env')

@pytest.mark.skipif(os.getenv('RUN_FREESOUND_LIVE_TESTS') != '1', reason='set RUN_FREESOUND_LIVE_TESTS=1 with a local Freesound token')
def test_live_cc0_search_download_and_local_reuse() -> None:
 from freesound_provider import FreesoundProvider
 from run_sfx_acquire import license_ok,probe
 from sfx_library import SFXLibrary
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp)
  with FreesoundProvider() as provider, SFXLibrary(root/'library') as library:
   candidate=next((x for x in provider.search('short click',count=8,max_duration=5) if license_ok(str(x.get('license','')),'cc0')),None)
   if candidate is None: pytest.skip('no short CC0 candidate returned by Freesound')
   temporary=root/'download.mp3';provider.download(candidate,temporary);technical=probe(temporary,5)
   asset=library.install({'provider':'freesound','provider_id':candidate['id'],'name':candidate.get('name'),'description':candidate.get('description'),'tags':candidate.get('tags') or [],'aliases':['short click'],'category':'foley','creator':candidate.get('username'),'source_url':candidate.get('url'),'license':candidate.get('license'),**technical},temporary)
   assert any(x['library_id']==asset['library_id'] for x in library.search('short click',licenses=()))
