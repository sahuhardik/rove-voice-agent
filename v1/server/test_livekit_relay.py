"""Stdlib unittest for the same-origin LiveKit signalling relay.

    .venv/bin/python -m unittest server.test_livekit_relay -v

An https page cannot open `ws://127.0.0.1:7880` (mixed content), and
livekit-server does not terminate TLS, so `server/livekit_relay.py` forwards
`/lk/*` to `settings.livekit_url`. Hermetic: the "media server" here is a
loopback `websockets` server, so nothing depends on a real LiveKit.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import uvicorn
import websockets
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from server.app import create_app
from server.config import Settings


class PublicUrlTests(unittest.TestCase):
    def test_https_request_gets_wss_through_the_relay(self) -> None:
        settings = Settings()
        self.assertEqual(
            settings.livekit_public_url("https", "demo.example:8443"),
            "wss://demo.example:8443/lk",
        )

    def test_http_request_gets_the_media_server_url_unchanged(self) -> None:
        settings = Settings(livekit_url="ws://10.0.0.5:7880")
        self.assertEqual(settings.livekit_public_url("http", "x:8080"), "ws://10.0.0.5:7880")

    def test_hostile_host_header_falls_back_to_the_media_server_url(self) -> None:
        settings = Settings()
        for host in ("", "evil/x", "a b", "a@b", "a?b", "a#b"):
            self.assertEqual(settings.livekit_public_url("https", host), settings.livekit_url)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.seen: list[str] = []
        self.auth: list[str] = []

        async def echo(ws) -> None:
            self.seen.append(ws.request.path)
            self.auth.append(ws.request.headers.get("Authorization", ""))
            async for message in ws:
                await ws.send(message)

        def http_probe(connection, request):
            if request.path.startswith("/rtc/validate"):
                got = request.headers.get("Authorization", "")
                return Response(200, "OK", Headers({"Content-Type": "text/plain"}), got.encode())
            return None

        self.upstream = await serve(echo, "127.0.0.1", 0, process_request=http_probe)
        up_port = self.upstream.sockets[0].getsockname()[1]
        settings = Settings(livekit_url=f"ws://127.0.0.1:{up_port}")
        app = create_app(settings)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        )
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        self.server.should_exit = True
        await self.task
        self.upstream.close()
        await self.upstream.wait_closed()

    async def test_websocket_frames_round_trip_text_and_binary_with_query(self) -> None:
        async with websockets.connect(f"ws://127.0.0.1:{self.port}/lk/rtc?access_token=abc") as ws:
            await ws.send(b"\x00\x01\x02")
            self.assertEqual(await ws.recv(), b"\x00\x01\x02")
            await ws.send("hello")
            self.assertEqual(await ws.recv(), "hello")
        self.assertIn("/rtc?access_token=abc", self.seen)  # the in-process worker also dials in

    async def test_authorization_header_reaches_the_media_server_on_the_socket(self) -> None:
        # The current LiveKit SDK carries the token in this header, not the query.
        async with websockets.connect(
            f"ws://127.0.0.1:{self.port}/lk/rtc/v1?join_request=x",
            additional_headers={"Authorization": "Bearer tok-123"},
        ) as ws:
            await ws.send("ping")
            await ws.recv()
        self.assertIn("Bearer tok-123", self.auth)

    async def test_get_is_forwarded_with_its_authorization_header(self) -> None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"http://127.0.0.1:{self.port}/lk/rtc/validate?access_token=x",
                headers={"Authorization": "Bearer tok-456"},
            )
        self.assertEqual((r.status_code, r.text), (200, "Bearer tok-456"))

    async def test_only_signalling_paths_are_relayed(self) -> None:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://127.0.0.1:{self.port}/lk/twirp/livekit.RoomService/ListRooms")
        self.assertEqual(r.status_code, 404)
        with self.assertRaises(websockets.exceptions.InvalidStatus):
            async with websockets.connect(f"ws://127.0.0.1:{self.port}/lk/debug/pprof"):
                pass

    async def test_unreachable_media_server_gives_502_not_a_hang(self) -> None:
        app = create_app(Settings(livekit_url="ws://127.0.0.1:1"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/lk/rtc/validate")
        self.assertEqual(r.status_code, 502)


if __name__ == "__main__":
    unittest.main()
