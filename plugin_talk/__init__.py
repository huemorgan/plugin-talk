"""plugin-talk — talk to Luna by voice in the browser.

ElevenLabs Agents handles the audio loop (mic, STT, TTS, barge-in) between the
browser and their edge; Luna stays the brain via an OpenAI-compatible bridge
route this plugin serves (see `bridge.py` / `routes.py`). Authored against
`luna_sdk` only.
"""

from __future__ import annotations

import logging

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, SettingsTab

log = logging.getLogger("plugin-talk")

# Vault keys (all owned by this plugin; ACL-scoped by the vault provider).
VAULT_API_KEY = "plugin_talk.elevenlabs_api_key"
VAULT_AGENT_ID = "plugin_talk.agent_id"
VAULT_BRIDGE_SECRET = "plugin_talk.bridge_secret"
VAULT_SETTINGS = "plugin_talk.settings"  # non-secret JSON (voice_id, ...); vault used as the plugin's durable KV


class TalkPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-talk",
        shown_name="Talk",
        icon="mic",
        version="0.1.3",
        description=(
            "Talk to Luna by voice in the browser — sidebar voice widget, "
            "ElevenLabs handles audio, Luna stays the brain."
        ),
        category="global",
        depends_on=["plugin-vault"],
        routes_module="routes",
        settings_tabs=[
            SettingsTab(
                id="talk",
                label="Talk",
                icon="mic",
                sort_order=75,
                iframe_src="/api/p/plugin-talk/ui/settings/",
            ),
        ],
        # WidgetSlot isn't re-exported from luna_sdk yet (only SettingsTab is);
        # PluginManifest.widgets is pydantic-validated, so a plain dict works.
        widgets=[
            {"id": "talk", "slot": "sidebar.bottom", "label": "Talk to Luna", "height": 180},
        ],
    )

    async def on_load(self, ctx: PluginContext) -> None:
        # Everything lives in routes (bridge + session + settings + static UI).
        # No agent tools are registered — the plugin is an interface, not a
        # capability; the bridge turn borrows the owner's installed tools.
        log.info("plugin-talk loaded (widget=talk, settings tab=talk)")

    async def on_unload(self) -> None:
        from .state import close_client

        await close_client()
