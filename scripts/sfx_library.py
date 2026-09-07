"""Persistent SQLite/FTS SFX library; provider-agnostic by design."""
from __future__ import annotations
import hashlib, json, os, re, shutil, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
DEFAULT_ROOT = Path(os.getenv("YT_SFX_LIBRARY_DIR", "runtime/sfx_library"))
def utcnow() -> str: return datetime.now(timezone.utc).isoformat()
def sha256(path: Path) -> str:
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
 return h.hexdigest()
class SFXLibrary:
 def __init__(self, root: Path|None=None):
  self.root=(root or DEFAULT_ROOT).expanduser().resolve(); self.root.mkdir(parents=True,exist_ok=True); (self.root/"assets").mkdir(exist_ok=True)
  self.db=sqlite3.connect(self.root/"index.sqlite3"); self.db.row_factory=sqlite3.Row
  self.db.executescript("""CREATE TABLE IF NOT EXISTS assets (library_id TEXT PRIMARY KEY,provider TEXT NOT NULL,provider_id TEXT NOT NULL,name TEXT,description TEXT,tags TEXT,aliases TEXT,category TEXT,creator TEXT,source_url TEXT,api_url TEXT,license TEXT,duration REAL,format TEXT,channels INTEGER,sample_rate INTEGER,bit_depth INTEGER,file_size INTEGER,file TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,downloaded_at TEXT,last_used_at TEXT,usage_count INTEGER NOT NULL DEFAULT 0,quality REAL DEFAULT 0,UNIQUE(provider,provider_id)); CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(library_id UNINDEXED,name,tags,description,aliases,category);""")
 def close(self): self.db.close()
 def __enter__(self): return self
 def __exit__(self,*x): self.close()
 def install(self, meta: dict[str,Any], source: Path) -> dict[str,Any]:
  digest=sha256(source); provider=str(meta["provider"]); provider_id=str(meta["provider_id"])
  row=self.db.execute("SELECT * FROM assets WHERE provider=? AND provider_id=? OR sha256=?",(provider,provider_id,digest)).fetchone()
  if row:
   source.unlink(missing_ok=True)
   return dict(row)
  declared = str(meta.get("format") or "").lower().split(",")[0]
  suffix = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg", "flac": ".flac", "m4a": ".m4a", "aac": ".aac"}.get(declared)
  suffix = suffix or (source.suffix.lower() if source.suffix.lower() in {".wav",".mp3",".ogg",".flac",".m4a",".aac"} else ".audio")
  lid=f"{provider}_{provider_id}"; dest=self.root/"assets"/f"{lid}_{digest[:12]}{suffix}"
  shutil.move(str(source), str(dest))
  record={"library_id":lid,"provider":provider,"provider_id":provider_id,"name":str(meta.get("name") or lid),"description":str(meta.get("description") or ""),"tags":json.dumps(meta.get("tags") or []),"aliases":json.dumps(meta.get("aliases") or []),"category":str(meta.get("category") or ""),"creator":str(meta.get("creator") or ""),"source_url":str(meta.get("source_url") or ""),"api_url":str(meta.get("api_url") or ""),"license":str(meta.get("license") or ""),"duration":float(meta.get("duration_seconds") or 0),"format":str(meta.get("format") or suffix.lstrip(".")),"channels":meta.get("channels"),"sample_rate":meta.get("sample_rate"),"bit_depth":meta.get("bit_depth"),"file_size":dest.stat().st_size,"file":str(dest),"sha256":digest,"downloaded_at":utcnow(),"last_used_at":None,"usage_count":0,"quality":float(meta.get("quality") or 0)}
  cols=",".join(record); self.db.execute(f"INSERT INTO assets ({cols}) VALUES ({','.join('?' for _ in record)})",tuple(record.values())); self.db.execute("INSERT INTO assets_fts VALUES (?,?,?,?,?,?)",(lid,record['name'],record['tags'],record['description'],record['aliases'],record['category'])); self.db.commit(); return record
 def search(self, query:str, *, category:str="", max_duration:float|None=None, licenses:tuple[str,...] = ("CC0",), limit:int=10)->list[dict[str,Any]]:
  words=" OR ".join('"'+x.replace('"','')+'"' for x in query.lower().split() if x) or '""'; sql="SELECT a.*, bm25(assets_fts) rank FROM assets_fts JOIN assets a USING(library_id) WHERE assets_fts MATCH ?"; args=[words]
  if category: sql+=" AND a.category=?"; args.append(category)
  if max_duration: sql+=" AND a.duration<=?"; args.append(float(max_duration))
  if licenses: sql+=" AND a.license IN (%s)" % ','.join('?' for _ in licenses); args.extend(licenses)
  rows=[]
  query_tokens=set(re.findall(r"[a-z0-9]+",query.lower()))
  for row in self.db.execute(sql+" ORDER BY rank LIMIT ?",(*args,limit)).fetchall():
   item=dict(row)
   if Path(item['file']).is_file():
    haystack=" ".join(str(item.get(key) or "") for key in ("name","tags","description","aliases","category")).lower()
    matched=sum(token in haystack for token in query_tokens)
    overlap=matched/max(1,len(query_tokens))
    # FTS chooses candidates efficiently; this explicit score is the stable,
    # human-auditable threshold used by local-first resolution.
    phrase_bonus=.15 if query.lower() in haystack else 0.0
    item['score']=round(min(1.0,overlap+phrase_bonus),3)
    rows.append(item)
  return rows
 def use(self, library_id:str, query:str)->None:
  row=self.db.execute("SELECT aliases FROM assets WHERE library_id=?",(library_id,)).fetchone()
  if not row: raise KeyError(library_id)
  aliases=set(json.loads(row['aliases'] or '[]')); aliases.add(query); self.db.execute("UPDATE assets SET usage_count=usage_count+1,last_used_at=?,aliases=? WHERE library_id=?",(utcnow(),json.dumps(sorted(aliases)),library_id)); self.db.execute("DELETE FROM assets_fts WHERE library_id=?",(library_id,)); a=self.db.execute("SELECT * FROM assets WHERE library_id=?",(library_id,)).fetchone(); self.db.execute("INSERT INTO assets_fts VALUES (?,?,?,?,?,?)",(library_id,a['name'],a['tags'],a['description'],a['aliases'],a['category'])); self.db.commit()
 def status(self)->dict[str,Any]:
  row=self.db.execute("SELECT count(*) n,coalesce(sum(file_size),0) b,max(downloaded_at) u FROM assets").fetchone(); return {"assets":row['n'],"bytes":row['b'],"last_updated":row['u']}
