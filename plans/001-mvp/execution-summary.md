# 001 — plugin-talk MVP — Execution Summary

**Version shipped:** plugin-talk 0.1.1 (0.1.0 + first-use fixes) · **Repo:** https://github.com/huemorgan/plugin-talk (tags `v0.1.0`, `v0.1.1`)

> **0.1.1 amendments (first real-browser use):** (1) Luna cookie auth is
> READ-ONLY — plugin iframes must send the shell's bearer token (`?token=` query
> or `luna-auth` postMessage; see plugin-render) for any POST; the settings page
> now does. (2) Sidebar *widget* iframes get NO token at all (plain `<iframe>` in
> Shell.tsx) — `/session` accepts GET so the widget can mint with cookie auth.
> (3) Agent ID field removed: `/connect` takes just the API key and
> auto-provisions the "Luna (plugin-talk)" agent via the ElevenLabs agents API
> (`POST /v1/convai/agents/create` with `prompt.llm="custom-llm"` +
> `custom_llm.url` ending at `/v1` — ElevenLabs appends `/chat/completions` —
> and `request_headers.Authorization`; schema verified live). Reconnect
> re-points the existing agent, so no manual dashboard step remains.
**Tests:** 33 unit/dojo passed + 1 live ElevenLabs smoke test passed · **Published:** seeded into `luna-marketplaces/marketplace-src/plugin_talk` (commit `129755b`), Render deploy triggered

## What was accomplished

- **Full plugin built** per PLAN.md, SDK-only (verified by test: no `import luna.*`):
  - `bridge.py` — pure-logic OpenAI-compatible SSE bridge: voice system prompt,
    history-window prompt folding, buffer-words first chunk (`"One moment... "`),
    sentence-sized streaming of `run_turn`'s finished reply, graceful spoken error
    on agent failure, non-stream JSON fallback.
  - Tool safety: voice turns get a computed allowlist — excludes `risk_level="high"`,
    `policy="prompt_always"` and `send_chat_message` (run_turn bypasses approval UX).
  - `routes.py` — bridge (bearer-secret gated, constant-time compare), `/connect`
    (validates key against ElevenLabs before storing), `/status`, `/voices` (proxied,
    key never reaches the browser), `/settings` (voice picker persistence), `/session`
    (conversation token mint, WebRTC first + signed-URL WebSocket fallback), static UI
    with path-traversal guard.
  - **All keys in the vault**: `plugin_talk.elevenlabs_api_key`, `.agent_id`,
    `.bridge_secret` (auto-generated `token_urlsafe(32)`), `.settings` (non-secret JSON).
  - **Sidebar widget** (`widgets=[{id: "talk", slot: "sidebar.bottom"}]`) — canvas
    dual-waveform: teal vibrates with the user's mic, violet with Luna's voice
    (SDK `getInputVolume`/`getOutputVolume`), calm violet pulse for "thinking" during
    slow tool calls. ElevenLabs browser SDK v1.14.0 vendored (`lib.iife.js`, 846 KB).
  - **Settings tab** — connect form, copy-paste Custom-LLM URL + Authorization header
    for the ElevenLabs console, voice picker with audio preview, save/clear.
- **Dojo tests answer the user's two questions through the real HTTP surface**:
  widget page served with viz canvas + talk button at the manifest-declared URL;
  connect→vault storage, voice round-trip through `/settings`, selected voice reaching
  the `/session` payload the widget consumes; bridge auth (503 unconfigured / 401 bad
  secret), SSE contract with buffer words, allowlist enforcement on the actual turn.
- **Live check with the owner's key (env only, never written to disk — verified by
  grep before commit): `list_voices` returned real voices.**

## What we discovered along the way

- `ctx.agent.run_turn` is **non-streaming** (returns the finished reply) — confirmed in
  `luna/luna/plugins/agent_facade.py`. First-audio latency = one full agent turn; the
  buffer-words chunk is what makes this acceptable. A streaming turn API in luna core
  is the single highest-value upgrade for this plugin.
- `run_turn` **bypasses tool approval policy** (documented in plugin-whatsapp) — the
  allowlist is a hard requirement, not a nicety.
- **SDK gap:** `PluginManifest.widgets` exists and the shell renders it
  (plugin-brain), but `WidgetSlot` is **not re-exported from `luna_sdk`** — worked
  around with a plain dict (pydantic validates it). Change request for luna: one-line
  re-export.
- No sanctioned non-secret KV store for plugins: `StorageProvider` is content-addressed
  (new ref per save), `scratch_dir` is ephemeral. Settled on a JSON blob in the vault
  (`kind="config"`) — works, slightly abusive. A `ctx.kv` / plugin-settings surface
  would be cleaner.
- ElevenLabs `@elevenlabs/client` ships an IIFE bundle (`dist/lib.iife.js`, exports
  global `ElevenLabsClient` with `Conversation.startSession`, `conversationToken` +
  `connectionType: "webrtc"|"websocket"`, volume getters) — vendoring it keeps the
  widget self-contained, no CDN at runtime.
- Publishing to `official` is **repo-seeded** (Path B in UPDATING-A-PLUGIN.md): copy
  the package into `luna-marketplaces/marketplace-src/`, push, deploy — the seeder
  upserts on boot. Render deploys can be triggered headlessly via the authenticated
  Render CLI credentials (`~/.render/cli.yaml`).
- Local dev: system python3 is 3.9; plugin venvs need `python3.12`
  (`~/.local/bin/python3.12`).
- **Submodule push trap:** the `luna-marketplaces` checkout is a submodule in
  detached HEAD. `git push <url> main:main` from there pushes the *stale local
  branch* — a silent no-op that exits 0 — so the seed commit never reached GitHub
  and the first deploy built the old tree. From a detached-HEAD submodule, always
  push `HEAD:main` (and verify with `git ls-remote` / `gh api .../commits/main`).
  Render (`luna-marketplaces` service, auto-deploy OFF) then needs a manual deploy;
  the authenticated CLI creds in `~/.render/cli.yaml` can trigger it headlessly.

## Things to consider in the future

- **Luna change requests:** (1) re-export `WidgetSlot` from `luna_sdk`; (2) a
  streaming variant of `run_turn` (or a token callback) → drop buffer-words latency;
  (3) a sanctioned plugin KV/settings store.
- **Transcript in chat** (plan acceptance criterion, consciously deferred): binding a
  voice session to a Luna conversation needs a conversation-create surface in the SDK;
  today the widget shows live state but turns aren't recorded in a chat thread.
- **Timeout behavior on 10–30 s tool calls** is still unverified against ElevenLabs'
  real custom-LLM timeout (research open question 4). If calls drop, send periodic
  buffer chunks or split the turn ("still working…").
- **Per-session voice override field** (`overrides.tts.voiceId`) should be verified in
  a real call; fallback is PATCHing the agent's default voice via REST.
- **E2E live walkthrough** (real browser, real agent) not yet run — needs an ElevenLabs
  *agent* created in the dashboard (the provided key alone isn't enough) and a running
  Luna. The dojo suite covers everything short of actual audio.
- Fleet provisioning (one EL agent per tenant) remains a luna-service concern.
- The vendored SDK bundle (846 KB) should be version-bumped deliberately; pin noted in
  the repo (v1.14.0).

## Files

**New repo `plugins/plugin-talk/`:** `plugin_talk/{__init__.py, luna-plugin.toml,
bridge.py, elevenlabs.py, routes.py, state.py, ui/widgets/talk/{index.html,
elevenlabs-client.js}, ui/settings/index.html}`, `tests/{conftest.py, test_manifest.py,
test_bridge.py, test_routes_dojo.py, test_live_elevenlabs.py}`, `pyproject.toml`,
`README.md`, `LICENSE`, `.gitignore`, `plans/001-mvp/{RESEARCH.md, PLAN.md,
execution-summary.md}`.

**Modified elsewhere:** `luna-marketplaces/marketplace-src/plugin_talk/` (seeded copy).
