// Connection status: the two planes, the link numbers, and the controls.
//
// `docs/06` §9.1 makes RTT, jitter and loss a Phase 2b deliverable rather than
// a nicety, so they are on screen and not only in the trace. These are the
// browser's own `getStats()` numbers — on LiveKit, the publisher's and the
// subscriber's merged into one report (`src/livekit.js`) and reduced by the
// same `summariseStats` the fallback uses, so the pills mean the same thing on
// both transports. The server samples its own view separately and the trace
// keeps the two apart.

import { useEffect, useState } from 'react'
import LevelMeter from './LevelMeter.jsx'

/** A once-a-second re-render, so the token countdown actually counts down. */
function useSecondHand() {
  const [, setTick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setTick((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
}

const SOCKET_LABEL = {
  idle: 'not joined',
  joining: 'joining…',
  open: 'connected',
  reconnecting: 'reconnecting…',
  closed: 'left',
  error: 'failed',
}

const SOCKET_TONE = {
  open: 'good',
  joining: 'warn',
  reconnecting: 'warn',
  error: 'bad',
}

const PC_TONE = {
  connected: 'good',
  connecting: 'warn',
  new: 'warn',
  disconnected: 'bad',
  failed: 'bad',
  closed: 'idle',
}

function Pill({ label, value, tone = 'idle', title }) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      <span className="pill-label">{label}</span>
      <span className="pill-value">{value}</span>
    </span>
  )
}

function countdown(expiresAt) {
  if (!expiresAt) return '—'
  const seconds = Math.max(0, Math.round(expiresAt - Date.now() / 1000))
  return `${seconds}s`
}

export default function ConnectionBar({
  status,
  pcState,
  stats,
  level,
  segments,
  minted,
  tokenExpiresAt,
  secure,
  muted,
  busy,
  onJoin,
  onLeave,
  onDropMedia,
  onRejoinMedia,
  onToggleMute,
}) {
  useSecondHand()
  const joined = status === 'open' || status === 'reconnecting'
  const mediaUp = pcState === 'connected'

  return (
    <div className="connection">
      <div className="pills">
        <Pill
          label="session"
          value={SOCKET_LABEL[status] ?? status}
          tone={SOCKET_TONE[status] ?? 'idle'}
          title="The control socket: typed turns, diagnostic state, transcript."
        />
        <Pill
          label="audio"
          value={secure ? pcState : 'no secure context'}
          tone={secure ? (PC_TONE[pcState] ?? 'idle') : 'bad'}
          title={
            minted?.transport === 'smallwebrtc'
              ? 'The WebRTC peer connection: microphone up, agent audio down.'
              : 'The LiveKit room: microphone published, agent audio subscribed.'
          }
        />
        <Pill
          label="rtt"
          value={stats?.rtt_ms == null ? '—' : `${stats.rtt_ms} ms`}
          tone={stats?.rtt_ms == null ? 'idle' : stats.rtt_ms < 100 ? 'good' : 'warn'}
          title="Round-trip time on the selected candidate pair (browser getStats)."
        />
        <Pill
          label="jitter"
          value={stats?.jitter_ms == null ? '—' : `${stats.jitter_ms} ms`}
          tone={stats?.jitter_ms == null ? 'idle' : stats.jitter_ms < 30 ? 'good' : 'warn'}
          title="Inbound audio jitter, in milliseconds."
        />
        <Pill
          label="loss"
          value={stats?.loss_pct == null ? '—' : `${stats.loss_pct}%`}
          tone={stats?.loss_pct == null ? 'idle' : stats.loss_pct < 1 ? 'good' : 'bad'}
          title={
            stats
              ? `${stats.packets_lost} lost of ${stats.packets_received + stats.packets_lost} offered`
              : 'no samples yet'
          }
        />
        <Pill
          label="playout"
          value={stats?.playout_delay_ms == null ? '—' : `${stats.playout_delay_ms} ms`}
          tone="idle"
          title="Mean jitter-buffer delay — §2.2 line 9, the browser's own half of it."
        />
        <Pill
          label="token"
          value={countdown(tokenExpiresAt)}
          tone="idle"
          title="Time left on the current join token. The page renews it while it is open."
        />
      </div>

      <LevelMeter level={level} segments={segments} muted={muted} active={mediaUp} />

      <div className="controls">
        {!joined ? (
          <button className="primary" onClick={onJoin} disabled={busy}>
            Join room
          </button>
        ) : (
          <>
            <button onClick={onToggleMute} disabled={!mediaUp}>
              {muted ? 'Unmute' : 'Mute'}
            </button>
            {mediaUp ? (
              <button onClick={onDropMedia} title="Close the peer connection without leaving the room">
                Drop audio
              </button>
            ) : (
              <button onClick={onRejoinMedia} disabled={busy || !secure}>
                Rejoin audio
              </button>
            )}
            <button className="danger" onClick={onLeave}>
              Leave
            </button>
          </>
        )}
      </div>

      {minted && (
        <div className="room-line">
          <code>{minted.room}</code> · <code>{minted.identity}</code>
          <span className="muted"> · {minted.transport}</span>
          {minted.livekit_url && <span className="muted"> · {minted.livekit_url}</span>}
          {stats?.candidate_pair && <span className="muted"> · pair {stats.candidate_pair}</span>}
        </div>
      )}
    </div>
  )
}
