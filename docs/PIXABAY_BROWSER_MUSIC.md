# Browser background music

`scripts/run_pixabay_music.py` uses the Ordak-managed logged-in Chrome UI to
derive a compact brief from the current video's `BRIEF.md`, `SCRIPT_FINAL.md`,
and narration duration, then ask the configured ChatGPT project for exactly one
provider URL. It opens that exact URL, clicks its visible download action, waits
for Chrome's downloaded audio, and stores it as `assets/music/background.<ext>`.
It records the generated prompt, a context hash, source URL, license notice,
timing, and artifact metadata in `music/MUSIC_SELECTION.json`; the metadata is
intended for Git, generated media is not.

```bash
python scripts/run_pixabay_music.py --video-id 002
# Resume a known Mixkit selection without a second ChatGPT request:
python scripts/run_pixabay_music.py --video-id 002 --provider mixkit --track-url 'https://mixkit.co/free-stock-music/item/443/'
```

Supported providers are `mixkit` (default) and `pixabay`. The runner does not
bypass sign-in, Cloudflare, CAPTCHA, or a content-license gate. It stops with an
explicit resumable state only when the visible website requires that unavoidable
human verification.
