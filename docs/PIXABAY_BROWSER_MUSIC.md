# Browser background music

`scripts/run_pixabay_music.py` uses the Ordak-managed logged-in Chrome UI to
derive a compact brief from the current video's `BRIEF.md`, `SCRIPT_FINAL.md`,
and narration duration, then ask the configured ChatGPT project for exactly one
provider URL. It opens that exact URL, clicks its visible download action, waits
for Chrome's downloaded audio, and stores it as `assets/music/background.<ext>`.
It records the generated prompt, a context hash, source URL, license notice,
timing, and artifact metadata in `music/MUSIC_SELECTION.json`; the metadata is
intended for Git, generated media is not.

## Reliability behavior

The browser path remains the preferred path because it selects a track for the
current video's subject and pacing. It is bounded and resumable:

- a previously selected direct track URL is reused after an interrupted
  download instead of asking ChatGPT again;
- ChatGPT selection, provider readiness, the overall browser workflow, and the
  Chrome download each have hard time limits;
- DevTools reads and websocket receives are bounded/retried;
- every downloaded file is checked with `ffprobe` before installation;
- music already present in a resumed project is reused only if it is a valid,
  decodable audio file of meaningful duration.

If ChatGPT, Chrome, Mixkit/Pixabay, a CAPTCHA, or a download fails, the runner
copies a previously completed track from the same provider's local verified
cache. It records `selection_mode: CACHE_FALLBACK`, the original license/source
URL, checksum, duration, origin artifact, and primary failure reason. This
degrades only per-video music selection; it does not stop rendering, QC, or
publication. The next video still attempts a fresh browser selection first.

Default bounded timings can be overridden with:

```text
YT_MUSIC_SELECTION_TIMEOUT_SECONDS=75
YT_MUSIC_PROVIDER_READY_TIMEOUT_SECONDS=45
YT_MUSIC_DOWNLOAD_TIMEOUT_SECONDS=90
YT_MUSIC_PRIMARY_TIMEOUT_SECONDS=300
```

```bash
python scripts/run_pixabay_music.py --video-id 002
# Resume a known Mixkit selection without a second ChatGPT request:
python scripts/run_pixabay_music.py --video-id 002 --provider mixkit --track-url 'https://mixkit.co/free-stock-music/item/443/'
```

Supported providers are `mixkit` (default) and `pixabay`. The runner does not
bypass sign-in, Cloudflare, CAPTCHA, or a content-license gate. Human
verification causes the primary browser attempt to end and the verified local
fallback to be used; it is never bypassed automatically.
