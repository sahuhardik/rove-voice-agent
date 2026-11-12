"""Same-origin relay for LiveKit signalling, so an https page can join a room.

Why this exists: the mint hands the browser `settings.livekit_url`, which is
`ws://127.0.0.1:7880`. A page served over https may not open a `ws://` URL
(mixed content), and `livekit-server` does not terminate TLS on its signalling
port. With no reverse proxy installed, this process is the TLS terminator:

    browser --wss://host/lk/...--> this app --ws://127.0.0.1:7880/...--> livekit-server

Only **signalling** goes through here (the `/rtc` WebSocket and the
`/rtc/validate` GET the SDK uses to explain a failed join). ICE and the UDP
media path go browser <-> media server directly and are unaffected.

The relay is a dumb pipe: it does not read or alter frames, and it adds no
authority — the media server still verifies the access token it is given.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from server.config import Settings

#: Prefix the page is given by `Settings.livekit_public_url`.
RELAY_PREFIX = "/lk"
#: A dead media server must be a fast 502, not a hung join.
UPSTREAM_TIMEOUT_SECS = 10.0
#: Response headers that describe the hop, not the content.
_HOP_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}


#: Request headers the media server needs. The current LiveKit SDK carries the
#: join token in `Authorization`, not only in the query string.
_FORWARDED_HEADERS = ("authorization", "user-agent")


def _forwarded(headers) -> dict[str, str]:
    return {name: headers[name] for name in _FORWARDED_HEADERS if name in headers}


#: Close codes that may appear on the wire (1005/1006/1015 are reserved).
_SENDABLE_CLOSE_CODES = {*range(1000, 1004), *range(1007, 1015), *range(3000, 5000)}


def _is_signalling(path: str) -> bool:
    """Only `rtc`, `rtc/v1` and their `validate` probes: not the rest of the
    media server's HTTP surface (admin API, metrics, debug)."""
    return path == "rtc" or path.startswith("rtc/")


def _upstream(settings: Settings, path: str, query: str, *, http: bool) -> str:
    base = settings.livekit_url.rstrip("/")
    if http:
        base = base.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    url = f"{base}/{path}"
    return f"{url}?{query}" if query else url


def register_livekit_relay(app: FastAPI, settings: Settings) -> None:
    @app.websocket(RELAY_PREFIX + "/{path:path}")
    async def relay_socket(socket: WebSocket, path: str) -> None:
        if not _is_signalling(path):
            await socket.close(code=1008)  # rejected before accept: HTTP 403
            return
        url = _upstream(settings, path, socket.url.query, http=False)
        requested = [
            p.strip()
            for p in socket.headers.get("sec-websocket-protocol", "").split(",")
            if p.strip()
        ]
        try:
            upstream = await websockets.connect(
                url,
                additional_headers=_forwarded(socket.headers),
                subprotocols=requested or None,
                open_timeout=UPSTREAM_TIMEOUT_SECS,
                max_size=None,
            )
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError):
            await socket.close(code=1014)  # bad gateway
            return
        await socket.accept(subprotocol=upstream.subprotocol)

        async def up() -> None:
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data = message.get("bytes")
                await upstream.send(data if data is not None else message["text"])

        async def down() -> None:
            async for message in upstream:
                if isinstance(message, bytes):
                    await socket.send_bytes(message)
                else:
                    await socket.send_text(message)

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await upstream.close()
            code = upstream.close_code
            with contextlib.suppress(Exception):  # peer may already be gone
                # Relay the media server's own close code (e.g. a token error)
                # so the SDK can tell a normal leave from a failure.
                await socket.close(code=code if code in _SENDABLE_CLOSE_CODES else 1000)

    @app.get(RELAY_PREFIX + "/{path:path}")
    async def relay_get(request: Request, path: str) -> Response:
        if not _is_signalling(path):
            return Response("not a signalling path", status_code=404, media_type="text/plain")
        url = _upstream(settings, path, request.url.query, http=True)
        try:
            async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECS) as client:
                reply = await client.get(url, headers=_forwarded(request.headers))
        except httpx.HTTPError:
            return Response("media server unreachable", status_code=502, media_type="text/plain")
        headers = {k: v for k, v in reply.headers.items() if k.lower() not in _HOP_HEADERS}
        return Response(reply.content, status_code=reply.status_code, headers=headers)
