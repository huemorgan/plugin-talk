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

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        try:
            resp = await self._http.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"ElevenLabs unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise ElevenLabsError(f"ElevenLabs {path} failed: HTTP {resp.status_code}")
        return resp.json()

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
