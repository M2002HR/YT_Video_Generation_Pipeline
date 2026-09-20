# Shorts V2.2 deployment, smoke, and rollback runbook

This runbook deploys the code-ready Shorts V2 path without changing existing episodes. A run with no explicit engine marker remains `legacy`. Do not switch the new-run default until the real P14 smoke matrix passes.

## Preconditions

- Main checkout is on `dev`; `main` is untouched.
- `services/ordak` is at the pinned reachable commit recorded in the master ledger.
- The Studio is behind its existing authenticated reverse proxy.
- Chrome/Ordak is idle and the ElevenLabs account is already authorized.
- `ffmpeg`, `ffprobe`, Python 3.12 virtualenv, and Node 22 are available.
- Back up the service unit/environment and the current `control_panel/dist` directory using the host's normal snapshot mechanism. Never copy `.env`, browser profiles, cookies, or sessions into Git.

## Provider-free deployment gate

From the repository root:

```bash
.venv/bin/python -m compileall -q scripts
.venv/bin/python -m pytest -q -rs tests
npm --prefix control_panel/ui test
npm --prefix control_panel/ui run build
git diff --check
```

Expected result: Python and UI tests pass, Vite builds `control_panel/dist`, and diff check is clean. A provider-free pass is not a production smoke pass.

## Safe activation

1. Deploy the tested `dev` commit using the existing service deployment mechanism; do not modify the Ordak submodule or production browser profile.
2. Restart only the Studio service during an idle window. Do not restart a pipeline, render, Release, or provider job that is live.
3. Verify `/api/launch-schema` exposes `editing_engine` and still defaults to `legacy` before P14 acceptance.
4. Create a dedicated non-public smoke episode with `editing_engine=shorts_v2`, visual content review off, geometry observation once, and delivery/Git disabled.
5. Run the P14 matrix below. Preserve receipts, screenshots with account details redacted, output SHA-256 values, and exact commands in the master ledger.
6. Only after every required smoke passes may the launch-schema default be changed to `shorts_v2` in a separate reviewed commit. Existing runs remain frozen.

## P14 real smoke matrix

Run one paid, bound generation for each voice model through the new adapter:

- Eleven v3: model and exact voice readback, contenteditable input, categorical Stability, fresh result identity, attempt-owned download, `ffprobe`, receipt hash.
- Eleven Multilingual v2: model and exact voice readback, textarea input, v2 controls, no v3 tags, fresh result identity, attempt-owned download, `ffprobe`, receipt hash.

Then cover all four character/gateway profiles across smoke episodes or authorized fixtures. For each, verify real audio alignment, opening source/trim, at least one multi-shot narration unit, QC-off semantics, an audible preview, final render, pause/resume, and no legacy Motion Director import in the V2 process.

Exercise these revisions from Studio against an accepted version: caption-only, narration gain-only, one asset, voice/model, and one deliberately failed revision. Confirm the preview categories and provider-call estimate, two-tab stale apply returns HTTP 409, unaffected hashes remain equal, and the accepted pointer survives failure. Create a Release with Telegram disabled and confirm `SOURCE_SNAPSHOT.json` contains the exact accepted revision, pointer hash, and master hash.

## Rollback

Application rollback is a normal deploy of the preceding reachable commit; do not reset the working tree or rewrite Git history. Restore the previous service unit/environment snapshot if those files changed, rebuild that commit's UI, and restart only the Studio service.

Data rollback is pointer-based:

- For a V2 media revision, use Studio Versions → Rollback. This moves `shorts_v2/ACCEPTED_VERSION.json` to a previously accepted immutable snapshot and does not resend delivery.
- For a bad new-run default, restore `editing_engine=legacy` in the shared schema. Do not edit existing run requests.
- Do not delete failed/staging versions during incident response. They are audit evidence and cannot replace the last healthy accepted output.
- Do not resume an old Release after its accepted source binding changes; create a new Release. A mismatched revision/hash/pointer is a hard failure.

After rollback, rerun the provider-free gate and one legacy read-only Studio check. Record the deployed commit, prior commit, service restart time, affected episode IDs, and whether any external delivery occurred.

## Security and retention checks

- Typed artifact routes accept logical names only and reject traversal/symlinks.
- Revision bodies are size-limited and schema-validated; apply is bound to the preview hash and accepted-pointer hash.
- Release consumes only an immutable accepted path below the selected revision and verifies its bytes.
- Git publication must use the existing artifact allowlist. Never include `.env`, cookies, browser state, downloads, render cache, or credentials.
- Screenshots and logs used for P14 evidence must redact account email, balance, recipient IDs, tokens, and local session paths.
