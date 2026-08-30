# Pixabay browser music

`scripts/run_pixabay_music.py` uses the Ordak-managed logged-in Chrome UI to
ask the configured ChatGPT project for one Pixabay Music URL, opens that exact
URL, clicks its visible **Free download** action, waits for Chrome's downloaded
audio, and stores it as `assets/music/background.<ext>`. It records the prompt,
source URL, license notice, timing, and artifact metadata in
`music/PIXABAY_SELECTION.json`; the metadata is intended for Git, generated
media is not.

```bash
python scripts/run_pixabay_music.py --video-id 002
# After a detected Cloudflare verification was completed in VNC:
python scripts/run_pixabay_music.py --video-id 002 --pixabay-url 'https://pixabay.com/music/.../'
```

The runner does not bypass sign-in, Cloudflare, CAPTCHA, or a content-license
gate. It stops with an explicit resumable state only when the visible website
requires that unavoidable human verification.
