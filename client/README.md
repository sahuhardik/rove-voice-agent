# `client/` — Phase 2b web client

A React page that joins one room, speaks over WebRTC, types into the same turn
dispatcher, and shows what the agent thinks it is working on.

`docs/06` §1.4 asks for a specific thing and not a chat window: the caller can *see*
the diagnosis. So the transcript is one panel of four, beside the diagnostic state,
the current step, and the state of the link itself. The text field is not a fallback
for when voice fails — it is a first-class input for *"strings the voice channel
mangles — SSIDs, serial numbers, card markings, error text"* (§1.4).

The two planes are kept visibly apart because they fail apart. The **control socket**
(`WS /ws`) carries turns, state and the trace; the **peer connection** carries audio.
Losing the microphone does not lose the session, and the UI does not pretend
otherwise.

| file | what it holds |
| --- | --- |
| `src/api.js` | the four server surfaces, all relative to the page's own origin |
| `src/useSession.js` | the control socket, the snapshot replay, and token renewal at half the TTL |
| `src/webrtc.js` | `RTCPeerConnection`, the mic track, the data channel, `getStats()` every 2 s |
| `src/stats.js` | the browser's `getStats()` report reduced to RTT / jitter / loss |
| `src/App.jsx` | the page: one room, one caller, four panels |
| `src/components/` | `ConnectionBar`, `Transcript`, `Composer`, `StatePanel`, `StepPanel`, `EventLog`, `LevelMeter` |

## Running it

Two ways, and the first is the one that matters.

**Built, served by the Python process** — one build, one process, one port:

```bash
cd client
npm install
npm run build          # writes client/dist, which server/config.py already looks for
cd ..
.venv/bin/python -m server
```

The server binds **port 8080 on `0.0.0.0`** and serves `client/dist/index.html` at
`/`. Open **`http://<host>:8080/`** — but read the secure-context note below first.

**Dev server**, for working on the page itself:

```bash
cd client && npm run dev        # http://<host>:5173/
```

Vite listens on `0.0.0.0:5173` and proxies `/api`, `/healthz` and `/ws` to
`127.0.0.1:8080`, so the Python process still has to be running. The build and the
dev server talk to exactly the same backend.

### The microphone needs a secure context

`getUserMedia` is only available on **HTTPS or `localhost`**. `http://<some-ip>:8080/`
will load the page, mint a token, open the control socket and let you type — and the
browser will refuse the microphone, with "no secure context" in the connection bar.

Three ways round it, in order of how little they cost:

1. **SSH tunnel**, so the browser sees `localhost`:
   ```bash
   ssh -L 8080:127.0.0.1:8080 <user>@<host>
   # then open http://localhost:8080/
   ```
2. **TLS on the server**: set `ROVE_TLS_CERT` and `ROVE_TLS_KEY`, and open
   `https://<host>:8080/`. Signalling then goes out as `wss://<host>/lk` through the
   in-process relay described in "Speaking over HTTPS" below. For a self-signed
   testing certificate use `scripts/serve_https_testing.sh`.
3. Run both the server and the browser on the same machine.

And if the browser is not on the server's host, set `ROVE_PUBLIC_IP` (or `=auto` on
EC2) so the ICE candidates carry an address the browser can actually reach — see
`server/README.md`.

## Browser verification — NOT YET DONE

**Neither of the two checks below has been run from a real browser.** What has been
verified is a headless `aiortc` peer handshake (offer → answer → connected, with audio
frames counted server-side) and a typed turn through `/ws` against the real core.
Both are in `server/test_server.py` and both are on disk in
`data/traces/phase2b/room-ALLtsO8jjE6l-f5d770f3.jsonl`.

A headless peer cannot stand in for these two. It has no `getUserMedia`, no acoustic
echo cancellation, no browser jitter buffer and no `RTCPeerConnection.getStats()` —
and those are exactly what the two checks are about. Treat the list below as a
procedure to run, not as a result.

### 1. The 10-minute stable session

`docs/06` §9.1 wants a duplex session that holds for ten minutes. The pipeline is
already configured for it: `idle_timeout_secs=None` in `server/pipeline.py`, because
Pipecat's default would cancel a quiet session at five minutes and a session with
nobody speaking is not an idle session.

1. Start the server: `.venv/bin/python -m server` (binds `0.0.0.0:8080`).
2. Open **`http://localhost:8080/`** through the SSH tunnel above, or
   `https://<host>:8080/` with TLS configured.
3. Click **Join room**. Grant the microphone when the browser asks.
4. Confirm within a few seconds: the connection bar shows `connected`, the level
   meter moves when you speak, and you hear the Polly greeting. (The `<audio>`
   element is unmuted and autoplaying; clicking **Join room** is the user gesture
   that lets a browser play it. If it stays silent, check the tab is not muted and
   that `greeting.played` — not `greeting.failed` — is in the trace.)
5. **Leave it open for ten minutes.** Speak every minute or so, rather than sitting
   silent, so the VAD and the return path are both exercised.
6. Watch the connection bar for the whole ten minutes. The `token` countdown should
   reset roughly every 2.5 minutes — that is renewal at half the 300 s TTL — and the
   peer-connection state should never leave `connected`.
7. At ten minutes, type a turn into the composer and confirm the agent still answers
   and the state panel still updates.
8. Stop, then read the trace for the room:
   ```bash
   .venv/bin/python - <<'EOF'
   import json, glob
   path = sorted(glob.glob('data/traces/phase2b/*.jsonl'))[-1]
   for line in open(path):
       e = json.loads(line)
       if e['type'] in ('webrtc.connected', 'webrtc.disconnected', 'session.renewed',
                        'net.client_stats', 'net.server_stats', 'media.stopped'):
           print(e['elapsed_s'], e['type'], e)
   EOF
   ```

   **Passes if**: `webrtc.disconnected` carries `held_for_s >= 600`, there is no
   `webrtc.disconnected`/`webrtc.connected` pair in between, several
   `session.renewed` events appear, and `net.client_stats` records are present
   throughout — the browser samples `getStats()` every 2 s and sends it up the
   control socket.

### 2. The drop-and-rejoin

§1.4.2: *"reconnection is expected, not exceptional"*, and *"a dropped connection
costs the in-flight turn and nothing else"*. `DiagnosticState` lives on the server, so
a re-join replays the snapshot and loses nothing.

1. Join as above and **have a real conversation first** — type or speak at least two
   turns, so the state panel has a device, a category and a step in it. Note what the
   step panel says.
2. Drop the media. Either is a valid test, and the second is the more honest one:
   - click **Drop audio** — closes the peer connection and leaves the room open; or
   - turn off Wi-Fi / pull the network for ~15 seconds.
3. While the media is down, confirm the control plane survived: the transcript is
   still there, the state panel still shows the same step, and **typing a turn still
   works**. This is the whole point of keeping the two planes apart.
4. Click **Rejoin audio** (after restoring the network, if you pulled it). This posts
   a fresh offer with `restart_pc`.
5. Confirm the peer connection returns to `connected`, the level meter moves again,
   and the transcript and state panel still hold everything from step 1 — no reset,
   no repeated greeting of a new room.
6. Reload the whole page and click **Join room** — this mints a *new* room, which is
   the correct behaviour and not the same test. The re-join in step 4 is the one that
   must preserve state.
7. Check the trace: a second `webrtc.offer` with `restart_pc: true`, a second
   `webrtc.connected`, `client.media.dropped_by_user` and `client.media.rejoined`,
   and the `turn.user`/`turn.reply` pair from step 3 sitting between the two
   connections.

   **Passes if**: the state after re-join is the state from before the drop, and the
   turn taken while the media was down is in the transcript.

## `docs/06` §2.2 lines 1 and 9

**Both are UNMEASURED.**

Line 1 is *browser capture → WebRTC uplink + jitter buffer* (budget: 15 ms best /
25 ms target median / 70 ms p95) and line 9 is *WebRTC downlink + browser playout*
(15 / 30 / 80 ms). They are the only two lines of the §2.2 budget the browser
transport changes, and both are properties of a **browser** leg.

No browser has been on this link yet, so there are no numbers for either. Concretely:
`net.client_stats` — the record `App.jsx` writes every 2 s from
`RTCPeerConnection.getStats()` — **does not appear in any trace file on disk**. The
only network samples in the traces are `net.server_stats` from the server's `aiortc`
RTCP view of a loopback session with the headless peer: RTT 0.467 / 0.453 / 2.362 ms,
zero packet loss, in `data/traces/phase2b/room-ALLtsO8jjE6l-f5d770f3.jsonl`. Two
processes on one host are not a laptop on domestic broadband, and the `jitter_ms`
figures in those same records are implausible on their face, so jitter is unmeasured
from either end rather than quoted.

Running either browser check above produces the missing data, because both ends then
report the same link and the trace holds them side by side. One unit trap is already
handled and worth knowing about: the browser reports `jitter` in **seconds** (W3C
webrtc-stats) while `aiortc` reports it in **RTP clock units**, so the two are
converted differently before they are compared — see `stats.js` and `OPUS_CLOCK_HZ`
in `server/pipeline.py`. Getting that wrong would not produce a wrong number, it
would produce a wrong comparison.

## Speaking over HTTPS (Milestone: browser speaking support)

An https page cannot open the `ws://127.0.0.1:7880` URL the mint used to hand out: the
browser blocks it as mixed content. `livekit-server` does not terminate TLS on its
signalling port and no reverse proxy is installed, so this process relays it.

- `server/livekit_relay.py` serves `WS /lk/{path}` and `GET /lk/{path}` and forwards
  both to `settings.livekit_url` (query string and `Authorization` header included;
  the current LiveKit SDK carries the join token in that header). Frames are not
  read or changed, and the media server still verifies the token itself.
- `Settings.livekit_public_url(scheme, host)` returns `wss://{host}/lk` when the
  request arrived over https, and `livekit_url` unchanged over http or when the
  `Host` header is not a bare `name[:port]`. `/api/session` and the token renewal use it.
- Only `rtc` paths are relayed (socket and `validate` probe); the rest of the media
  server's HTTP surface is 404 here. There is no Origin check or connection cap: the
  media server's token check is the gate. The https scheme is read from the request
  as uvicorn sees it, so this is for TLS terminated by this process, not behind a
  proxy that strips it.
- Only signalling is relayed. ICE and the UDP media path go straight to the media
  server and are unchanged.

### Testing certificate (TESTING ONLY)

`scripts/serve_https_testing.sh` generates a throwaway CA and a 30-day leaf
certificate (SAN `localhost`, `127.0.0.1`, plus any host or IP you pass as an
argument) into `server/testing-tls/` and starts the server on `https://127.0.0.1:8443/`
(`PORT`, `HOST` override). The files are named `TESTING-ONLY-*`, are gitignored, and
must not be used anywhere real. Browsers will warn until you trust
`TESTING-ONLY-ca.pem`. The leaf must be CA:FALSE: a self-signed certificate that is
its own CA is rejected by the LiveKit SDK's TLS stack (`CaUsedAsEndEntity`).

### Headless check

```bash
scripts/serve_https_testing.sh &
SSL_CERT_FILE=server/testing-tls/TESTING-ONLY-ca.pem \
  .venv/bin/python -m server.verify_wss https://127.0.0.1:8443
```

### Measured results

| Check | Result |
|---|---|
| `.meter-fill` / `.meter-speaking` contrast (Part A fix) | 1.23:1 to 6.09:1 and 1.30:1 to 5.48:1, as measured by the earlier run; not re-measured here |
| `npm run build` | completes; only the existing bundle-size advisory (753 kB JS) |
| Built output vs source | all 60 user-visible strings in the JSX (panel headings, labels, titles, placeholder) found in `dist`, case-insensitive |
| `python -m unittest server.test_livekit_relay` | 8 relay tests pass (URL selection, binary and text frames, query, `Authorization` on socket and GET, non-signalling paths refused, 502 when the media server is down) |
| `python -m unittest server.test_server` | 7 tests pass |
| `/api/session` over https | `livekit_url = wss://127.0.0.1:8443/lk` |
| `server.verify_wss` against the already-running `livekit-server --dev` on :7880 | joined the room over wss in 0.054 s; agent worker joined; agent voice track subscribed |
| HTTPS page returns 200 | **not confirmed**: `curl` was denied by the permission layer in this run. Run `curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/` |

Not covered: a real browser (`getUserMedia`, echo cancellation, `getStats()`), which is
still the manual list under "Browser verification". The headless peer proves the secure
signalling path and room join, not a speaking human.
