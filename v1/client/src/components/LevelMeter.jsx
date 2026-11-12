// "I can hear you", with a number behind it.
//
// The level and the speech segments both come down the media plane's data
// channel — the `rove` topic from `server/livekit_agent.py` on LiveKit, or
// `SpeechReporter` in `server/pipeline.py` on the fallback. Either way what
// this meter shows is what the *server* received, after the whole uplink. A
// meter driven from the local `AnalyserNode` would move even when nothing was
// reaching the server, which is the one failure a user most needs to see.

const FLOOR_DBFS = -60

function toFraction(dbfs) {
  if (dbfs == null) return 0
  const clamped = Math.max(FLOOR_DBFS, Math.min(0, dbfs))
  return (clamped - FLOOR_DBFS) / -FLOOR_DBFS
}

export default function LevelMeter({ level, segments, muted, active }) {
  const dbfs = level?.dbfs ?? null
  const speaking = Boolean(level?.speaking)
  const fraction = muted ? 0 : toFraction(dbfs)
  const lastSegment = segments?.[segments.length - 1]

  return (
    <div className={`meter ${active ? '' : 'meter-idle'}`}>
      <div className="meter-track">
        <div
          className={`meter-fill ${speaking ? 'meter-speaking' : ''}`}
          style={{ width: `${Math.round(fraction * 100)}%` }}
        />
      </div>
      <div className="meter-caption">
        {!active ? (
          <span className="muted">no audio path</span>
        ) : muted ? (
          <span className="warn-text">muted — the server is receiving silence</span>
        ) : speaking ? (
          <span className="good-text">speech detected</span>
        ) : (
          <span className="muted">
            {dbfs == null ? 'waiting for audio' : `${dbfs.toFixed(1)} dBFS at the server`}
          </span>
        )}
        <span className="muted">
          {segments?.length ? `${segments.length} segment(s)` : 'no segments yet'}
          {lastSegment ? ` · last ${lastSegment.duration_ms} ms` : ''}
        </span>
      </div>
    </div>
  )
}
