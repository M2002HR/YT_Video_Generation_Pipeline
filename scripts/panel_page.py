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
.feature-off{opacity:.52}
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
@media (prefers-color-scheme:light){:root{color-scheme:light;
  --bg:#edf1f7; --panel:#ffffff; --panel-2:#f0f3f9; --line:#cbd5e2; --line-2:#b9c6d9;
  --ink:#17222f; --ink-dim:#5b6d83; --ink-faint:#8a97a8;
  --accent:#2b5fc7; --accent-ink:#ffffff;
  --ok:#0c7a55; --ok-bg:#e2f4ea; --ok-line:#a4d9c0;
  --warn:#8a5f05; --warn-bg:#faf0d7; --warn-line:#e6cf96;
  --bad:#bf3040; --bad-bg:#fdecef; --bad-line:#efb3bb}
  input:disabled{color:var(--ink-dim);background:#e8edf4}
  .pill.idle{background:#e8edf4}
  tr.sel td{background:#e9f0fc}
  .bar{background:#dbe2ec}
  .notice{background:#e9f0fc}}
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
        (p.running ? ' · ' + esc(p.running) : '') + '</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div>'
      : '<span class="stage">—</span>';
    var what = job.kind === 'flow_watcher'
      ? '<b>Flow watcher</b><div class="stage">every ' +
        Math.round((job.interval_seconds || 1200) / 60) + ' min · video ' + esc(job.video_id) + '</div>'
      : '<b>' + esc(job.video_id || '—') + '</b><div class="stage">' + esc(job.topic || '') + '</div>';
    if (job.kind !== 'flow_watcher' && job.motion) {
      var m = job.motion;
      what += '<div class="stage">Motion: ' + (m.enabled ? esc(m.style) + ' / ' + esc(m.pace) : 'disabled') +
        (m.micro_shots != null ? ' · ' + esc(m.micro_shots) + ' micro-shots' : '') +
        (m.qc ? ' · QC ' + esc(m.qc) : '') + '</div>';
    }
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
  syncMotionControls();
  syncSubtitleOffset();
  syncBeatImageQcControls();
  pollStatus();
  setInterval(pollStatus, 5000);
  setInterval(pollLog, 2000);
});

function syncMotionControls(){
  var master = document.getElementById('motion_enabled');
  var controls = document.getElementById('motion_controls');
  if (!master || !controls) return;
  var active = master.checked;
  controls.classList.toggle('feature-off', !active);
  controls.querySelectorAll('input,select,textarea,button').forEach(function(control){ control.disabled = !active; });
}

function syncSubtitleOffset(){
  var pos = document.querySelector('select[name=subtitle_position]');
  var custom = pos && pos.value === 'custom';
  ['subtitle_offset_value', 'subtitle_offset_unit'].forEach(function(name){
    var el = document.querySelector('[name=' + name + ']');
    if (el) el.disabled = !custom;
  });
}

function syncBeatImageQcControls(){
  var disabled = document.querySelector('input[name=beat_image_qc_disabled]');
  var policy = document.getElementById('beat_image_qc_policy');
  if (!disabled || !policy) return;
  policy.style.display = disabled.checked ? 'none' : '';
  policy.querySelectorAll('select,input').forEach(function(control){ control.disabled = disabled.checked; });
}

function onProjectChange(){
  var sel = document.querySelector('select[name=content_project]');
  var qh = sel && sel.value === 'q_station';
  var box = document.getElementById('qh_advanced');
  if (box) box.style.display = qh ? '' : 'none';
  if (!qh) return;
  var min = document.querySelector('input[name=min_duration_seconds]');
  var max = document.querySelector('input[name=max_duration_seconds]');
  if (min && !min.dataset.touched) min.value = 40;
  if (max && !max.dataset.touched) max.value = 60;
}
"""


def launch_form(project_options: str, style_options: str, character_options: str = "") -> str:
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
   <small>Q Station default: off (§71)</small></label>
  <label class="check"><input type=checkbox name=word_highlight checked> Highlight the spoken word
   <small>Warm-gold sweep follows each measured word; requires burned subtitles and real word timing.</small></label>
  <label>Subtitle font <select name=subtitle_font>
    <option selected>Roboto</option><option>Open Sans</option>
    <option>Lato</option><option>Montserrat</option>
    <option>Poppins</option><option>Noto Sans</option>
    <option>Source Sans 3</option><option>Rubik</option>
    <option>Atkinson Hyperlegible</option><option>Bebas Neue</option>
    <option>Oswald</option><option>DejaVu Sans</option><option>DejaVu Serif</option>
    <option>Liberation Sans</option><option>Liberation Serif</option>
    <option>Liberation Sans Narrow</option><option>Nimbus Sans</option>
    <option>Noto Sans Mono</option></select>
   <small>Starred picks and search are in Studio; the burn-in face is identical.</small></label>
  <div class="grid2">
   <label>Subtitle font size <input name=subtitle_font_size type=number min=24 max=300 step=1 value=56></label>
   <label>Max words per caption <input name=subtitle_max_words type=number min=1 max=12 step=1 value=6></label>
  </div>
  <div class="grid2">
   <label>Subtitle position <select name=subtitle_position onchange="syncSubtitleOffset()">
     <option value=low>Low — near the bottom edge</option>
     <option value=standard selected>Standard — clears the app UI</option>
     <option value=high>High — raised lower-third</option>
     <option value=custom>Custom — offset from the bottom</option></select></label>
   <label class="check"><input type=checkbox name=subtitle_bold checked> Subtitle bold</label>
  </div>
  <div class="grid2">
   <label>Custom offset <input name=subtitle_offset_value type=number min=0 max=800 step=0.5 value=10>
    <small>Used only with Custom position.</small></label>
   <label>Offset unit <select name=subtitle_offset_unit>
     <option value=percent selected>Percent of height (0–40)</option>
     <option value=px>Pixels (0–800)</option></select></label>
  </div>
  <div class="grid2">
   <label>Text colour <input name=subtitle_font_colour type=color value=#FFFFFF></label>
   <label>Outline colour <input name=subtitle_outline_colour type=color value=#000000></label>
  </div>
  <div class="grid2">
   <label>Outline width <input name=subtitle_outline type=number min=0 max=8 step=0.5 value=3>
    <small>0 switches the outline off.</small></label>
   <label class="check"><input type=checkbox name=subtitle_italic> Subtitle italic</label>
  </div>
  <h3>Logo &amp; video title</h3>
  <label class=check><input type=checkbox name=show_logo> Show logo</label>
  <input type=hidden name=logo_upload_id value="">
  <div class=grid2>
   <label>Logo position <select name=logo_position><option value=top_right selected>Top right</option><option value=top_left>Top left</option><option value=bottom_right>Bottom right</option><option value=bottom_left>Bottom left</option><option value=custom>Custom</option></select></label>
   <label>Logo width % <input name=logo_width_percent type=number min=4 max=40 step=.5 value=14></label>
   <label>Logo opacity <input name=logo_opacity type=number min=.1 max=1 step=.05 value=1></label>
   <label>Logo horizontal margin % <input name=logo_margin_x_percent type=number min=0 max=25 step=.5 value=3></label>
   <label>Logo vertical margin % <input name=logo_margin_y_percent type=number min=0 max=25 step=.5 value=2.5></label>
   <label>Logo custom centre X % <input name=logo_custom_x_percent type=number min=0 max=100 step=.5 value=85></label>
   <label>Logo custom centre Y % <input name=logo_custom_y_percent type=number min=0 max=100 step=.5 value=10></label>
  </div>
  <label class=check><input type=checkbox name=show_title checked> Show question as title</label>
  <div class=grid2>
   <label>Title position <select name=title_position><option value=below_logo selected>Below logo</option><option value=top_left>Top left</option><option value=top_center>Top centre</option><option value=top_right>Top right</option><option value=center>Centre</option><option value=bottom_left>Bottom left</option><option value=bottom_center>Bottom centre</option><option value=bottom_right>Bottom right</option><option value=custom>Custom</option></select></label>
   <label>Title font <select name=title_font><option selected>Roboto</option><option>Open Sans</option><option>Rubik</option><option>DejaVu Sans</option></select></label>
   <label>Title font size <input name=title_font_size type=number min=16 max=200 value=38></label>
   <label>Maximum words per line <input name=title_max_words_per_line type=number min=1 max=100 value=7></label>
   <label>Line spacing (px) <input name=title_line_spacing type=number min=-10 max=100 value=6></label>
   <label>Title box width % <input name=title_max_width_percent type=number min=12 max=90 value=34></label>
   <label>Text alignment <select name=title_text_align><option value=right selected>Right</option><option value=center>Centre</option><option value=left>Left</option></select></label>
   <label>Title horizontal margin % <input name=title_margin_x_percent type=number min=0 max=25 step=.5 value=3></label>
   <label>Title vertical margin % <input name=title_margin_y_percent type=number min=0 max=25 step=.5 value=2.5></label>
   <label>Gap below logo % <input name=title_logo_gap_percent type=number min=0 max=15 step=.5 value=1></label>
   <label>Title custom centre X % <input name=title_custom_x_percent type=number min=0 max=100 step=.5 value=80></label>
   <label>Title custom top Y % <input name=title_custom_y_percent type=number min=0 max=100 step=.5 value=18></label>
   <label>Title colour <input name=title_font_colour type=color value=#FFFFFF></label>
   <label>Title outline colour <input name=title_outline_colour type=color value=#000000></label>
   <label>Title outline width <input name=title_outline type=number min=0 max=8 step=.5 value=2></label>
   <label class=check><input type=checkbox name=title_bold checked> Title bold</label>
   <label class=check><input type=checkbox name=title_italic> Title italic</label>
  </div>
  <label class="check"><input type=checkbox name=commit_artifacts> Commit &amp; push artifacts after QC
   <small>needs a remote with write access</small></label>
  <label class="check"><input type=checkbox name=telegram_low_size checked> Send low-size copy to Telegram
   <small>Default: compressed 480px delivery copy; the full-quality master remains unchanged.</small></label>
  <label class="check"><input type=checkbox name=telegram_original> Send original file to Telegram too
   <small>Optional: sends the full-quality polished file in addition to the compact copy.</small></label>
 </fieldset>

 <fieldset id="qh_advanced"><legend>Q Station</legend>
  <label>Character <select name=character_mode onchange="document.getElementById('manual_character').disabled=this.value!=='manual'">
    <option value=auto selected>Auto — choose after the final script</option>
    <option value=manual>Manual character</option></select></label>
  <label>Manual character <select id=manual_character name=character_id disabled>{character_options}</select></label>
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
  <input type=hidden name=world_style_reference_id value="">
  <label><input type=checkbox name=reserve_subtitle_space checked> Reserve lower space inside images for subtitles</label>
  <label><input type=checkbox name=chatgpt_fallback_auto> Automatically fall back to Gemini if ChatGPT fails</label>
  <label>Gemini image model <select name=gemini_image_model>
    <option value=nano_banana_2 selected>Nano Banana 2 — what Gemini offers today</option>
    <option value=nano_banana_pro>Nano Banana Pro — fails until Gemini exposes it</option></select></label>
  <label class=check><input type=checkbox name=beat_image_qc_disabled onchange="syncBeatImageQcControls()">
   Disable ChatGPT QC for beat images
   <small>Generated body-beat images will never be uploaded to ChatGPT for review.</small></label>
  <label id=beat_image_qc_policy>Non-critical image QC corrections <select name=image_qc_correction_policy>
    <option value=0 selected>0 — report only (current behaviour)</option>
    <option value=1>1 corrective regeneration</option>
    <option value=2>2 corrective regenerations, then use best</option>
    <option value=strict>Strict — 3 attempts, then fail if not clean</option></select>
   <small>Blocking identity, style-continuity and wrong-output failures are never accepted.</small></label>
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
   <label>Opening sync tolerance <small>silent clip may slow up to this to meet narration</small>
    <input name=opening_speed_tolerance type=number min=0 max=0.5 step=0.01 value=0.1></label>
  <small>Each Flow generation costs 7 credits.</small>
 </fieldset>

 <fieldset><legend>Voice &amp; music</legend>
  <label><span class="q">Voice</span>
   <input name=voice value="Mark - Natural Conversations" required></label>
  <label>ElevenLabs model <select name=model>
    <option selected>Eleven Multilingual v2</option><option>Eleven v3</option></select></label>
  <div class="grid2">
   <label>Speed <input name=speed type=number min=.7 max=1.2 step=.01 value=.9 required></label>
   <label>Stability <input name=stability type=number min=0 max=1 step=.01 value=.30 required></label>
   <label>Similarity <input name=similarity type=number min=0 max=1 step=.01 value=.50 required></label>
   <label>Style <input name=style type=number min=0 max=1 step=.01 value=.15 required></label>
  </div>
  <label>Music provider priority
   <input name=music_providers value="freesound,mixkit,pixabay" pattern="(freesound|mixkit|pixabay)(,(freesound|mixkit|pixabay))*" required>
   <small>Comma-separated order. The pipeline tries each provider in order, then uses only a verified cached track if all fail.</small>
  </label>
 </fieldset>

 <fieldset><legend>Sound effects</legend>
  <label class=check><input name=sfx_enabled type=checkbox> Enable restrained SFX</label>
  <div class=grid2>
   <label>Planner style <select name=sfx_planner_style><option value=restrained selected>Restrained</option><option value=balanced>Balanced</option><option value=expressive>Expressive</option></select></label>
   <label>Max events/min <input name=sfx_max_events_per_minute type=number min=0 max=20 step=.5 value=4></label>
   <label>Minimum gap (sec) <input name=sfx_minimum_gap_seconds type=number min=0 max=30 step=.1 value=2></label>
   <label>Local-match threshold <input name=sfx_local_match_threshold type=number min=0 max=1 step=.05 value=.35></label>
   <label>License policy <select name=sfx_license_policy><option value=cc0 selected>CC0 only</option><option value=cc0_by>CC0 + CC BY</option></select></label>
   <label>Candidate count <input name=sfx_candidate_count type=number min=1 max=50 value=12></label>
   <label>Max queries/event <input name=sfx_max_queries_per_event type=number min=1 max=5 value=2></label>
   <label>Default gain dB <input name=sfx_default_gain_db type=number min=-20 max=-3 step=1 value=-9></label>
  </div>
  <label class=check><input name=sfx_freesound_enabled type=checkbox checked> Use Freesound only after a local-library miss</label>
  <small>Freesound credentials remain server-side. CC0 is the production default; API use must comply with Freesound terms.</small>
 </fieldset>

 <fieldset><legend>Motion / Editing</legend>
 <label class=check><input id=motion_enabled name=motion_enabled type=checkbox checked onchange="syncMotionControls()"> Enable Dynamic Motion Director</label>
 <small>Off: skips the Motion Director/Ordak stage and renders with the existing legacy timeline behavior. Existing Motion Plan artifacts are ignored, never deleted.</small>
 <div class=grid2>
  <label>Image zoom strength <input name=motion_image_zoom_strength type=number min=.04 max=.24 step=.01 value=.14></label>
  <label>Default transition <select name=motion_transition_default_type><option value=fade selected>Fade</option><option value=dissolve>Dissolve</option><option value=fadeblack>Fade to black</option><option value=fadewhite>Fade to white</option><option value=smoothleft>Smooth left</option><option value=smoothright>Smooth right</option><option value=wipeleft>Wipe left</option><option value=wiperight>Wipe right</option><option value=slideleft>Slide left</option><option value=slideright>Slide right</option><option value=cut>Cut</option></select></label>
  <label>Transition intensity / seconds <input name=motion_transition_seconds type=number min=.08 max=.45 step=.01 value=.28></label>
  <label class=check><input name=motion_transition_ai_enabled type=checkbox> Let ChatGPT choose image-pair transitions</label>
  <input name=motion_image_transition_style type=hidden value=cut_fade_dissolve><input name=motion_image_transition_seconds type=hidden value=.28><input name=motion_opening_to_image_seconds type=hidden value=.28>
 </div>
 <small>Fade at 0.28 seconds is the default for every media boundary. Per-boundary overrides are available in the React Studio Revise view.</small>
 <div id=motion_controls>
  <div class=grid2>
   <label>Editing pace <select name=motion_pace><option value=calm>Calm</option><option value=balanced>Balanced</option><option value=fast selected>Fast</option><option value=very_fast>Very Fast</option></select></label>
   <label>Motion intensity <select name=motion_intensity><option value=subtle>Subtle</option><option value=normal selected>Normal</option><option value=strong>Strong</option></select></label>
   <label>Editing style <select name=motion_style><option value=clean>Clean</option><option value=dynamic selected>Dynamic</option><option value=cinematic>Cinematic</option></select></label>
   <label>Transition preference <select name=motion_transition_preference><option value=minimal selected>Minimal</option><option value=balanced>Balanced</option><option value=expressive>Expressive</option></select></label>
   <label>Maximum micro-shots/image <input name=motion_max_micro_shots type=number min=1 max=4 value=3></label>
  </div>
  <label class=check><input name=motion_allow_punch_ins type=checkbox checked> Allow punch-ins</label>
  <label class=check><input name=motion_allow_directional_pans type=checkbox checked> Allow directional pans</label>
  <label class=check><input name=motion_allow_hard_reframe_cuts type=checkbox checked> Allow hard reframe cuts</label>
  <label class=check><input name=motion_face_protection type=checkbox checked> Face protection</label>
  <details><summary>Advanced motion safety and planning</summary>
   <div class=grid2>
    <label>Planning quality <select name=motion_planning_quality><option value=draft>Draft</option><option value=standard>Standard</option><option value=professional selected>Professional</option></select></label>
    <label>Min micro-shot (sec) <input name=motion_min_shot_duration type=number min=.35 max=3 step=.05 value=.55></label>
    <label>Max micro-shot (sec) <input name=motion_max_shot_duration type=number min=.6 max=8 step=.1 value=3.2></label>
    <label>Target interval min (sec) <input name=motion_interval_min type=number min=.4 max=5 step=.1 value=.8></label>
    <label>Target interval max (sec) <input name=motion_interval_max type=number min=.6 max=8 step=.1 value=1.8></label>
    <label>Normal max zoom <input name=motion_normal_max_zoom type=number min=1 max=1.6 step=.01 value=1.32></label>
    <label>Punch max zoom <input name=motion_punch_max_zoom type=number min=1 max=1.8 step=.01 value=1.48></label>
    <label>Max pan distance <input name=motion_max_pan_distance type=number min=.02 max=.7 step=.01 value=.32></label>
    <label>Max pan/sec <input name=motion_max_pan_velocity type=number min=.02 max=1 step=.01 value=.42></label>
    <label>Max zoom/sec <input name=motion_max_zoom_velocity type=number min=.02 max=1 step=.01 value=.34></label>
    <label>Transition min (sec) <input name=motion_transition_min type=number min=.08 max=.6 step=.01 value=.10></label>
    <label>Transition max (sec) <input name=motion_transition_max type=number min=.08 max=.8 step=.01 value=.40></label>
    <label>Observation batch size <input name=motion_observation_batch type=number min=1 max=6 value=3></label>
    <label>Planning batch size <input name=motion_planning_batch type=number min=1 max=6 value=1></label>
    <label>Critic batch size <input name=motion_critic_batch type=number min=1 max=4 value=2></label>
    <label>JSON correction attempts <input name=motion_correction_attempts type=number min=0 max=4 value=4></label>
    <label>Neighbor beats/context <input name=motion_neighbor_context type=number min=1 max=3 value=1></label>
    <label>Word-sync tolerance (ms) <input name=motion_word_sync_tolerance type=number min=0 max=250 step=5 value=50></label>
    <label>Face safety padding <input name=motion_face_padding type=number min=0 max=.5 step=.01 value=.18></label>
   <label>Supersample <select name=motion_supersample><option value=1>1×</option><option value=2 selected>2×</option><option value=3>3×</option><option value=4>4×</option></select></label>
   </div>
   <label class=check><input name=motion_allow_hold type=checkbox checked> Allow intentional holds</label>
   <label class=check><input name=motion_allow_push type=checkbox checked> Allow pushes</label>
   <label class=check><input name=motion_allow_pull type=checkbox checked> Allow pull-outs</label>
   <label class=check><input name=motion_allow_tilt type=checkbox checked> Allow vertical tilts</label>
   <label class=check><input name=motion_allow_pan_push type=checkbox checked> Allow combined pan + push</label>
   <label class=check><input name=motion_allow_pan_pull type=checkbox checked> Allow combined pan + pull</label>
   <label class=check><input name=motion_allow_drift type=checkbox checked> Allow subtle drift</label>
   <label class=check><input name=motion_allow_settle type=checkbox checked> Allow settle moves</label>
   <label class=check><input name=motion_allow_reveal_move type=checkbox checked> Allow reveal moves</label>
   <label class=check><input name=motion_allow_match_position_cuts type=checkbox checked> Allow match-position cuts</label>
   <label class=check><input name=motion_allow_decorative_transitions type=checkbox checked> Allow non-cut transitions</label>
   <label class=check><input name=motion_allow_directional_transitions type=checkbox checked> Allow directional transitions</label>
   <label class=check><input name=motion_allow_reveal_transitions type=checkbox checked> Allow reveal transitions</label>
   <label class=check><input name=motion_subtitle_avoidance type=checkbox checked> Protect subtitle region</label>
   <label class=check><input name=motion_blank_avoidance type=checkbox checked> Avoid blank/low-detail regions</label>
   <label class=check><input name=motion_word_sync type=checkbox checked> Synchronize events to Ajil words</label>
   <label class=check><input name=motion_editorial_critic type=checkbox checked> Run senior editorial critic</label>
   <label class=check><input name=motion_debug_preview type=checkbox> Generate debug preview assets</label>
  </details>
  </div>
  <small>ChatGPT via Ordak sees the accepted beat images and produces an audited semantic plan; local FFmpeg compilation remains deterministic.</small>
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


def render(*, message: str, project_options: str, style_options: str, address: str, character_options: str = "") -> str:
    """The whole page. Job rows and provider badges arrive from /api/status, so the served
    HTML is the same for every request and the live parts update in place."""
    import html as _html

    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Video Studio — Q Station</title>
<style>{CSS}</style></head>
<body><div class=wrap>

<header class=top>
  <h1>Video Studio</h1>
  <span class=sub>Q Station · ChatGPT → Gemini → Flow → ElevenLabs → render</span>
  <span class=spacer></span>
  <span class=addr>{_html.escape(address)}</span>
</header>

<div id=health><span class="pill idle">checking providers…</span></div>
<p class=msg>{_html.escape(message)}</p>

<div class=cols>
  <section>
    <div class=card>
      <h2>New episode</h2>
      <div class=body>{launch_form(project_options, style_options, character_options)}</div>
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
