"""Phase 2b: the web client's server side (`docs/06` §9.1).

One Python process, nothing to operate — the shape `docs/06` §8.1.1 picks for
the spike and `docs/07` D-02 records as the fallback. It holds four things:

* **the token mint** (`server/tokens.py`, `docs/06` §1.4.2) — short-lived,
  single-room, single-identity. The browser never holds a long-lived credential
  and never holds an AWS one;
* **a Pipecat SmallWebRTC transport** (`server/pipeline.py`) — a real peer
  connection inside this process, carrying real microphone audio in and real
  Polly audio out, with Silero VAD v5 running in-process on the inbound frames;
* **the typed turn** (`server/core_bridge.py`) — the click-or-type path of
  §1.4 wired to the existing text diagnostic core in `agent/`. It is wired, not
  reimplemented: one `agent.core.diagnose` call per typed turn;
* **the trace** (`server/trace.py`) — session events plus RTT, jitter and loss
  from both ends of the peer connection.

What it deliberately is **not**: the Phase 3 pipeline. There is no Transcribe
streaming, no incremental synthesis, no barge-in and no endpointing beyond the
VAD's own speech segments (`docs/06` §9.1, §9.2).
"""
