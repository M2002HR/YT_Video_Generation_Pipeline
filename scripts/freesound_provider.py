"""Small official Freesound API v2 client. No browser automation or scraping."""
from __future__ import annotations
import os,time
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv
class FreesoundError(RuntimeError): pass
class FreesoundProvider:
 def __init__(self, token:str|None=None, *, base_url:str="https://freesound.org/apiv2"):
  # Panel jobs inherit a process environment rather than a shell that sourced .env.
  # Load the project's single local runtime config without ever serializing it.
  load_dotenv(Path(__file__).resolve().parents[1] / '.env')
  self.token=token or os.getenv("FREESOUND_OAUTH_TOKEN") or os.getenv("FREESOUND_API_KEY")
  if not self.token: raise FreesoundError("Freesound is enabled but FREESOUND_API_KEY or FREESOUND_OAUTH_TOKEN is not configured.")
  self.base=base_url.rstrip('/'); self.http=httpx.Client(timeout=30,headers={"Authorization":f"Token {self.token}"})
 def close(self): self.http.close()
 def __enter__(self): return self
 def __exit__(self,*x): self.close()
 def request(self, method:str,url:str,**kw:Any)->httpx.Response:
  for attempt in range(4):
   r=self.http.request(method,url,**kw)
   if r.status_code not in {429,500,502,503,504}:
    if r.status_code in {401,403}: raise FreesoundError(f"Freesound authorization failed (HTTP {r.status_code}); check token scope and API terms.")
    r.raise_for_status(); return r
   if attempt==3: raise FreesoundError(f"Freesound transient failure HTTP {r.status_code} after bounded retries")
   time.sleep(float(r.headers.get('Retry-After',min(8,2**attempt))))
  raise AssertionError
 def search(self, query:str, *, count:int=12, max_duration:float|None=None)->list[dict[str,Any]]:
  params={"query":query,"page_size":min(max(1,count),50),"fields":"id,name,description,tags,username,license,duration,filesize,type,channels,samplerate,bitdepth,num_downloads,avg_rating,url,previews"}
  if max_duration: params['filter']=f"duration:[0 TO {max_duration}]"
  return list(self.request("GET",self.base+"/search/text/",params=params).json().get("results") or [])
 def download(self, candidate:dict[str,Any], destination:Path)->None:
  # API exposes preview URLs in search responses. Original download can require OAuth scope;
  # prefer it only when supplied by metadata, otherwise use a documented preview URL.
  url=candidate.get('download') or ((candidate.get('previews') or {}).get('preview-hq-mp3'))
  if not url: raise FreesoundError("Freesound candidate has no downloadable preview/original URL")
  destination.parent.mkdir(parents=True,exist_ok=True)
  with self.http.stream("GET",url) as r:
   r.raise_for_status()
   if int(r.headers.get("Content-Length") or 0) > 8 * 1024 * 1024:
    raise FreesoundError("Freesound candidate exceeds the 8 MiB one-shot download limit")
   with destination.open('wb') as f:
    for chunk in r.iter_bytes(262144): f.write(chunk)
