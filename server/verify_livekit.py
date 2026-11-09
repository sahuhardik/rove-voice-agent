"""Verify the Phase 3 voice pipeline from outside itself.

    .venv/bin/python -m server.verify_livekit
    .venv/bin/python -m server.verify_livekit --json
    .venv/bin/python -m server.verify_livekit --no-llm

`server/verify.py` is this file's Phase 2b sibling and still verifies the
Pipecat fallback. This one verifies what `docs/06` §9.1 Phase 3 actually asks
for — *"promote to LiveKit Agents, then: streaming Transcribe with biasing,
Silero VAD v5, context-dependent endpointing"* — and it does it the only way
that means anything: by starting a real media server, joining a real room with
a real credential, and speaking real synthesised speech into it.

Six things, in the order that makes a failure readable. Each runs only if the
one before it held, because a transcript check after a failed join tells you
nothing you did not already know.

1. **The media server is there.** `livekit-server --dev` binds and answers.
2. **The mint issues a LiveKit credential (§1.4.2).** Short-lived, single-room,
   single-identity, HS256 over the API secret, and carrying neither
   `roomCreate` nor `roomAdmin`. A token minted for one room is refused on
   another, and an expired one is refused now.
3. **Both participants are in the room.** The browser's stand-in
   (`server/livekit_peer.py`) joins with the minted token; the agent worker is
   dispatched into the same room and publishes its voice track.
4. **Audio flows and the recogniser hears it.** 20 ms frames up at real-time
   pace, Silero VAD v5 segments them, and Amazon Transcribe returns a
   transcript for the spoken utterance.
5. **The endpointer closes the turn (§2.3).** `endpoint.armed` chose a row of
   §2.3's table and `endpoint.fired` reports the hangover that was actually
   used and the silence that satisfied it — and the turn reaches the same
   `agent.core` function a typed turn does.
6. **The typed path still works (§1.4.1 item 3).** A turn typed over the
   control socket is answered *and spoken into the room*, which is what makes
   it one session rather than two.
7. **Barge-in cuts the agent off (§2.1).** The caller talks over a *full
   length* greeting: `agent.flush` reaches the browser, the greeting stops
   with a remainder it never spoke, `barge_in.detected` is in the trace, and
   the sentence the caller interrupted with is dispatched as a turn.

Check 7 runs against a **second** API process, started after the first has
stopped. The greeting is `Settings.greeting_text` — process-wide, not
per-session — and `server/livekit_agent.py` keeps the worker's `AgentHost` in
a module global, so two API processes cannot be up at once. Sequential is the
honest way to get both a short greeting for checks 1–6 (where eight seconds of
playout is dead time) and the real, long one for check 7 (where the length is
the point). Both phases share the one media server.

**This needs AWS** (Polly for the microphone fixture and the agent's voice,
Transcribe for the recogniser) and the `livekit-server` binary. It is the
counterpart to `server/test_livekit.py`, which is hermetic and needs neither.

The exit code is 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

from server import livekit_dev, livekit_peer, livekit_tokens, polly
from server.config import DEFAULT_GREETING, REPO_ROOT, Settings
from server.verify import BackgroundServer, Report, free_port

#: What the headless participant says into the microphone. Chosen to carry
#: §3.4's confusables — the model name and the thing that changed — because
#: D-05 leaves "biasing behaviour on *our* confusables" explicitly unmeasured
#: and a fixture of "hello testing one two three" would leave it there.
MIC_LINE = "My Rove R2-4K stopped recording after the firmware update."

#: A short greeting, so the verification is not gated on eight seconds of
#: playout. The agent will not hear the caller while it is speaking (there is
#: no barge-in until Milestone 6.2), so greeting length is dead time here and
#: nothing else — the default greeting is unchanged and is what a user gets.
VERIFY_GREETING = "I can hear you. Tell me what the camera is doing."

#: What a typed turn says. Deliberately *not* the same sentence as `MIC_LINE`:
#: a second turn on the same session, so the reply is a step in a conversation
#: and the one-session claim in §1.4.1 item 3 is actually exercised.
TYPED_LINE = "the red light is blinking"

#: What the caller says *over* the greeting. It opens with the interruption a
#: real caller makes and then states a symptom, so the turn the barge-in
#: produces is a turn the core can answer — a check that proved only "the
#: audio stopped" would leave §2.1's second half ("re-anchors rather than
#: restarting") untested.
BARGE_IN_LINE = "Sorry — hang on. My camera stopped recording after the update."

#: How far into the greeting the caller cuts in. Long enough that there is
#: real audio on the wire to throw away (so `queued_ms` and `played_ms` mean
#: something), short enough that the greeting has most of itself left to lose.
BARGE_IN_AFTER_S = 1.5

#: Below this, a "greeting" is not long enough for talking over it to prove
#: anything, and the check says so rather than passing on a fixture that could
#: not have failed.
MIN_BARGE_IN_GREETING_MS = 4000


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


async def verify_mint(
    http: httpx.AsyncClient, base_url: str, settings: Settings, report: Report
) -> dict[str, Any]:
    """§1.4.2, in the shape the media server will accept (`docs/07` D-02)."""
    first = await livekit_peer.open_session(http, base_url)
    second = await livekit_peer.open_session(http, base_url)

    report.check(
        "mint returns a room, an identity, a token and the media-server URL",
        bool(first.get("room") and first.get("identity") and first.get("token")),
    )
    report.check(
        "mint declares the transport and where to point it",
        first.get("transport") == "livekit" and bool(first.get("livekit_url")),
        f"{first.get('transport')} at {first.get('livekit_url')}",
    )

    ttl = int(first.get("ttl_seconds", 0))
    report.check(
        "token is short-lived",
        0 < ttl <= livekit_tokens.MAX_TTL_SECONDS,
        f"ttl={ttl}s, ceiling={livekit_tokens.MAX_TTL_SECONDS}s",
    )

    try:
        claims = livekit_tokens.verify(
            first["token"],
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            room=first["room"],
            identity=first["identity"],
        )
        verified: Any = claims
    except Exception as exc:  # noqa: BLE001
        verified = None
        report.check("token verifies for its own room and identity", False, str(exc))
    if verified is not None:
        report.check(
            "token verifies for its own room and identity",
            verified.room == first["room"] and verified.identity == first["identity"],
        )
        grant = verified.video_grant
        report.check(
            "token grants roomJoin, publish, subscribe and data — and nothing more",
            grant.get("roomJoin") is True
            and grant.get("canPublish") is True
            and grant.get("canPublishData") is True
            and not any(grant.get(k) for k in ("roomCreate", "roomAdmin", "roomList")),
            ",".join(sorted(k for k, v in grant.items() if v is True)),
        )

    report.check(
        "rooms and identities are distinct per session",
        first["room"] != second["room"] and first["identity"] != second["identity"],
    )

    cross = False
    try:
        livekit_tokens.verify(
            first["token"],
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            room=second["room"],
        )
    except livekit_tokens.TokenScopeError:
        cross = True
    report.check("a token minted for one room is refused on another", cross)

    replay = await http.get(
        f"{base_url}/api/trace/{second['room']}", params={"token": first["token"]}
    )
    report.check(
        "the server refuses a cross-room token at the endpoint, not only in the library",
        replay.status_code == 403,
        f"HTTP {replay.status_code}",
    )

    stale = livekit_tokens.mint(
        room=first["room"],
        identity=first["identity"],
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        ttl_seconds=60,
        now=time.time() - 3600,
    )
    expired = await http.get(
        f"{base_url}/api/trace/{first['room']}", params={"token": stale}
    )
    report.check(
        "a correctly signed but expired token is refused",
        expired.status_code == 401,
        f"HTTP {expired.status_code}",
    )
    report.fact("token", f"HS256 JWT, {ttl}s, room={first['room']}")
    return first


async def _wait_for_greeting(peer: livekit_peer.HeadlessParticipant, timeout: float) -> bool:
    """Hold until the agent stops talking.

    Checks 1–6 wait the greeting out rather than cut it short: barge-in has
    its own check and its own process, and a turn that began by interrupting
    would not be the plain turn these checks are about.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(m.get("state") == "end" for m in peer.of_type("agent.speech")):
            return True
        if any(m.get("state") == "failed" for m in peer.of_type("agent.speech")):
            return False
        await asyncio.sleep(0.1)
    return False


async def _next_speech(
    peer: livekit_peer.HeadlessParticipant,
    *states: str,
    since: int,
    timeout: float,
) -> dict[str, Any] | None:
    """The next `agent.speech` in one of `states` past the mark, or `None`."""
    deadline = time.time() + timeout
    seen = max(0, since)
    while time.time() < deadline:
        for message in peer.messages[seen:]:
            if message.get("type") != "agent.speech":
                continue
            if message.get("state") in states:
                return message
            if message.get("state") == "failed":
                return None
        seen = len(peer.messages)
        await asyncio.sleep(0.05)
    return None


async def verify_voice(
    session: dict[str, Any],
    settings: Settings,
    report: Report,
) -> livekit_peer.HeadlessParticipant:
    """The room, the audio, the VAD, the recogniser and the endpointer."""
    sample_rate = int(session.get("audio_sample_rate", 16000))
    mic_pcm = await asyncio.to_thread(
        polly.synthesize_pcm,
        MIC_LINE,
        voice=settings.polly_voice,
        engine=settings.polly_engine,
        sample_rate=sample_rate,
        cache_dir=settings.polly_cache_dir,
    )
    report.fact("microphone fixture", f'"{MIC_LINE}" ({polly.duration_ms(mic_pcm, sample_rate)} ms)')

    peer = livekit_peer.HeadlessParticipant(
        url=session["livekit_url"],
        token=session["token"],
        sample_rate=sample_rate,
        identity=session["identity"],
    )
    await peer.connect()
    report.check("the caller joined the room with the minted token", True, f"{peer.connected_at}s")

    joined = await peer.wait_for_agent(timeout=45.0)
    report.check(
        "the agent worker was dispatched into the same room",
        joined,
        peer.agent_identity or "no participant arrived",
    )
    if not joined:
        return peer
    report.check(
        "the agent published a voice track", await peer.wait_for_agent_track(timeout=30.0)
    )
    await peer.publish_microphone()

    spoke = await _wait_for_greeting(peer, timeout=60.0)
    report.check(
        "the agent spoke its greeting into the room",
        spoke and peer.returned.audible_seconds > 0.3,
        f"{peer.returned.frames} frames, {peer.returned.audible_seconds:.2f}s audible "
        f"at {peer.returned.sample_rate} Hz",
    )

    armed = await peer.wait_for_message("endpoint.armed", timeout=15.0)
    report.check(
        "the endpointer armed a §2.3 row for the caller's turn",
        armed is not None,
        f"{armed.get('turn_type')} {armed.get('hangover_min_ms')}–{armed.get('hangover_max_ms')} ms"
        if armed
        else "no endpoint.armed",
    )

    asr_state = next(iter(peer.of_type("asr.state")), {})
    report.check(
        "the recogniser is streaming",
        bool(asr_state.get("available")),
        f"vocabulary={asr_state.get('vocabulary')}" if asr_state.get("available")
        else str(asr_state.get("detail", "no asr.state message")),
    )

    before = peer.returned.audible_seconds
    spoken_s = await peer.speak(mic_pcm, lead_silence_ms=300)
    # Past the longest hangover in §2.3's table, so the endpointer has had its
    # chance however the turn was classified — and paced, so the silence the
    # VAD measures is real silence on the wire.
    await peer.hold_silence(3.0)
    report.fact("microphone pushed", f"{spoken_s:.2f}s at real-time pace")

    levels = peer.of_type("audio.level")
    report.check(
        "audio frames arrived at the agent",
        bool(levels) and levels[-1].get("frames", 0) > 50,
        f"{levels[-1].get('frames') if levels else 0} frames of 20 ms",
    )
    report.check(
        "Silero VAD v5 segmented the speech",
        len(peer.speech_segments) >= 1,
        ", ".join(f"{s.get('duration_ms')} ms" for s in peer.speech_segments) or "no segments",
    )

    partials = peer.of_type("asr.partial")
    report.check(
        "Transcribe returned a transcript for the spoken utterance",
        bool(partials) and bool((partials[-1].get("text") or "").strip()),
        f'{len(partials)} hypothesis(es), last: "{(partials[-1].get("text") if partials else "")}"',
    )

    fired = await peer.wait_for_message("endpoint.fired", timeout=20.0)
    report.check(
        "the endpointer closed the turn",
        fired is not None,
        f"{fired.get('turn_type')} at {fired.get('silence_ms')} ms of silence "
        f"against a {fired.get('hangover_ms')} ms hangover ({fired.get('reason')})"
        if fired
        else "no endpoint.fired",
    )
    if fired:
        report.fact(
            "§2.2 line 2 — endpoint decision",
            f"{fired.get('hangover_ms')} ms hangover, {fired.get('silence_ms')} ms silence, "
            f"completeness {fired.get('completeness')}",
        )
    return peer


async def verify_voice_turn(
    http: httpx.AsyncClient,
    base_url: str,
    session: dict[str, Any],
    peer: livekit_peer.HeadlessParticipant,
    report: Report,
) -> None:
    """The transcript became a turn, through the same core a typed turn uses."""
    events = await _trace_events(http, base_url, session, timeout=45.0, until="turn.reply")
    # The reply is spoken *after* turn.reply is recorded (Polly synthesis
    # then playback), so the event list fetched for turn.reply contains
    # only the greeting's tts.played. Wait for the reply's own tts.played
    # before judging whether the reply was spoken back into the room.
    events = await _trace_events(
        http, base_url, session, timeout=45.0, until="tts.played", min_count=2
    )
    voice = [e for e in events if e["type"] == "turn.voice"]
    report.check(
        "the transcript was dispatched as a voice turn",
        bool(voice),
        f'"{voice[-1].get("normalised")}"' if voice else "no turn.voice in the trace",
    )
    if voice:
        report.fact("heard", voice[-1].get("verbatim"))
        report.fact("normalised", voice[-1].get("normalised"))
        report.fact("§2.2 line 3 — ASR final flush", f"{voice[-1].get('asr_flush_ms')} ms")
        report.fact("asr confidence", voice[-1].get("confidence"))
        report.fact(
            "§3.4 alias candidates",
            json.dumps(voice[-1].get("asr_candidates") or [], sort_keys=True),
        )

    replies = [e for e in events if e["type"] == "turn.reply" and e.get("modality") == "voice"]
    report.check(
        "the voice turn reached the diagnostic core",
        bool(replies),
        f"{replies[-1].get('step_id') or replies[-1].get('taxonomy_id') or 'escalated'} "
        f"in state {replies[-1].get('fsm_state')}"
        if replies
        else "no voice turn.reply",
    )
    if replies:
        report.fact("§2.2 lines 4–6 — gate, FSM, retrieval, LLM", f"{replies[-1].get('latency_ms')} ms")
        report.fact("reply", (replies[-1].get("text") or "")[:120])

    played = [e for e in events if e["type"] == "tts.played"]
    report.check(
        "the agent spoke the reply back into the room",
        len(played) >= 2,
        f"{len(played)} utterance(s)",
    )
    if played:
        report.fact("§2.2 line 7 — TTS time-to-first-audio", f"{played[-1].get('synthesis_ms')} ms")


async def verify_typed_turn(
    ws_url: str,
    session: dict[str, Any],
    peer: livekit_peer.HeadlessParticipant,
    report: Report,
) -> None:
    """§1.4.1 item 3: the typed turn is the same session, and it is spoken."""
    url = f"{ws_url}/ws?room={session['room']}&token={session['token']}"
    spoken_before = len(peer.of_type("agent.speech"))
    reply: dict[str, Any] | None = None
    async with websockets.connect(url, open_timeout=20, max_size=4 * 1024 * 1024) as socket:
        hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
        report.check("the control socket accepted the LiveKit token", hello.get("type") == "hello")
        turns_before = len((hello.get("snapshot") or {}).get("transcript") or [])
        report.check(
            "the control socket replays the voice turn already in the session",
            turns_before >= 2,
            f"{turns_before} transcript line(s) before the typed turn",
        )
        # §2.3's typing suppressor, sent the way the page sends it.
        await socket.send(json.dumps({"type": "user.typing"}))
        await socket.send(
            json.dumps({"type": "user.text", "text": TYPED_LINE, "modality": "typed"})
        )
        deadline = time.time() + 120
        while time.time() < deadline:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=120))
            if message.get("type") == "turn.reply":
                reply = message["reply"]
                break
            if message.get("type") == "error":
                report.check("typed turn answered", False, str(message.get("detail")))
                return

    report.check("typed turn answered with words", bool(reply and reply.get("text")))
    if not reply:
        return
    report.check(
        "typed reply carries a step or an escalation",
        bool(reply.get("step")) or bool(reply.get("escalate")),
        (reply.get("step") or {}).get("step_id") or "escalated",
    )
    report.fact("typed reply", (reply.get("text") or "")[:120])

    deadline = time.time() + 45
    while time.time() < deadline and len(peer.of_type("agent.speech")) <= spoken_before:
        await asyncio.sleep(0.2)
    report.check(
        "the agent spoke the typed turn's reply into the room",
        len(peer.of_type("agent.speech")) > spoken_before,
        "one session, whichever modality answered (§1.4.1 item 3)",
    )


async def verify_barge_in(
    http: httpx.AsyncClient,
    base_url: str,
    settings: Settings,
    report: Report,
) -> None:
    """§2.1: the caller talks over the greeting, and the agent stops.

    Four things, and all four are needed before "barge-in works" means
    anything. That the browser was told (`agent.flush`); that the agent
    actually stopped with something left to say (`agent.speech` →
    `interrupted`, with a non-empty remainder); that the server recorded *why*
    it stopped (`barge_in.detected`); and that the sentence the caller cut in
    with became a turn rather than being thrown away with the audio.
    """
    sample_rate = int(settings.audio_sample_rate)
    greeting = settings.greeting_text
    greeting_pcm = await asyncio.to_thread(
        polly.synthesize_pcm,
        greeting,
        voice=settings.polly_voice,
        engine=settings.polly_engine,
        sample_rate=sample_rate,
        cache_dir=settings.polly_cache_dir,
    )
    greeting_ms = polly.duration_ms(greeting_pcm, sample_rate)
    report.fact("barge-in greeting", f'"{greeting}" ({greeting_ms} ms of playout)')
    report.check(
        "the greeting under test is long enough to be worth cutting into",
        greeting_ms >= MIN_BARGE_IN_GREETING_MS,
        f"{greeting_ms} ms, floor {MIN_BARGE_IN_GREETING_MS} ms",
    )

    mic_pcm = await asyncio.to_thread(
        polly.synthesize_pcm,
        BARGE_IN_LINE,
        voice=settings.polly_voice,
        engine=settings.polly_engine,
        sample_rate=sample_rate,
        cache_dir=settings.polly_cache_dir,
    )

    session = await livekit_peer.open_session(http, base_url)
    peer = livekit_peer.HeadlessParticipant(
        url=session["livekit_url"],
        token=session["token"],
        sample_rate=sample_rate,
        identity=session["identity"],
    )
    try:
        await peer.connect()
        joined = await peer.wait_for_agent(timeout=45.0)
        report.check(
            "the agent worker was dispatched into the barge-in room",
            joined,
            peer.agent_identity or "no participant arrived",
        )
        if not joined:
            return
        await peer.wait_for_agent_track(timeout=30.0)
        await peer.publish_microphone()

        began = await _next_speech(peer, "start", since=0, timeout=60.0)
        report.check(
            "the agent began the full-length greeting",
            began is not None,
            f"{began.get('chunks')} chunk(s)" if began else "no agent.speech start",
        )
        if began is None:
            return

        # Far enough in that there is real audio on the wire to throw away.
        await asyncio.sleep(BARGE_IN_AFTER_S)
        mark = len(peer.messages)
        await peer.speak(mic_pcm, lead_silence_ms=0)

        flush = await peer.wait_for_message("agent.flush", timeout=5.0, since=mark)
        report.check(
            "`agent.flush` reached the browser (§2.1, browser-side half)",
            flush is not None,
            f"reason={flush.get('reason')}, {flush.get('queued_ms')} ms of jitter "
            f"buffer discarded"
            if flush
            else "no agent.flush within 5 s of the caller speaking",
        )

        stopped = await _next_speech(
            peer, "interrupted", "end", since=mark, timeout=20.0
        )
        interrupted = bool(stopped and stopped.get("state") == "interrupted")
        played_ms = float((stopped or {}).get("played_ms") or 0.0)
        remainder = str((stopped or {}).get("remainder") or "")
        report.check(
            "the greeting stopped early, with words it never got to say",
            interrupted and played_ms < greeting_ms and bool(remainder.strip()),
            f"{played_ms:.0f} ms of {greeting_ms} ms played, "
            f'remainder "{remainder[:60]}"'
            if stopped
            else "the greeting neither ended nor was interrupted",
        )
        if interrupted:
            report.fact(
                "§2.1 barge-in",
                f"{played_ms:.0f}/{greeting_ms} ms spoken "
                f"({100.0 * played_ms / greeting_ms:.0f} %), "
                f"spoken prefix \"{str(stopped.get('spoken_prefix') or '')[:60]}\"",
            )

        # Past the longest §2.3 hangover, so the interrupting turn gets closed.
        await peer.hold_silence(3.0)

        events = await _trace_events(
            http, base_url, session, timeout=90.0, until="turn.reply"
        )
        detected = [e for e in events if e["type"] == "barge_in.detected"]
        report.check(
            "`barge_in.detected` is in the trace (§2.1, server-side half)",
            bool(detected),
            f"{len(detected)} event(s), {detected[-1].get('flushed_ms')} ms flushed, "
            f"{detected[-1].get('held_frames')} held frame(s) handed to the recogniser"
            if detected
            else "no barge_in.detected",
        )

        voice = [e for e in events if e["type"] == "turn.voice"]
        replies = [
            e for e in events if e["type"] == "turn.reply" and e.get("modality") == "voice"
        ]
        report.check(
            "the interrupting turn was dispatched, not discarded with the audio",
            bool(voice) and bool(replies),
            f'heard "{voice[-1].get("verbatim")}" → '
            f"{replies[-1].get('step_id') or replies[-1].get('taxonomy_id') or 'escalated'}"
            if voice and replies
            else f"{len(voice)} turn.voice, {len(replies)} voice turn.reply",
        )
        if voice:
            report.fact("barge-in heard", voice[-1].get("verbatim"))
        if replies:
            report.fact("barge-in reply", (replies[-1].get("text") or "")[:120])
    finally:
        await peer.close()


async def _trace_events(
    http: httpx.AsyncClient,
    base_url: str,
    session: dict[str, Any],
    *,
    timeout: float,
    until: str,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Poll the trace until `min_count` events of type `until` appear, or
    give up and return what there is."""
    deadline = time.time() + timeout
    events: list[dict[str, Any]] = []
    while time.time() < deadline:
        response = await http.get(
            f"{base_url}/api/trace/{session['room']}", params={"token": session["token"]}
        )
        response.raise_for_status()
        events = response.json()["events"]
        if sum(1 for e in events if e["type"] == until) >= min_count:
            return events
        await asyncio.sleep(0.5)
    return events


async def verify_trace(
    http: httpx.AsyncClient, base_url: str, session: dict[str, Any], report: Report
) -> None:
    response = await http.get(
        f"{base_url}/api/trace/{session['room']}", params={"token": session["token"]}
    )
    response.raise_for_status()
    body = response.json()
    types = {event["type"] for event in body["events"]}
    for name in ("agent.joined", "asr.started", "vad.speech_end", "endpoint.fired", "turn.voice"):
        report.check(f"trace recorded `{name}`", name in types)
    report.fact("trace file", body["summary"].get("trace_path"))
    report.fact("trace event types", ", ".join(sorted(types)))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def run(
    base_url: str, ws_url: str, settings: Settings, report: Report
) -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        health = (await http.get(f"{base_url}/healthz")).json()
        report.check("server answers /healthz", bool(health.get("ok")), base_url)
        report.check(
            "the process is running the livekit transport with its worker up",
            health.get("transport") == "livekit"
            and bool((health.get("livekit_worker") or {}).get("running")),
            json.dumps(health.get("livekit_worker"), sort_keys=True),
        )
        report.fact("health", json.dumps(health, sort_keys=True))

        session = await verify_mint(http, base_url, settings, report)
        peer = await verify_voice(session, settings, report)
        try:
            await verify_voice_turn(http, base_url, session, peer, report)
            await verify_typed_turn(ws_url, session, peer, report)
            await verify_trace(http, base_url, session, report)
        finally:
            await peer.close()


async def run_barge_in(base_url: str, settings: Settings, report: Report) -> None:
    """Check 7, on the second process. See the module docstring for why."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        health = (await http.get(f"{base_url}/healthz")).json()
        report.check(
            "the barge-in process is up on the livekit transport",
            bool(health.get("ok"))
            and bool((health.get("livekit_worker") or {}).get("running")),
            base_url,
        )
        await verify_barge_in(http, base_url, settings, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Phase 3 LiveKit voice pipeline.")
    parser.add_argument("--binary", default="", help=f"default: {livekit_dev.DEFAULT_BINARY}")
    parser.add_argument("--port", type=int, default=0, help="port for the API process")
    parser.add_argument("--livekit-port", type=int, default=0, help="port for livekit-server")
    parser.add_argument("--no-llm", action="store_true", help="run the core on its rule-based floor")
    parser.add_argument(
        "--no-barge-in",
        action="store_true",
        help="skip check 7 and its second process (it costs a full greeting's playout)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    report = Report()
    media: livekit_dev.DevServer | None = None
    api: BackgroundServer | None = None
    try:
        binary = livekit_dev.find_binary(args.binary or None)
        if binary is None:
            report.check(
                "livekit-server binary found",
                False,
                f"expected {livekit_dev.DEFAULT_BINARY} or on PATH",
            )
            raise SystemExit(_finish(report, args.json))
        version = livekit_dev.version(binary)
        report.check("livekit-server binary found", True, version)
        report.fact("media server", version)

        trace_dir = REPO_ROOT / "data" / "traces" / "phase3"
        log_path = trace_dir / "livekit-server.log"
        media = livekit_dev.start_dev_server(
            binary=binary, port=args.livekit_port or free_port(), log_path=log_path
        )
        report.check("livekit-server --dev is answering", media.responding(), media.ws_url)
        report.fact("media server url", media.ws_url)
        report.fact(
            "media server keys",
            f"{livekit_tokens.DEV_API_KEY}/{livekit_tokens.DEV_API_SECRET} — published, "
            "local loop only (see server/README.md)",
        )

        def settings_for(greeting: str, port: int) -> Settings:
            return dataclasses.replace(
                Settings.from_env(),
                port=port,
                transport="livekit",
                livekit_url=media.ws_url,
                livekit_api_key=livekit_tokens.DEV_API_KEY,
                livekit_api_secret=livekit_tokens.DEV_API_SECRET,
                livekit_keys_are_dev=True,
                greeting_text=greeting,
                use_llm=not args.no_llm,
                use_transcribe=True,
                trace_dir=trace_dir,
            )

        settings = settings_for(VERIFY_GREETING, args.port or free_port())
        api = BackgroundServer(settings).start()
        print(f"api on {settings.host}:{settings.port}, media on {media.ws_url}", flush=True)
        asyncio.run(run(api.base_url, api.ws_url, settings, report))

        # -- check 7, on its own process ---------------------------------
        # Stopped first, not alongside: `server/livekit_agent.py` holds the
        # worker's `AgentHost` in a module global, so a second API process
        # started while this one is up would take the first one's rooms.
        api.stop()
        api = None
        if not args.no_barge_in:
            barge = settings_for(DEFAULT_GREETING, free_port())
            api = BackgroundServer(barge).start()
            print(
                f"barge-in api on {barge.host}:{barge.port} "
                f"(full-length greeting, {len(DEFAULT_GREETING)} chars)",
                flush=True,
            )
            asyncio.run(run_barge_in(api.base_url, barge, report))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — a crash is a failed verification
        report.check("verification completed", False, f"{type(exc).__name__}: {exc}")
    finally:
        if api is not None:
            with contextlib.suppress(Exception):
                api.stop()
        if media is not None:
            with contextlib.suppress(Exception):
                media.stop()
    return _finish(report, args.json)


def _finish(report: Report, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": report.ok, "checks": report.checks, "facts": report.facts}, indent=2))
    else:
        print("\nPhase 3 LiveKit voice pipeline verification\n")
        print(report.render())
        print("\n" + ("ALL CHECKS PASSED" if report.ok else "FAILED") + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
