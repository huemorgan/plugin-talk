"""plugin-talk routes — the bridge, session minting, voices, settings, static UI.

Auth model:
- ``/v1/chat/completions`` is called BY ELEVENLABS (server→server): gated by the
  vault-held bridge secret (constant-time compare), not by Luna login.
- Everything else is owner-facing: gated by ``luna_sdk.get_current_user``.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from luna_sdk import get_current_user

from . import VAULT_AGENT_ID, VAULT_API_KEY, VAULT_BRIDGE_SECRET, VAULT_SETTINGS, bridge
from .elevenlabs import ElevenLabsClient, ElevenLabsError
from .state import get_client, set_client

log = logging.getLogger("plugin-talk.routes")

_UI_DIR = Path(__file__).parent / "ui"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


AGENT_NAME = "Luna (plugin-talk)"


class _ConnectReq(BaseModel):
    # Optional at the schema level so a blank form yields a friendly 400 string
    # instead of FastAPI's 422 array (which UIs render as "[object Object]").
    api_key: str | None = None
    agent_id: str | None = None  # optional override; normally auto-provisioned


class _SettingsReq(BaseModel):
    voice_id: str | None = None


def register_routes(app, ctx):
    router = APIRouter(prefix="/api/p/plugin-talk", tags=["talk"])

    # ---------- vault helpers (resolved at call time, never cached) ----------

    def _vault():
        vault = getattr(ctx, "vault", None)
        if vault is None:
            raise HTTPException(503, "Vault not available")
        return vault

    async def _read(key: str) -> str | None:
        try:
            cred = await _vault().get_credential(key)
        except KeyError:
            return None
        value = (getattr(cred, "value", None) or "").strip()
        return value or None

    async def _client() -> ElevenLabsClient:
        client = get_client()
        if client is None:
            api_key = await _read(VAULT_API_KEY)
            if not api_key:
                raise HTTPException(400, "Not connected — add your ElevenLabs API key in Settings → Talk")
            client = ElevenLabsClient(api_key)
            set_client(client)
        return client

    async def _settings() -> dict:
        raw = await _read(VAULT_SETTINGS)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ---------- the bridge (ElevenLabs → Luna) ----------

    @router.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        secret = await _read(VAULT_BRIDGE_SECRET)
        if not secret:
            raise HTTPException(503, "Bridge not configured")
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token, secret):
            raise HTTPException(401, "Bad bridge credentials")

        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Expected a JSON body") from None
        messages = body.get("messages") or []
        if not isinstance(messages, list):
            raise HTTPException(400, "messages must be a list")

        agent = getattr(ctx, "agent", None)
        if agent is None:
            raise HTTPException(503, "Agent not available")

        prompt = bridge.build_prompt(messages)
        tools = bridge.voice_tool_allowlist(ctx)

        async def run() -> str:
            try:
                result = await agent.run_turn(prompt, tools=tools)
            except Exception:
                # bridge.stream_turn speaks a graceful fallback; make sure the
                # real cause lands in the server log instead of vanishing.
                log.exception("plugin-talk: voice turn failed")
                raise
            return bridge.normalize_reply(result)

        if body.get("stream", True):
            return StreamingResponse(
                bridge.stream_turn(run),
                media_type="text/event-stream",
                headers=_NO_CACHE,
            )
        return bridge.completion_json(await run())

    # ---------- owner-facing API ----------

    def _public_base(request: Request) -> str:
        """The externally reachable base URL of this Luna, for the agent's
        Custom LLM config. Proxy headers win (tenants sit behind one)."""
        proto = request.headers.get("x-forwarded-proto")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if host:
            return f"{proto or request.url.scheme}://{host}"
        return str(request.base_url).rstrip("/")

    def _is_local_host(base: str) -> bool:
        host = base.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith(".local")

    @router.post("/connect")
    async def connect(body: _ConnectReq, request: Request, user=Depends(get_current_user)):
        if not (body.api_key or "").strip():
            raise HTTPException(400, "Paste your ElevenLabs API key first")
        probe = ElevenLabsClient(body.api_key.strip())
        try:
            await probe.list_voices()
        except ElevenLabsError as exc:
            await probe.close()
            raise HTTPException(400, f"ElevenLabs rejected the key: {exc}") from exc

        vault = _vault()
        await vault.store_credential(VAULT_API_KEY, body.api_key.strip(), kind="api_key")
        if not await _read(VAULT_BRIDGE_SECRET):
            await vault.store_credential(
                VAULT_BRIDGE_SECRET, secrets.token_urlsafe(32), kind="api_key"
            )
        secret = await _read(VAULT_BRIDGE_SECRET)

        # ElevenLabs appends /chat/completions — hand it the base ending at /v1.
        public_base = _public_base(request)
        bridge_base = f"{public_base}/api/p/plugin-talk/v1"

        # One key is all the owner provides: find or create the Luna agent and
        # keep its custom-LLM config pointed at this Luna's bridge.
        # ElevenLabs' servers can never reach a localhost URL, so a local base
        # must NOT clobber an already-working public one (e.g. a tunnel).
        try:
            agent_id = (body.agent_id or "").strip() or await probe.find_agent(AGENT_NAME)
            if agent_id:
                current = await probe.get_agent_bridge_url(agent_id)
                keep_current = (
                    _is_local_host(public_base)
                    and current
                    and not _is_local_host(current)
                )
                if not keep_current:
                    await probe.update_agent_bridge(
                        agent_id, custom_llm_url=bridge_base, bridge_secret=secret
                    )
            else:
                agent_id = await probe.create_agent(
                    AGENT_NAME, custom_llm_url=bridge_base, bridge_secret=secret
                )
        except ElevenLabsError as exc:
            await probe.close()
            raise HTTPException(502, f"Could not provision the ElevenLabs agent: {exc}") from exc
        await vault.store_credential(VAULT_AGENT_ID, agent_id, kind="config")

        old = get_client()
        if old is not None:
            await old.close()
        set_client(probe)
        return await status(user=user)

    @router.post("/disconnect")
    async def disconnect(user=Depends(get_current_user)):
        vault = _vault()
        for key in (VAULT_API_KEY, VAULT_AGENT_ID):
            try:
                await vault.delete_credential(key)
            except KeyError:
                pass
        old = get_client()
        if old is not None:
            await old.close()
            set_client(None)
        return {"connected": False}

    @router.get("/status")
    async def status(user=Depends(get_current_user)):
        agent_id = await _read(VAULT_AGENT_ID)
        secret = await _read(VAULT_BRIDGE_SECRET)
        settings = await _settings()
        return {
            "connected": bool(await _read(VAULT_API_KEY)),
            "agent_id": agent_id,
            "voice_id": settings.get("voice_id"),
            # The owner pastes these two into the ElevenLabs agent's Custom LLM
            # config; the secret is owner-only output (this route is authed).
            "bridge_path": "/api/p/plugin-talk/v1/chat/completions",
            "bridge_secret": secret,
        }

    @router.get("/voices")
    async def voices(user=Depends(get_current_user)):
        client = await _client()
        try:
            return {"voices": await client.list_voices()}
        except ElevenLabsError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.get("/settings")
    async def get_settings(user=Depends(get_current_user)):
        return await _settings()

    @router.post("/settings")
    async def post_settings(body: _SettingsReq, user=Depends(get_current_user)):
        settings = await _settings()
        settings["voice_id"] = (body.voice_id or "").strip() or None
        await _vault().store_credential(
            VAULT_SETTINGS, json.dumps(settings), kind="config"
        )
        # Apply to the agent itself — per-session overrides need an explicit
        # permission on the agent, so the default voice is the reliable path.
        agent_id = await _read(VAULT_AGENT_ID)
        if agent_id and settings["voice_id"]:
            try:
                await (await _client()).set_agent_voice(agent_id, settings["voice_id"])
            except (ElevenLabsError, HTTPException) as exc:
                log.warning("plugin-talk: voice not applied to agent: %s", exc)
        return settings

    # GET as well as POST: the sidebar widget iframe has cookie auth only (the
    # shell doesn't hand widgets a bearer token), and cookie auth is read-only.
    # Minting a session token writes nothing in Luna, so GET is honest.
    @router.get("/session")
    @router.post("/session")
    async def session(user=Depends(get_current_user)):
        agent_id = await _read(VAULT_AGENT_ID)
        if not agent_id:
            raise HTTPException(400, "No agent id — finish setup in Settings → Talk")
        client = await _client()
        settings = await _settings()
        token = await client.conversation_token(agent_id)
        signed = None if token else await client.signed_url(agent_id)
        if not token and not signed:
            raise HTTPException(502, "Could not start an ElevenLabs session (check agent id / key)")
        return {
            "agent_id": agent_id,
            "conversation_token": token,
            "signed_url": signed,
            "voice_id": settings.get("voice_id"),
        }

    # ---------- static UI (widget + settings iframe) ----------

    def _serve(base: Path, path: str) -> FileResponse:
        if not path or path == "/":
            path = "index.html"
        target = (base / path).resolve()
        if not str(target).startswith(str(base.resolve())):
            raise HTTPException(403, "Forbidden")
        if not target.is_file():
            index = base / "index.html"
            if index.is_file():
                return FileResponse(str(index), headers=_NO_CACHE)
            raise HTTPException(404, "Not found")
        return FileResponse(str(target), headers=_NO_CACHE)

    @router.get("/ui/widgets/talk/{path:path}")
    async def widget_ui(path: str = ""):
        return _serve(_UI_DIR / "widgets" / "talk", path)

    @router.get("/ui/settings/{path:path}")
    async def settings_ui(path: str = ""):
        return _serve(_UI_DIR / "settings", path)

    app.include_router(router)
