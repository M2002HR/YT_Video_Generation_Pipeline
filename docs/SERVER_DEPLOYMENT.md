# Server deployment

One Ubuntu 24.04 host runs everything: a virtual X display, a persistent authenticated
Chrome, the Ordak API, the control panel, and nginx in front of the two things a human
touches. There is no container, no proxy, and no second machine.

## Layout

Working tree and every systemd unit point at **`/opt/YT_Video_Generation_Pipeline`**.
Two virtualenvs, deliberately separate:

| venv | Used by |
|---|---|
| `/opt/YT_Video_Generation_Pipeline/.venv` | pipeline scripts, control panel |
| `/opt/YT_Video_Generation_Pipeline/services/ordak/.venv` | the Ordak API and its tests |

Chrome's profile lives at `/root/.config/google-chrome-ordak` and holds the provider logins.
**It is the only place those sessions exist** — treat it as state, not cache.

## Units

| Unit | What it is | Listens |
|---|---|---|
| `ordak-xvfb` | `Xvfb :1 -screen 0 1920x1080x24 -nolisten tcp` | — |
| `ordak-fluxbox` | window manager on `:1` | — |
| `ordak-chrome` | Chrome with `--remote-debugging-port=9222`, profile `google-chrome-ordak` | 127.0.0.1:9222 |
| `ordak-x11vnc` | `x11vnc -display :1 -localhost -rfbauth /etc/ordak-vnc.pass` | 127.0.0.1:5901 |
| `ordak-novnc` | `websockify --web /usr/share/novnc 127.0.0.1:6080 → 5901` | 127.0.0.1:6080 |
| `ordak-api` | `.venv/bin/python scripts/run_ordak.py` | 127.0.0.1:8000 |
| `video-control-panel` | `.venv/bin/python scripts/video_control_panel.py --host 127.0.0.1 --port 4142` | 127.0.0.1:4142 |
| `nginx` | basic auth in front of the panel and noVNC | 0.0.0.0:4141, 4143, 4144 |

All of them are `enabled` with `Restart=always`, so the stack comes back after a reboot.
Everything except nginx binds to loopback only.

## Public surface

| Port | Serves | Auth file |
|---|---|---|
| **4141** | control panel (the official address) | `/etc/nginx/.htpasswd-video-panel` |
| 4144 | the same panel, legacy alias | same |
| **4143** | noVNC — watch Ordak drive the browser | `/etc/nginx/.htpasswd-ordak-vnc` |

Config: `/etc/nginx/sites-available/yt-vnc-panel`. `/nginx-health` is open on both ports for
liveness; everything else needs basic auth. Credentials live in
`/root/.config/yt-video-pipeline/access-credentials.txt` (mode `600`).

### The htpasswd trap

nginx workers run as **`www-data`**. An htpasswd file at mode `600` owned by `root` is
unreadable by them, and the failure is confusing: a request with **no** credentials still
returns `401` (nginx never opens the file), while a request with **correct** credentials
returns **`500`**, with this in the error log:

```
[crit] open() "/etc/nginx/.htpasswd-ordak-vnc" failed (13: Permission denied)
```

So a "401 without auth" smoke test passes while nobody can actually log in. The correct
permissions keep the file unreadable to others *and* readable by nginx:

```bash
chown root:www-data /etc/nginx/.htpasswd-ordak-vnc /etc/nginx/.htpasswd-video-panel
chmod 640          /etc/nginx/.htpasswd-ordak-vnc /etc/nginx/.htpasswd-video-panel
```

Always verify with a **valid** password, not just a missing one:

```bash
U=$(sed -n 's/^user:[[:space:]]*//p' /root/.config/yt-video-pipeline/access-credentials.txt)
PW=$(sed -n 's/^pass:[[:space:]]*//p' /root/.config/yt-video-pipeline/access-credentials.txt)
curl -so /dev/null -w '%{http_code}\n' http://127.0.0.1:4141/            # 401
curl -so /dev/null -w '%{http_code}\n' -u "$U:$PW" http://127.0.0.1:4141/ # 200
curl -so /dev/null -w '%{http_code}\n' -u "$U:wrong" http://127.0.0.1:4143/ # 401
```

## Browser session model

**One tab at a time.** Opening a provider tab closes every other tab
(`_linux_close_other_tabs`): work is serialised, so a stale tab only wastes RAM and risks the
next job binding to the wrong page. Two consequences to expect:

* `/api/diagnostics` can only confirm the login of a provider that currently has a tab. The
  other two report `logged_in: false` with `login_state: ready` — that is **idle, not signed
  out**. The panel shows them as `idle (no tab)`, and `check_full_stack.py` treats a missing
  tab as advisory while still failing on `login_required`.
* If you want parallel provider work later, this is the single function to change.

## Verifying the whole stack

```bash
cd /opt/YT_Video_Generation_Pipeline
.venv/bin/python scripts/check_full_stack.py     # exit 0; advisories print with ⚠
PYTHONPATH=.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -q
cd services/ordak && .venv/bin/python -m pytest tests/ -q
```

## After changing Ordak code

```bash
systemctl restart ordak-api
```

Not optional. A job launched against a stale worker once burned 7 Flow credits proving it.

## Configuration

`.env` at the repo root, `.env.example` documents every key. The ones that change behaviour
most: `YT_ORDAK_FLOW_URL` (pin to a project URL),
`YT_QUESTION_HARVEST_DEFAULT_GEMINI_MODEL`, `YT_RENDER_RESOURCE_BUDGET`,
`YT_PIPELINE_TELEGRAM_*`, `YT_GIT_PUSH_ENABLED`.
