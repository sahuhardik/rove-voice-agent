# `server/` — Phase 2b web server, SmallWebRTC spike, and Phase 4 scaffolding

One FastAPI process. It mints the join tokens, holds the WebRTC peer connection, runs
Silero VAD v5 over the inbound audio, speaks a Polly greeting back down the same
connection, and dispatches typed turns into the existing diagnostic core. `docs/06`
§8.1.1 picks this shape for the spike and says why: *"SmallWebRTC gets a real browser
conversation running in a single Python process with nothing to operate."*

Milestone 7.1 adds the Phase 4 scaffolding to the same process: the support console's
server half, the §5.2 handoff panel, the §5.3 same-session join, §6.3 consent, and the
pilot-transcript write path. Still one process and still one thing to run.

Nothing in `agent/` or `eval/` is modified or duplicated here. `core_bridge.py` is a
dispatcher: one typed string in, one call to `agent.core.diagnose`, one projection out.

| file | what it holds |
| --- | --- |
| `__main__.py` | `python -m server` — the banner and the uvicorn call |
| `config.py` | every setting, from the environment, with working defaults |
| `tokens.py` | the HMAC-SHA256 mint: two scopes, `join:room` and `observe:room` (`docs/06` §1.4.2, §5.3) |
| `app.py` | the caller's four surfaces — the mint, WebRTC signalling, the trace, `WS /ws` — and the console mount |
| `pipeline.py` | the media path: `transport.input() → VADProcessor → SpeechReporter → transport.output()` |
| `core_bridge.py` | `DiagnosticState` per room, the typed-turn dispatcher, the agent-mode flip, the UI projections |
| `support.py` | `/api/support/*` and `WS /ws/support`: the observer mint, the §5.3 join, collection |
| `handoff.py` | the §5.2 panel, rendered from `DiagnosticState` on every request |
| `consent.py` | §6.3: display and storage as two decisions, and nothing stored until the storage one exists |
| `transcripts.py` | the pilot corpus write path — Postgres, consent-gated, redacted (`docs/07` D-12) |
| `polly.py` | the greeting: one Polly Neural call, cached on disk |
| `sdp.py` | ICE host-candidate rewriting for a host behind 1:1 NAT |
| `trace.py` | the JSONL session trace under `data/traces/phase2b/` |
| `headless_peer.py` | a browser-shaped `aiortc` peer with no browser in it |
| `verify.py` | `python -m server.verify` — starts a server, checks it end to end, exits non-zero on any failure |
| `test_server.py` | 7 stdlib unittest cases: the mint, the handshake, the typed turn |
| `test_support.py` | 35 stdlib unittest cases: observer scoping, consent gating, the join flip, the console |

## Running it

```bash
.venv/bin/python -m server
```

That is the whole operation. It binds **port 8080 on `0.0.0.0`** — both parts matter:
one documented port so there is a single thing to open, and `0.0.0.0` rather than
`127.0.0.1` so a browser that is not on this host can reach the session at all.

```
  listening on   0.0.0.0:8080  (http)
  open           http://<this-host>:8080/
```

Serve the built page from the same process (`client/dist` is mounted at `/`, so one
build and one process is the entire deployment):

```bash
cd client && npm install && npm run build   # writes client/dist
cd .. && node support/build.mjs             # writes support/dist
.venv/bin/python -m server                  # http://<this-host>:8080/
```

Two pages from one process: the caller's at `/` and the support console at `/support`
(`support/README.md`). Without a build either one returns 503 with the command to run.
The API still works.

### Settings

All optional. All read once at startup.

| variable | default | what it does |
| --- | --- | --- |
| `ROVE_WEB_PORT` | `8080` | the one documented port |
| `ROVE_WEB_HOST` | `0.0.0.0` | the bind address |
| `ROVE_TOKEN_SECRET` | *(generated per process)* | the token signing secret |
| `ROVE_TOKEN_TTL_SECONDS` | `300` | join-token lifetime, capped at 900 by `tokens.py` |
| `ROVE_SUPPORT_KEY` | *(generated per process, printed in the banner)* | the one gate on minting a support observer token |
| `ROVE_OBSERVER_TTL_SECONDS` | `300` | observer-token lifetime, capped at 900 by the same ceiling |
| `ROVE_PG_DSN` | `postgresql://ubuntu@/rove?host=/var/run/postgresql` | the pilot corpus, shared with `agent/store.py` |
| `ROVE_PUBLIC_IP` | *(none)* | address to advertise in ICE candidates; `auto` asks EC2 IMDS |
| `ROVE_ICE_SERVERS` | *(none)* | comma-separated STUN/TURN URLs |
| `ROVE_USE_LLM` | `1` | `0` runs the core on its rule-based floor, with no Bedrock call |
| `ROVE_TLS_CERT`, `ROVE_TLS_KEY` | *(none)* | serve HTTPS, which the browser needs for a microphone |
| `ROVE_TRACE_DIR` | `data/traces/phase2b` | where the JSONL session traces land |

**`ROVE_TOKEN_SECRET` unset is fine for a spike and wrong for anything else.** The
process generates one at startup, so every restart invalidates every token in flight,
and two processes behind a load balancer would not accept each other's tokens. The
banner says so when it happens.

### What has to be reachable

- **TCP 8080** — the page, `POST /api/session`, `POST /api/offer`, `POST /api/ice`
  and `WS /ws`. This is signalling and control only.
- **UDP, ephemeral ports** — the media itself. It does not go over 8080. This is the
  part that surprises people: opening 8080 and nothing else gets you a page that
  signals correctly and never connects.
- A host behind **1:1 NAT** — which is every EC2 instance with a public address —
  gathers ICE candidates holding its *private* IP, and a browser elsewhere cannot
  reach those. Set `ROVE_PUBLIC_IP` (or `=auto`) and `sdp.py` rewrites them.

## The join token (`docs/06` §1.4.2)

The browser never holds a long-lived credential and never holds an AWS credential at
all. `POST /api/session` returns a **short-lived, single-room, single-identity** HMAC
token; Polly and Bedrock are called from this process, with this process's role.

Each of the three properties is enforced by construction, not by convention:

- **Short-lived.** Five minutes by default, 15 minutes maximum, enforced at the mint.
  The page renews at half the TTL while it is open, so a session can outlive its own
  token but the credential on the wire never is valid for more than one TTL. Renewal
  needs an *unexpired* token — no grace window, no separate refresh credential.
- **Single-room.** `verify()` requires the caller to name the room it is verifying
  for. There is no way to ask "is this token valid?" in the abstract.
- **Single-identity.** One signed `identity` claim, checked the same way.

It is a signed payload rather than a JWT: no algorithm field to confuse, no `none`
algorithm to strip, no library to keep current.

### The fourth property: single-scope (`docs/06` §5.3)

Escalation admits a *second participant* to the room the caller is already in, and that
participant is not the caller. So the mint issues two disjoint scopes:

| scope | identity | reaches |
| --- | --- | --- |
| `join:room` | `caller-…` | signalling, media, `WS /ws`, the trace. The only thing the browser ever holds |
| `observe:room` | `observer-…` | `/api/support/*` and `WS /ws/support`. Never SDP, never a caller turn |

`verify()` takes the scope as a parameter and **defaults to the caller's**. That default
is the security property: every surface written before the console keeps asking exactly
the question it was asking — *"is this the caller?"* — so an observer token cannot reach
one by being forgotten about. The observer path names its scope out loud. The mint also
pairs scope with identity prefix, so a signed token cannot disagree with itself.

Minting an observer token needs `ROVE_SUPPORT_KEY`. A room id is not a secret — it
travels in URLs and in the trace — so possession of one must not be enough to watch the
session it names.

## Consent, and what is stored (`docs/06` §6.3)

Two decisions, never collapsed into one:

- **Display** — may the live transcript be rendered? Refused only on an explicit decline,
  because rendering a caller's own words into their own browser retains nothing.
- **Storage** — may anything be written anywhere? Permitted on exactly one value,
  `granted`. `undecided` is not a third kind of yes and no operator default turns it into
  one.

A decision requires a prior disclosure (§6.3 puts it in `GREET`, *"spoken and shown"*),
and `transcripts.collect` asks the storage question **before it opens a connection** — an
un-consented session does not reach the network, let alone the disk. The same rule is
stated a second time in the schema as `CHECK (consent_storage = 'granted')`, because a
filter bug is a plausible event and a rejected `INSERT` is not. Identifiers are redacted
from the corpus by default. No audio is written by this milestone under any answer.

## Verifying it

Three tools, and they do different jobs.

```bash
.venv/bin/python -m unittest server.test_server -v    # 7 cases, hermetic, ~5 s
.venv/bin/python -m unittest server.test_support -v   # 35 cases, Phase 4 scaffolding
.venv/bin/python -m server.verify                     # end to end, needs AWS for Polly
.venv/bin/python -m server.verify --url http://host:8080 --secret <s>
```

`test_support.py` builds the console with `node support/build.mjs`, runs
`node support/selftest.mjs` over the result — every module parses, every element id
`main.js` reaches for exists in `index.html`, and every panel escapes what it renders —
then starts a server and asserts four properties: the observer token is refused on every caller surface and the
caller token on every support surface (both sockets included); nothing is stored until a
storage decision exists, and the refusal is the consent one rather than the database one;
the §5.3 join flips the agent so the caller's next turn is transcribed and never reaches
`agent.core.diagnose`; and `/support` and its assets are served. It needs Postgres only
for the end-to-end collection case, which skips without it — the *gate* is asserted either
way, because the gate must never depend on the database being there.

`test_server.py` is hermetic — no AWS, no Bedrock, no network beyond loopback. It
starts a server on a free port and asserts three things:

1. **The mint is scoped.** A token is refused once its TTL has elapsed, and a token
   minted for one room is refused on another — asserted both against `tokens.py`
   directly and over HTTP against the running server, because a property that holds in
   the library and not at the endpoint is not a property this system has.
2. **The handshake is real.** A headless `aiortc` peer offers, the server answers with
   a real SDP answer, ICE and DTLS come up, and the server reports frames it received
   back over the WebRTC data channel. No mock transport.
3. **A typed turn reaches the core.** `user.text` over `/ws` comes back as an agent
   transcript line carrying a step id out of `eval.ontology` and an FSM state out of
   `agent.state` — neither of which `server/` has a copy of.

`verify.py` is the fuller pass and needs AWS: it synthesises the headless peer's
microphone with Polly so that **Silero VAD v5** is exercised against real speech
rather than a tone, and it checks the Polly greeting arrives back on the return path.
A VAD that fires on a sine wave has told you nothing, which is why the hermetic test
deliberately does not claim to test the VAD.

The whole suite:

```bash
.venv/bin/python -m unittest eval.test_harness ingest.test_ingest agent.test_core \
  agent.test_graph agent.test_retrieval eval.test_harness_b eval.test_grounding \
  server.test_server server.test_support
```

303 cases at Milestone 7.1.

## What is verified, and what is not

**Verified.** The headless `aiortc` handshake (offer → answer → connected, audio
frames counted server-side) and the typed turn through `/ws` against the real core.
Both run in `test_server.py` and both are in the trace at
`data/traces/phase2b/room-ALLtsO8jjE6l-f5d770f3.jsonl`: `webrtc.offer` →
`webrtc.answer` → `webrtc.connected` at 0.186 s from offer, `greeting.played`
(Polly Amy/neural, 7,580 ms, 242,560 bytes), two `vad.speech_end` segments of
3,440 ms and 3,080 ms, `turn.user` → `turn.reply` (`STEP.OBSERVE.CHECK_UPDATE_INDICATOR`,
`FW-01`, 2,055.7 ms), 766 inbound frames over 15.32 s of audio, and two
`auth.rejected` events for a bad signature and an expired token.

**Not verified.** Nothing here has been opened in a real browser yet. In particular
the two browser checks in `client/README.md` — **the 10-minute stable session** and
**the drop-and-rejoin** — have **not** been run. They need `getUserMedia`, a browser
jitter buffer and `RTCPeerConnection.getStats()`, and a headless peer has none of
those. Do not read the headless result as covering them.

## `docs/06` §2.2 lines 1 and 9

**Both are UNMEASURED.**

Line 1 is *browser capture → WebRTC uplink + jitter buffer* (budget: 15 / 25 / 70 ms)
and line 9 is *WebRTC downlink + browser playout* (15 / 30 / 80 ms). Both are
properties of a browser leg, and no browser has been on this link. The field that
would carry the browser's own view — `net.client_stats`, written when the page sends
`RTCPeerConnection.getStats()` up the control socket — does **not appear in any trace
file on disk**.

The only network numbers in the traces come from the server's `aiortc` RTCP view of a
**loopback** session with the headless peer, which is a different measurement of a
different link:

| source | samples | value |
| --- | --- | --- |
| `net.server_stats`, `room-ALLtsO8jjE6l-f5d770f3.jsonl`, `source: aiortc` | 3, at 5 s intervals | `rtt_ms` 0.467, 0.453, 2.362; `packets_lost` 0; 748 packets sent |

Sub-millisecond RTT between two processes on one host is not evidence about a laptop
on domestic broadband. The `jitter_ms` values in the same records (16,000 / 17,000 /
43,000) are not usable either — `aiortc` reports jitter in RTP timestamp units and
these converted figures are implausible on their face, so jitter is **UNMEASURED**
from either end rather than quoted. Treat the RTT figures as proof the stats path
works, not as a measurement of lines 1 or 9.

Getting real numbers for those two lines needs a browser, and `client/README.md` gives
the steps.


## Phase 3 — LiveKit promotion (Milestone 6.1)

The transport is now LiveKit, per `docs/06` §8 / `docs/07` D-02. The browser
joins a **room** (`client/src/livekit.js`) with the credential `POST
/api/session` mints (`server/livekit_tokens.py`: HS256, one room, one
identity, 300 s); the agent is another participant in the same room
(`server/livekit_agent.py`), and §5.3's human support seat is one more
`mint()` call with a different identity. What rides on the room is exactly
what rode on the peer connection: mic up as one Opus track (20 ms frames),
the agent's voice track down, and the `rove` data topic carrying audio
levels, Silero speech segments, ASR partials and the §2.3 endpoint
decisions. Typed turns, diagnostic state and the transcript are still on
the control socket in `useSession.js`. The Pipecat SmallWebRTC server is
kept as the documented fallback (`server/pipeline.py`, `client/src/webrtc.js`)
— D-02 keeps it rather than deleting it.

New files: `server/endpointing.py` (context-dependent hangover per §2.3),
`server/transcribe.py` (streaming Transcribe with the `rove-support-en-us`
vocabulary for biasing), `server/livekit_tokens.py`, `server/livekit_agent.py`
(the agent worker), `server/livekit_dev.py` (dev media-server launcher),
`server/livekit_peer.py` (headless stand-in for the browser),
`server/verify_livekit.py`, `client/src/livekit.js`. The hermetic tests
(token mint scope, cross-room and expired-token refusal, headless-peer
handshake, typed turn) live in `server/test_server.py` and need neither
AWS nor the media-server binary.

### Running it

```bash
~/livekit-server/livekit-server --dev   # media server, loopback, dev keys
.venv/bin/python -m server              # app server, transport=livekit
```

The media server binary is LiveKit 1.13.11, at `~/livekit-server/`. The
`--dev` keys (`devkey`/`secret`) are published and local-loop only — that is
the dev-vs-production decision: **dev mode is for this spike; production
mints its own API key/secret and runs the media server with them, never the
dev pair.** The app server's health endpoint reports
`livekit_keys_are_dev: true` while the dev pair is in use, so the mistake
is visible rather than silent.

### Verification

`.venv/bin/python -m server.verify_livekit` — starts a real media server,
joins a real room with a real credential, speaks real synthesised speech
into it, and checks the whole path. `--no-llm` runs the core on its
rule-based floor. Verified 2026-11-08 (Muse's own run, `--no-llm`):
**all checks passed**, including token scope (roomJoin/publish/subscribe/data
and nothing more, cross-room and expired tokens refused at the endpoint),
both participants in the room, greeting audible (365 frames), Silero VAD v5
segmenting 3,936 ms of speech, Transcribe returning a transcript, the
endpointer closing the turn at 608 ms of silence against a 600 ms hangover
(open_symptom), the voice turn reaching the core
(`STEP.SAFETY.HOLD_DO_NOT_UNPLUG`), the reply spoken back into the room,
and the typed turn answered. Two honest notes from that run: Transcribe
heard "My R2-4K stopped recording" as **"My rover 24K stopped recording"**
— the §3.4 alias candidates caught it (`ROVE?`, confidence 0.4), and this
is exactly the mis-hearing Harness C's corruption pass is for, not a reason
to trust the transcript; and the verifier itself had a race (it stopped
collecting trace events at `turn.reply`, before the reply's `tts.played`
landed) which was fixed by waiting for the second `tts.played` event.
`server/verify.py` still verifies the Pipecat fallback. 268 tests pass.


## Phase 3 — Milestone 6.2: barge-in, incremental Polly, speculative prefetch

### Barge-in (§2.1)

When the caller starts speaking while the agent is speaking, the agent stops
within one frame: VAD speech-start during playback calls
`RoomVoiceAgent._barge_in`, which sets the interrupt (the push loop checks it
per frame), empties the synthesis queue, and sends `agent.flush` (reason
`barge-in`) so the browser empties its jitter buffer. The caller's frames
captured while the agent was talking are drained into the recogniser first,
so the turn starts where the caller started it. The interrupted turn is not
lost: `_finish_utterance` records it via `core_bridge.note_interruption`
(`step_id`, `sub_step_index`, spoken prefix, un-spoken remainder) into
`DiagnosticState.notes`, and the next turn's hangover is chosen from the
spoken prefix, not the whole reply. The reply stays in the transcript as
composed — a transcript that quietly dropped it would disagree with the
ledger and the §5.2 handoff.

Verified live by Muse (not by the stock verifier, which does not test this):
a headless peer spoke the 4.1 s fixture over a ~8 s greeting. The `agent.flush`
arrived with 1,026.1 ms of queued audio discarded, the greeting stopped after
0.28 s of audible audio, `barge_in.detected` is in the trace, and the
interrupting utterance became a turn (`turn.voice`). Two caveats from that
probe: the trace event reports `probability: 0.0` (the VAD speech-start path
does not carry a scored probability — the detection fired, the number is
uninformative), and the Silero model load blocks the agent loop for ~132 ms
at startup (an `onnxruntime` warning in the log; transient, at load, not
during a turn).

### Incremental Polly synthesis (§2.2 line 7)

`server/polly.py` cuts a reply into clauses (`split_clauses`) and the first
clause is pushed into the room the moment Polly returns it, with the next
synthesised behind it. `synthesis_ms` on a `tts.played` event is now the wait
for the **first clause** — the number line 7 budgets at 120 ms median — and
`synthesis_total_ms` is what the whole reply cost. Measured on the verify
fixture (140-char reply, 2 chunks): first clause 167.7 ms, whole reply
344.1 ms — first audio ~176 ms before the whole reply finished synthesising,
and the first-clause wait no longer scales with reply length. Honest
comparison note: the 6.1 run's 3.7 ms was a Polly-cache hit on a repeated
reply, not a baseline, so there is no clean before/after on the same uncached
reply; and this one sample (167.7 ms) sits above the 120 ms median budget —
one sample, not a verdict, and 6.3's instrumentation is what measures the
median.

### Speculative prefetch (§2.1, §2.2 line 5)

`server/prefetch.py`: on an ASR partial at ~60% confidence carrying a
category-bearing phrase, run the metadata-filtered retrieval for the 2–3
most likely taxonomy IDs and warm the LLM prompt prefix. It never writes
anything — a prefetch produces a `RetrievalResult` and a `Classification`
into a cache, touches no `DiagnosticState`, advances no FSM, enters no
ledger. The turn still runs the real retrieval and classification
unconditionally through `agent.core.diagnose`; a hit means those calls find
their work already done (the Titan embedding in `agent/store.py`'s
`_query_cache`, the Nova Micro classification in `MemoLLM`). A wrong guess
costs tokens and never a decision, so M10 stays measurable. Discarded
silently when the final transcript disagrees.

Measured on the one verify utterance: 4 partials fired, 1 hit (hit rate
0.25 by the fired count). That is one utterance, not a rate — the prefetch
hit rate across the Harness B fixture utterances, which the 6.2 brief asked
for, was **not measured** (no such eval exists yet) and is open for 6.3.
`prefetch.Stats` (`hit_rate`, `saved_ms`, `wasted_ms`) is the instrument for
it.

### Verification status

309 tests pass; `server.verify_livekit --no-llm` ALL CHECKS PASSED;
`server.verify` (Pipecat fallback) ALL CHECKS PASSED; client builds clean.
Open gap, stated plainly: **no unit tests cover the three features** — they
are verified by the live probes above, not by the suite. The barge-in probe
itself lives nowhere in the repo (it was run transiently by Muse); if 6.3
does not fold it into `verify_livekit`, the feature has no standing test.

## Phase 3 — Milestone 6.3: latency instrumentation and Harness C

`server/latency.py` records the §2.2 9-component breakdown on every turn
(`latency.turn` in the trace: lines 1–9 with their budgets); `server/ladder.py`
is the §2.4 degradation ladder — tiers 0–3 keyed off the p95 over a 20-turn
window, releasing only once the p95 has sat `RECOVERY_MARGIN_MS` under the
trigger for `RECOVERY_TURNS` consecutive turns. Lines 1 and 9 are
**UNMEASURED** in every trace so far: they need a real browser leg, and a
loopback peer is a different link — the instrument records `UNMEASURED`
rather than quoting loopback numbers as if they were browser numbers.

### What the first measured turns say (Harness C, 2026-11-08, 24 turns)

Per-line medians over the full 47-turn set: line 2 (endpoint hangover)
608 ms, line 6 (LLM turn reasoning) 1342 ms, line 7 (TTS first clause)
147 ms, line 5 127 ms, line 4 17 ms, line 3 0 ms, line 8 0 ms. M7 median
2273 ms — against the §2.2 target median of ~860 ms and the 1.2 s line, the
pipeline is roughly twice too slow at the median, and the two lines that
matter are the endpoint hangover and the LLM turn, ~86% of a median turn
between them. The full verdict, the corruption pass (7/7), M10 (43/46), the
prefetch hit rate (0.0714 per fire) and the ladder replay are written up in
`eval/README.md` under Milestone 6.3; this section records the server half
only.

Two measurement notes, so nobody re-learns them the hard way. First,
`peer_m7_ms` in the Harness C results is **not** M7: the harness records
`push_ended` after three seconds of post-fixture silence, so the first audible
frame after that mark is mid-reply and the number comes out around 524 ms
with `loopback_ms` near −1800 ms on every case. The server's `m7_server_ms`
is the M7. Second, the ladder's recovery is demonstrated by replay
(`eval/run_ladder.py`: Tier 0→3 on a 3504 ms p95, then 3→2→1→0 across 21
calm turns), not in a live room — a 20-turn p95 window cannot recover inside
a Harness C case that runs one or two turns, so the replay drives the real
`LatencyBook` and the real `Ladder` with real readings and says so.

Barge-in is a standing check now: `server/verify_livekit.py` check 7 speaks
over a 7580 ms greeting and asserts `agent.flush` (1005.1 ms of jitter buffer
discarded in the check run), the greeting stopping early, `barge_in.detected`
in the trace, and the interrupting turn dispatched. The transient probe from
6.2 that used to be the only evidence for barge-in is no longer needed.
