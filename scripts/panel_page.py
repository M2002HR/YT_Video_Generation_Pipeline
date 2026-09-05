#!/usr/bin/env python3
"""The control panel's single page: a studio layout, rendered server-side.

Kept out of ``video_control_panel.py`` so the handler stays readable and the markup can be
edited without scrolling past request plumbing. Everything lives on one page — launching,
provider health, the runs list, the live log, and the artifacts an episode produced — so a
long run can be watched from where it was started, with no navigation (§62-64, T9.2).

The page is deliberately static HTML plus a small amount of vanilla JavaScript polling
``/api/status`` and ``/api/log/<job>``. No build step, no framework, no CDN: the panel has to
work on a server with no outbound access to anything but the providers.
"""
from __future__ import annotations

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#0b0e14; --panel:#121722; --panel-2:#161c29; --line:#232c3d; --line-2:#2e3950;
  --ink:#e7ecf5; --ink-dim:#9aa7bd; --ink-faint:#6b768c;
  --accent:#6ea8fe; --accent-ink:#0b1220;
  --ok:#5fd39b; --ok-bg:#0f2a1e; --ok-line:#245c41;
  --warn:#e9c46a; --warn-bg:#2b2412; --warn-line:#5f4f24;
  --bad:#ff8f8f; --bad-bg:#2c1414; --bad-line:#5f2626;
  --radius:10px; --radius-sm:6px;
}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
.wrap{max-width:1500px;margin:0 auto;padding:20px 22px 56px}

header.top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
header.top h1{font-size:19px;margin:0;letter-spacing:-.2px}
header.top .sub{color:var(--ink-dim);font-size:13px}
header.top .spacer{flex:1}
header.top .addr{color:var(--ink-dim);font-size:12px;font-family:ui-monospace,monospace}

#health{display:flex;flex-wrap:wrap;gap:7px;align-items:center;
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 12px;margin:12px 0 16px}
.msg{margin:0 0 16px;padding:10px 12px;border-radius:var(--radius-sm);font-size:14px;
  background:var(--ok-bg);border:1px solid var(--ok-line);color:var(--ok)}
.msg:empty{display:none}

.cols{display:grid;grid-template-columns:minmax(380px,1fr) minmax(0,1.25fr);gap:18px;align-items:start}
@media (max-width:1080px){.cols{grid-template-columns:1fr}}

.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:18px}
.card>h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim);
  margin:0;padding:12px 14px;border-bottom:1px solid var(--line);font-weight:600}
.card>.body{padding:14px}

fieldset{border:0;border-top:1px solid var(--line);margin:0;padding:14px 0 4px}
fieldset:first-of-type{border-top:0;padding-top:0}
legend{padding:0;color:var(--accent);font-weight:600;font-size:13px;
  text-transform:uppercase;letter-spacing:.06em}
label{display:block;margin:11px 0 0;font-size:13px;color:var(--ink-dim)}
label>span.q{color:var(--ink);font-size:14px}
input,select,textarea{display:block;width:100%;margin-top:5px;padding:8px 10px;
  background:var(--panel-2);color:var(--ink);border:1px solid var(--line-2);
  border-radius:var(--radius-sm);font:inherit;font-size:14px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:-1px;border-color:transparent}
input:disabled{color:var(--ink-dim);background:#10141d}
textarea{min-height:64px;resize:vertical}
input[type=checkbox]{display:inline-block;width:auto;margin:0 8px 0 0;vertical-align:-2px}
label.check{color:var(--ink);font-size:14px}
small{display:block;color:var(--ink-dim);font-size:12px;margin-top:3px}
label small{margin-top:4px}

.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
@media (max-width:520px){.grid2{grid-template-columns:1fr}}

button{font:inherit;font-weight:600;cursor:pointer;border:0;border-radius:var(--radius-sm)}
button.primary{width:100%;margin-top:18px;padding:12px 18px;font-size:15px;
  background:var(--accent);color:var(--accent-ink)}
button.primary:hover{filter:brightness(1.08)}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--line-2);
  padding:4px 9px;font-size:12px;font-weight:600}
button.ghost:hover{border-color:var(--accent)}
button.ghost.danger{color:var(--bad)}
button.ghost.danger:hover{border-color:var(--bad-line)}
button.ghost:disabled{color:var(--ink-dim);border-color:var(--line);cursor:not-allowed}

.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:99px;
  font-size:12px;font-weight:600;white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok);border:1px solid var(--ok-line)}
.pill.warn{background:var(--warn-bg);color:var(--warn);border:1px solid var(--warn-line)}
.pill.bad{background:var(--bad-bg);color:var(--bad);border:1px solid var(--bad-line)}
.pill.idle{background:#171d2a;color:var(--ink-dim);border:1px solid var(--line-2)}

table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--ink-dim);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.06em;padding:0 10px 8px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
tr.sel td{background:#141b2b}
td.actions{white-space:nowrap;text-align:right}
td.actions button{margin-left:5px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}

.bar{height:5px;background:#1b2231;border-radius:99px;overflow:hidden;margin-top:5px;min-width:96px}
.bar>i{display:block;height:100%;background:var(--accent);border-radius:99px}
.stage{color:var(--ink-dim);font-size:12px}

#logwrap{position:relative}
#log{margin:0;padding:12px 14px;height:460px;overflow:auto;white-space:pre-wrap;word-break:break-word;
  background:#080b11;color:#cfd8e6;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12px;line-height:1.55;border-radius:0 0 var(--radius) var(--radius)}
#log .s{color:var(--ok)}#log .f{color:var(--bad)}#log .r{color:var(--warn)}#log .b{color:var(--accent)}
.logbar{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--line);
  font-size:12px;color:var(--ink-dim)}
.logbar .spacer{flex:1}
.empty{color:var(--ink-dim);font-size:13px;padding:6px 2px}

.notice{background:#141b2b;border-left:3px solid var(--accent);padding:9px 12px;
  border-radius:var(--radius-sm);font-size:13px;color:var(--ink-dim);margin:0 0 12px}
.notice.wait{border-left-color:var(--warn)}
.notice b{color:var(--ink)}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}
.shots figure{margin:0}
.shots img{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:var(--radius-sm);
  border:1px solid var(--line-2);background:#0a0d13;display:block}
.shots figcaption{font-size:10px;color:var(--ink-dim);margin-top:3px;text-align:center;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""


SCRIPT = r"""
var tailed = null, tailOffset = 0, follow = true;

function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

function badgeClass(entry){
  if (entry.state === 'login_required' || entry.state === 'manual_verification_required') return 'bad';
  if (entry.logged_in === true && entry.state === 'ready') return 'ok';
  if (entry.state === 'ready') return 'idle';
  return 'warn';
}

function providerLabel(entry){
  if (entry.logged_in === true) return 'signed in';
  // Ordak keeps one work tab, so the providers not in use have no tab to confirm.
  if (entry.state === 'ready' && entry.tabs === 0) return 'idle (no tab)';
  return entry.state;
}

function renderHealth(ordak){
  var host = document.getElementById('health');
  if (!ordak || !ordak.reachable) {
    host.innerHTML = '<span class="pill bad">Ordak unreachable</span>' +
      '<span class="mono" style="color:var(--ink-dim)">' + esc(ordak && ordak.error) + '</span>';
    return;
  }
  var out = ['<span class="pill ' + (ordak.chrome_running ? 'ok' : 'bad') + '">Chrome ' +
             (ordak.chrome_running ? 'running' : 'down') + '</span>'];
  Object.keys(ordak.providers || {}).forEach(function(name){
    var e = ordak.providers[name];
    out.push('<span class="pill ' + badgeClass(e) + '">' + esc(name) + ': ' + esc(providerLabel(e)) + '</span>');
  });
  out.push('<span class="spacer" style="flex:1"></span>');
  out.push('<a class="mono" href="/logs/" style="display:none"></a>');
  host.innerHTML = out.join('');
}

function statusPill(job){
  var s = job.status || '—';
  var cls = s === 'DONE' ? 'ok'
          : s === 'RUNNING' ? 'warn'
          : s === 'WAITING_FOR_FLOW' ? 'warn'
          : (s === 'FAILED' || s === 'STOPPED') ? 'bad' : 'idle';
  var label = s === 'WAITING_FOR_FLOW' ? 'waiting for Flow' : s.toLowerCase();
  return '<span class="pill ' + cls + '">' + esc(label) + '</span>';
}

function renderJobs(jobs){
  var body = document.querySelector('#runs tbody');
  if (!jobs || !jobs.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">No runs yet.</td></tr>';
    return;
  }
  body.innerHTML = jobs.map(function(job){
    var p = job.pipeline || {};
    var pct = p.stage_count ? Math.round(100 * (p.done || 0) / p.stage_count) : 0;
    var progress = p.stage_count
      ? '<div class="stage">' + (p.done || 0) + '/' + p.stage_count +
        (p.current ? ' · ' + esc(p.current) : '') + '</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div>'
      : '<span class="stage">—</span>';
    var what = job.kind === 'flow_watcher'
      ? '<b>Flow watcher</b><div class="stage">every ' +
        Math.round((job.interval_seconds || 1200) / 60) + ' min · video ' + esc(job.video_id) + '</div>'
      : '<b>' + esc(job.video_id || '—') + '</b><div class="stage">' + esc(job.topic || '') + '</div>';
    var acts = ['<button class="ghost" onclick="tail(\'' + job.job_id + '\')">Log</button>'];
    if (job.resumable) acts.push('<button class="ghost" onclick="post(\'/resume\',\'' + job.job_id + '\')">Resume</button>');
    if (job.stoppable) acts.push('<button class="ghost danger" onclick="post(\'/stop\',\'' + job.job_id + '\')">Stop</button>');
    acts.push('<button class="ghost danger" onclick="del(\'' + job.job_id + '\')">Delete</button>');
    return '<tr class="' + (tailed === job.job_id ? 'sel' : '') + '">' +
      '<td>' + what + '</td>' +
      '<td>' + statusPill(job) + (job.flow_pending && job.flow_pending.missing_clips
          ? '<div class="stage">missing: ' + esc((job.flow_pending.missing_clips || []).join(', ')) + '</div>' : '') + '</td>' +
      '<td>' + progress + '</td>' +
      '<td class="mono" style="color:var(--ink-dim)">' + esc((job.created_at || '').slice(0, 19).replace('T', ' ')) + '</td>' +
      '<td class="actions">' + acts.join('') + '</td>' +
    '</tr>';
  }).join('');
}

function post(path, jobId){
  var f = document.createElement('form');
  f.method = 'post'; f.action = path;
  var i = document.createElement('input');
  i.type = 'hidden'; i.name = 'job_id'; i.value = jobId;
  f.appendChild(i); document.body.appendChild(f); f.submit();
}

function del(jobId){
  if (!confirm('Remove this run from the panel? Files under videos/ are kept.')) return;
  post('/delete', jobId);
}

function tail(jobId){
  tailed = jobId; tailOffset = 0; follow = true;
  document.getElementById('log').textContent = '';
  document.getElementById('logfor').textContent = jobId.slice(0, 8);
  pollLog();
}

function colourise(text){
  return esc(text).split('\n').map(function(line){
    if (/^✔/.test(line)) return '<span class="s">' + line + '</span>';
    if (/^✘|FAILED|Traceback/.test(line)) return '<span class="f">' + line + '</span>';
    if (/^↻|PENDING|PARKED|WAITING/.test(line)) return '<span class="r">' + line + '</span>';
    if (/^▶|^\$ /.test(line)) return '<span class="b">' + line + '</span>';
    return line;
  }).join('\n');
}

function pollStatus(){
  fetch('/api/status').then(function(r){ return r.json(); }).then(function(d){
    renderHealth(d.ordak); renderJobs(d.jobs);
    if (!tailed && d.jobs && d.jobs.length) { /* leave the choice to the operator */ }
  }).catch(function(){});
}

function pollLog(){
  if (!tailed) return;
  fetch('/api/log/' + tailed + '?offset=' + tailOffset).then(function(r){ return r.json(); })
    .then(function(d){
      if (d.text) {
        var pre = document.getElementById('log');
        pre.innerHTML += colourise(d.text);
        if (follow) pre.scrollTop = pre.scrollHeight;
      }
      if (typeof d.offset === 'number') tailOffset = d.offset;
    }).catch(function(){});
}

document.addEventListener('DOMContentLoaded', function(){
  var pre = document.getElementById('log');
  pre.addEventListener('scroll', function(){
    follow = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
  });
  onProjectChange();
  pollStatus();
  setInterval(pollStatus, 5000);
  setInterval(pollLog, 2000);
});

function onProjectChange(){
  var sel = document.querySelector('select[name=content_project]');
  var qh = sel && sel.value === 'question_harvest';
  var box = document.getElementById('qh_advanced');
  if (box) box.style.display = qh ? '' : 'none';
  if (!qh) return;
  var min = document.querySelector('input[name=min_duration_seconds]');
  var max = document.querySelector('input[name=max_duration_seconds]');
  if (min && !min.dataset.touched) min.value = 40;
  if (max && !max.dataset.touched) max.value = 60;
}
"""


def launch_form(project_options: str, style_options: str) -> str:
    """The launch form. Locked choices render disabled so the UI cannot suggest a
    combination the pipeline would reject (§62-63)."""
    return f"""
<form method=post action=/launch>
 <fieldset><legend>Episode</legend>
  <label><span class="q">Content project</span>
   <select name=content_project onchange="onProjectChange()">{project_options}</select></label>
  <label><span class="q">Question / topic</span>
   <input name=topic required maxlength=220 placeholder="Why do leaves change color in autumn?"></label>
  <label>Working title <small>optional</small>
   <input name=working_title maxlength=220 placeholder="The strange reason years feel shorter"></label>
  <label>Audience <small>optional; overrides the project default</small>
   <input name=audience maxlength=500 placeholder="Curious adults who enjoy thoughtful explainers"></label>
  <label>Narrative angle <small>optional</small>
   <textarea name=narrative_angle maxlength=2000 placeholder="Start with a familiar moment, then explain the idea through a surprising metaphor."></textarea></label>
  <label>Must include <small>optional</small>
   <textarea name=must_include maxlength=2000 placeholder="Key examples, questions or points that must appear."></textarea></label>
  <label>Must avoid <small>optional</small>
   <textarea name=must_avoid maxlength=2000 placeholder="Claims, framing, spoilers or visual motifs to avoid."></textarea></label>
  <label>Source notes / verified facts <small>recommended for factual topics</small>
   <textarea name=source_notes maxlength=4000 placeholder="Paste only facts, links or quotations you have verified."></textarea></label>
 </fieldset>

 <fieldset><legend>Length &amp; format</legend>
  <div class="grid2">
   <label><span class="q">Minimum seconds</span>
    <input name=min_duration_seconds type=number min=15 max=300 value=40 required
     oninput="this.dataset.touched=1"></label>
   <label><span class="q">Maximum seconds</span>
    <input name=max_duration_seconds type=number min=15 max=300 value=60 required
     oninput="this.dataset.touched=1"></label>
  </div>
  <small>Binding: the script prompts are written for this length. 40–60s asks for ~92–150
   spoken words in 8–15 beats; 25–30s asks for ~57–75 in 5–8.</small>
  <label>Frame format <select name=aspect_ratio>
    <option value="9:16" selected>9:16 — Shorts / Reels vertical</option>
    <option value="16:9">16:9 — YouTube landscape</option></select></label>
  <label class="check"><input type=checkbox name=show_subtitles> Burn in subtitles
   <small>Question Harvest default: off (§71)</small></label>
  <label class="check"><input type=checkbox name=commit_artifacts> Commit &amp; push artifacts after QC
   <small>needs a remote with write access</small></label>
 </fieldset>

 <fieldset id="qh_advanced"><legend>Question Harvest</legend>
  <label>Hero presence <select name=hero_presence_mode>
    <option value=auto selected>auto — decide from the topic (§44)</option>
    <option value=opener_only>opener_only</option>
    <option value=limited_in_world>limited_in_world</option>
    <option value=in_world>in_world</option></select></label>
  <label><span class="q">World style</span><select name=world_style_id>{style_options}</select>
   <small>Pick a catalogued style to reuse it. A style created during a run is added here for
    the next episode.</small></label>
  <label>Style policy <select name=world_style_policy>
    <option value=auto selected>auto — reuse or create, whichever fits</option>
    <option value=reuse>reuse an existing style</option>
    <option value=new>create a new style</option></select>
   <small>ignored when a style is picked above</small></label>
  <label>Style hint <small>free text; steers a new style</small>
   <input name=world_style_hint maxlength=500 placeholder="e.g. charcoal, woodcut, ink wash …"></label>
  <label>Gemini image model <select name=gemini_image_model>
    <option value=nano_banana_2 selected>Nano Banana 2 — what Gemini offers today</option>
    <option value=nano_banana_pro>Nano Banana Pro — fails until Gemini exposes it</option></select></label>
  <div class="grid2">
   <label>Flow video model <select name=flow_video_model>
     <option value=gemini_omni_1_1_flash selected>Gemini Omni 1.1 Flash</option>
     <option value=veo_3_1_quality>Veo 3.1 Quality</option>
     <option value=veo_3_1_fast>Veo 3.1 Fast</option>
     <option value=veo_3_1_lite>Veo 3.1 Lite</option></select></label>
   <label>Flow resolution <select name=flow_resolution>
     <option value="720p" selected>720p</option>
     <option value="360p">360p draft</option></select></label>
  </div>
  <div class="grid2">
   <label>Clip A source <small>trimmed to the measured spark</small>
    <select name=opening_a_seconds><option value=4>4s</option><option value=5>5s</option>
     <option value=6 selected>6s</option><option value=8>8s</option></select></label>
   <label>Clip B source <small>trimmed to the measured hinge</small>
    <select name=opening_b_seconds><option value=3>3s</option><option value=4 selected>4s</option>
     <option value=6>6s</option><option value=8>8s</option></select></label>
  </div>
  <small>Each Flow generation costs 7 credits.</small>
 </fieldset>

 <fieldset><legend>Voice &amp; music</legend>
  <label><span class="q">Voice</span>
   <input name=voice value="George" required></label>
  <label>ElevenLabs model <select name=model>
    <option>Eleven Multilingual v2</option><option>Eleven v3</option></select></label>
  <div class="grid2">
   <label>Speed <input name=speed type=number min=.7 max=1.2 step=.01 value=.9 required></label>
   <label>Stability <input name=stability type=number min=0 max=1 step=.01 value=.45 required></label>
   <label>Similarity <input name=similarity type=number min=0 max=1 step=.01 value=.75 required></label>
   <label>Style <input name=style type=number min=0 max=1 step=.01 value=.10 required></label>
  </div>
  <label>Music provider <select name=music_provider>
    <option value=mixkit selected>Mixkit</option><option value=pixabay>Pixabay</option></select></label>
 </fieldset>

 <fieldset><legend>Locked by project design</legend>
  <label>Text <input value="ChatGPT · via Ordak" disabled></label>
  <label>Image <input value="Gemini · via Ordak" disabled></label>
  <label>Video <input value="Google Flow · via Ordak" disabled></label>
  <label>Flow references <input value="character_sheet (A) · first_frame + last_frame (B)" disabled></label>
  <label>Flow style sheet <input value="never uploaded — forbidden by §12-16, §61" disabled></label>
 </fieldset>

 <button class="primary" type=submit>Launch full pipeline</button>
</form>
"""


def render(*, message: str, project_options: str, style_options: str, address: str) -> str:
    """The whole page. Job rows and provider badges arrive from /api/status, so the served
    HTML is the same for every request and the live parts update in place."""
    import html as _html

    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Video Studio — Question Harvest</title>
<style>{CSS}</style></head>
<body><div class=wrap>

<header class=top>
  <h1>Video Studio</h1>
  <span class=sub>Question Harvest · ChatGPT → Gemini → Flow → ElevenLabs → render</span>
  <span class=spacer></span>
  <span class=addr>{_html.escape(address)}</span>
</header>

<div id=health><span class="pill idle">checking providers…</span></div>
<p class=msg>{_html.escape(message)}</p>

<div class=cols>
  <section>
    <div class=card>
      <h2>New episode</h2>
      <div class=body>{launch_form(project_options, style_options)}</div>
    </div>
  </section>

  <section>
    <div class=card>
      <h2>Runs</h2>
      <div class=body>
        <p class="notice wait">A Flow outage does not fail an episode. The run finishes
          narration, timing and music, parks as <b>waiting for Flow</b>, and a watcher job
          re-probes on a schedule and continues the render when Flow answers again.</p>
        <table id=runs><thead><tr>
          <th>Episode</th><th>Status</th><th>Progress</th><th>Started</th><th></th>
        </tr></thead><tbody>
          <tr><td colspan=5 class=empty>loading…</td></tr>
        </tbody></table>
      </div>
    </div>

    <div class=card id=logwrap>
      <h2>Live log</h2>
      <div class=logbar>
        <span>tailing <code id=logfor>—</code></span>
        <span class=spacer></span>
        <span>follows the tail unless you scroll up</span>
      </div>
      <pre id=log>Pick <b>Log</b> on a run to follow it.</pre>
    </div>
  </section>
</div>

<script>{SCRIPT}</script>
</div></body></html>
"""
