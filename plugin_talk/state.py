"""Module-level live state — the shared ElevenLabs HTTP client.

Same pattern as plugin-render's `state.py`: the client is swapped when the
owner connects/disconnects, and resolved at call time (never cached on the
plugin instance).
"""

from __future__ import annotations

from typing import Any

_client: Any = None


def get_client() -> Any:
    return _client


def set_client(client: Any) -> None:
    global _client
    _client = client


async def close_client() -> None:
    global _client
    if _client is not None:
        try:
            await _client.close()
        finally:
            _client = None
