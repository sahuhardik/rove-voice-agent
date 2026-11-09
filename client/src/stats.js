// The browser's own view of the link (`docs/06` §9.1 Phase 2b exit:
// "...and reports RTT/jitter/loss into the trace").
//
// One unit trap worth naming, because the trace puts the two ends side by
// side: **the browser reports `jitter` in seconds** (W3C webrtc-stats), while
// `aiortc` on the server reports it as an integer in RTP clock units. Both are
// converted to milliseconds, each in its own way — see `OPUS_CLOCK_HZ` in
// `server/pipeline.py`. `roundTripTime` is seconds on both sides.
//
// Loss is reported as cumulative counters plus a percentage of what was sent,
// not as a rate over the sampling window: `packetsLost` only climbs, so a
// difference between two samples is noisier than the total and says less.

export function summariseStats(report) {
  let inbound = null
  let remoteInbound = null
  let pair = null
  let outbound = null

  report.forEach((entry) => {
    if (entry.type === 'inbound-rtp' && entry.kind === 'audio') inbound = entry
    else if (entry.type === 'remote-inbound-rtp' && entry.kind === 'audio') remoteInbound = entry
    else if (entry.type === 'outbound-rtp' && entry.kind === 'audio') outbound = entry
    else if (entry.type === 'candidate-pair' && entry.state === 'succeeded') {
      // Chrome marks the chosen pair `nominated`; Firefox marks it `selected`.
      // Either is better than the first succeeded pair, but the first succeeded
      // pair is better than nothing.
      if (!pair || entry.nominated || entry.selected) pair = entry
    }
  })

  const roundTrip = pair?.currentRoundTripTime ?? remoteInbound?.roundTripTime
  const received = inbound?.packetsReceived ?? 0
  const lost = inbound?.packetsLost ?? 0
  const offered = received + Math.max(lost, 0)

  let playoutDelayMs = null
  if (inbound?.jitterBufferDelay != null && inbound?.jitterBufferEmittedCount) {
    playoutDelayMs = round((1000 * inbound.jitterBufferDelay) / inbound.jitterBufferEmittedCount, 2)
  }

  return {
    rtt_ms: roundTrip == null ? null : round(1000 * roundTrip, 2),
    // Seconds → milliseconds. See the note above.
    jitter_ms: inbound?.jitter == null ? null : round(1000 * inbound.jitter, 3),
    packets_received: received,
    packets_lost: lost,
    loss_pct: offered > 0 ? round((100 * lost) / offered, 3) : null,
    packets_sent: outbound?.packetsSent ?? null,
    playout_delay_ms: playoutDelayMs,
    audio_level: inbound?.audioLevel ?? null,
    candidate_pair: pair ? `${pair.localCandidateId} ⇄ ${pair.remoteCandidateId}` : null,
    bytes_received: inbound?.bytesReceived ?? null,
  }
}

function round(value, places) {
  const factor = 10 ** places
  return Math.round(value * factor) / factor
}
