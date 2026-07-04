# plugin-talk

Talk to Luna by voice, in the browser.

- **Sidebar widget** with a live dual voice visualization — your voice (teal) and
  Luna's (violet) vibrate as you speak; a calm pulse shows Luna thinking during
  slow tool calls.
- **ElevenLabs Agents** carries the audio: microphone, speech-to-text,
  text-to-speech, turn-taking and barge-in run browser ⇄ ElevenLabs (WebRTC,
  WebSocket fallback). Audio never touches the Luna server — ideal for small
  hosted instances.
- **Luna stays the brain.** The plugin serves an OpenAI-compatible bridge
  (`POST /api/p/plugin-talk/v1/chat/completions`, SSE) that your ElevenLabs
  agent uses as its Custom LLM; every reply comes from Luna's own agent loop
  (`run_turn`) with her tools and memory. The stream opens with a short
  "buffer words" chunk so long tool calls keep the audio natural.

## Setup

1. Install the plugin (needs `plugin-vault`).
2. In ElevenLabs: create an **Agents** agent, note its ID.
3. In Luna → Settings → Talk: paste your ElevenLabs API key + agent ID,
   click Connect. Copy the shown **Custom LLM URL** and **Authorization
   header** into your ElevenLabs agent (Agent → LLM → Custom LLM), and disable
   the agent's own tools/RAG.
4. Pick Luna's voice in the same tab (optional — otherwise the agent default).
5. Click **Talk** in the sidebar widget.

All keys live in Luna's vault. The bridge is protected by a generated secret;
voice turns run with a restricted tool allowlist (no high-risk or
prompt-always tools — voice has no approval UI).

## Tests

```bash
pip install -e ".[dev]" && pytest
# live ElevenLabs smoke test (optional):
LUNA_TEST_ELEVENLABS_KEY=sk_... pytest tests/test_live_elevenlabs.py
```

Source: https://github.com/huemorgan/plugin-talk — MIT.
