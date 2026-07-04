"""ElevenLabs REST calls — all of them live here, nowhere else.

The API key is passed at construction (resolved from the vault by routes) and
only ever sent as the ``xi-api-key`` header. Never logged.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsError(Exception):
    """A failed ElevenLabs call, with a safe (key-free) message."""


class ElevenLabsClient:
    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(15.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _req(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> dict[str, Any]:
        try:
            resp = await self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"ElevenLabs unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise ElevenLabsError(f"ElevenLabs {path} failed: HTTP {resp.status_code}")
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        return await self._req("GET", path, params=params or None)

    async def list_voices(self) -> list[dict[str, Any]]:
        """The account's voices, trimmed to what the picker needs."""
        data = await self._get("/v1/voices")
        return [
            {
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "preview_url": v.get("preview_url"),
            }
            for v in data.get("voices", [])
            if v.get("voice_id")
        ]

    async def conversation_token(self, agent_id: str) -> str | None:
        """Short-lived WebRTC conversation token for a (private) agent."""
        try:
            data = await self._get("/v1/convai/conversation/token", agent_id=agent_id)
        except ElevenLabsError:
            return None
        return data.get("token") or None

    async def signed_url(self, agent_id: str) -> str | None:
        """Signed WebSocket URL — fallback transport when token/WebRTC is unavailable."""
        try:
            data = await self._get("/v1/convai/conversation/get-signed-url", agent_id=agent_id)
        except ElevenLabsError:
            return None
        return data.get("signed_url") or None

    # ------------------------------------------------------- agent provisioning

    @staticmethod
    def _agent_config(custom_llm_url: str, bridge_secret: str) -> dict[str, Any]:
        # api_type "chat_completions": ElevenLabs appends /chat/completions to
        # the url, so we hand it the bridge base ending at .../v1 (verified
        # live against the API, 2026-07).
        return {
            "agent": {
                "first_message": "Hi, I'm Luna. What can I do for you?",
                "prompt": {
                    "prompt": (
                        "You are Luna. Every reply is produced by the connected "
                        "custom LLM (Luna's own agent loop); pass conversation "
                        "through faithfully."
                    ),
                    "llm": "custom-llm",
                    "custom_llm": {
                        "url": custom_llm_url,
                        "model_id": "luna",
                        "request_headers": {"Authorization": f"Bearer {bridge_secret}"},
                    },
                },
            },
        }

    async def find_agent(self, name: str) -> str | None:
        data = await self._get("/v1/convai/agents", page_size=100)
        for agent in data.get("agents", []):
            if agent.get("name") == name and agent.get("agent_id"):
                return agent["agent_id"]
        return None

    async def create_agent(self, name: str, *, custom_llm_url: str, bridge_secret: str) -> str:
        data = await self._req(
            "POST",
            "/v1/convai/agents/create",
            json={"name": name, "conversation_config": self._agent_config(custom_llm_url, bridge_secret)},
        )
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ElevenLabsError("agent create returned no agent_id")
        return agent_id

    async def update_agent_bridge(self, agent_id: str, *, custom_llm_url: str, bridge_secret: str) -> None:
        """Re-point an existing agent at the (possibly moved) bridge + fresh secret."""
        await self._req(
            "PATCH",
            f"/v1/convai/agents/{agent_id}",
            json={"conversation_config": self._agent_config(custom_llm_url, bridge_secret)},
        )
