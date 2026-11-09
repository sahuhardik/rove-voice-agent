"""Run the server.

    .venv/bin/python -m server

Binds ``0.0.0.0`` on one port (8080 by default, `ROVE_WEB_PORT` to change it),
so the session can be opened from a browser that is not on this host. See
`server/README.md` for what else has to be open — the signalling port is TCP
and the media is not.

In the default ``livekit`` transport this process does **not** carry the media:
it mints the room token, runs the agent worker, and the browser joins the media
server directly. A `livekit-server` has to be running and reachable at
``ROVE_LIVEKIT_URL`` — ``python -m server.livekit_dev`` is the local one.
"""

from __future__ import annotations

import sys

import uvicorn

from server.app import create_app
from server.config import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    app = create_app(settings)

    title = (
        "Rove — Phase 3 voice pipeline (LiveKit rooms, streaming Transcribe, Silero VAD)"
        if settings.is_livekit
        else "Rove — SmallWebRTC fallback transport (docs/07 D-02)"
    )
    banner = [
        "",
        f"  {title}",
        f"  listening on   {settings.host}:{settings.port}  ({settings.scheme})",
        f"  open           {settings.scheme}://<this-host>:{settings.port}/",
        f"  transport      {settings.transport}",
        f"  trace          {settings.trace_dir}",
        f"  tts            Polly {settings.polly_engine} / {settings.polly_voice}",
        f"  vad            Silero v5  start={settings.vad_start_secs}s "
        f"conf={settings.vad_confidence}",
        f"  token ttl      {settings.token_ttl_seconds}s, single-room, single-identity",
        f"  console        {settings.scheme}://<this-host>:{settings.port}/support"
        + ("" if settings.console_dist.is_dir() else "   (not built — node support/build.mjs)"),
        f"  observer ttl   {settings.observer_ttl_seconds}s, separate scope "
        "(observe:room), never the caller token",
    ]
    if settings.support_key_is_ephemeral:
        # Printed because it is generated: an operator who cannot read the key
        # cannot open the console, and a key nobody can see is not a security
        # property, it is a locked room with the key inside.
        banner.append(f"  support key    {settings.support_key}   (set ROVE_SUPPORT_KEY to pin it)")
    else:
        banner.append("  support key    from ROVE_SUPPORT_KEY")
    if settings.is_livekit:
        from server import endpointing

        banner.append(f"  media server   {settings.livekit_url}")
        banner.append(
            f"  agent worker   {'in this process' if settings.livekit_worker_inprocess else 'external'}"
        )
        banner.append(
            "  asr            " + (
                "Amazon Transcribe streaming"
                + (
                    f", vocabulary {settings.transcribe_vocabulary}"
                    if settings.transcribe_vocabulary
                    else ", unbiased"
                )
                if settings.use_transcribe
                else "off — typed turns only"
            )
        )
        banner.append(
            "  endpointing    context-dependent, "
            + ", ".join(
                f"{row.turn_type.value} {row.min_ms}–{row.max_ms}ms"
                for row in endpointing.HANGOVERS.values()
            )
        )
        if settings.livekit_keys_are_dev:
            banner.append(
                "  NOTE: running on LiveKit's published --dev key pair (devkey/secret)."
                " Local loop only — set ROVE_LIVEKIT_API_KEY / ROVE_LIVEKIT_API_SECRET"
                " before this is reachable from anywhere else."
            )
    elif settings.public_ip:
        banner.append(f"  ice advertises {settings.public_ip} (1:1 NAT rewrite)")
    else:
        banner.append(
            "  ice advertises this host's own interfaces only — set ROVE_PUBLIC_IP"
            " (or =auto) to reach a browser elsewhere"
        )
    if settings.token_secret_is_ephemeral and not settings.is_livekit:
        banner.append(
            "  NOTE: ROVE_TOKEN_SECRET unset — tokens are signed with a per-process"
            " secret and every restart invalidates them"
        )
    banner.append("")
    print("\n".join(banner), flush=True)

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        ssl_certfile=settings.tls_certfile or None,
        ssl_keyfile=settings.tls_keyfile or None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
