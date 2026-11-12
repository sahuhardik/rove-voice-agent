// The session trace, live (`docs/06` §7.5).
//
// The server writes one JSONL file per session; this is the same stream pushed
// to the open page as it happens. It is here because the 10-minute stability
// check and the drop-and-rejoin check in `client/README.md` are both read off
// it — `webrtc.connected` twice with one `webrtc.disconnected` between them is
// what a successful rejoin looks like, and seeing it live beats grepping a file
// afterwards.

const INTERESTING = new Set([
  'session.created',
  'session.minted',
  'session.renewed',
  'webrtc.offer',
  'webrtc.answer',
  'webrtc.connected',
  'webrtc.disconnected',
  'webrtc.offer_failed',
  'greeting.played',
  'greeting.failed',
  'vad.speech_start',
  'vad.speech_end',
  'turn.user',
  'turn.reply',
  'turn.failed',
  'media.stopped',
  'media.error',
  'net.server_stats',
  'auth.rejected',
  'control.connected',
  'control.disconnected',
])

function detail(event) {
  switch (event.type) {
    case 'vad.speech_end':
      return `${event.duration_ms} ms (hangover ${Math.round((event.stop_secs ?? 0) * 1000)} ms)`
    case 'greeting.played':
      return `${event.duration_ms} ms, ${event.voice}/${event.engine}`
    case 'net.server_stats':
      return [
        event.rtt_ms != null ? `rtt ${event.rtt_ms} ms` : null,
        event.jitter_ms != null ? `jitter ${event.jitter_ms} ms` : null,
        event.packets_lost != null ? `lost ${event.packets_lost}` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    case 'turn.reply':
      return `${event.step_id ?? (event.escalate ? 'escalate' : '—')} · ${event.latency_ms} ms`
    case 'turn.user':
      return `${event.modality}: ${event.value}`
    case 'webrtc.connected':
      return `up in ${event.elapsed_since_offer_s}s`
    case 'webrtc.disconnected':
      return `held ${event.held_for_s}s, ${event.frames_received} frames`
    case 'auth.rejected':
      return event.reason
    default:
      return ''
  }
}

export default function EventLog({ events }) {
  const shown = events.filter((event) => INTERESTING.has(event.type)).slice(-80).reverse()

  if (!shown.length) {
    return <p className="muted">No events yet.</p>
  }

  return (
    <ol className="events">
      {shown.map((event) => (
        <li key={event.seq}>
          <span className="muted event-time">{event.elapsed_s?.toFixed(1)}s</span>
          <code className="event-type">{event.type}</code>
          <span className="muted">{detail(event)}</span>
        </li>
      ))}
    </ol>
  )
}
