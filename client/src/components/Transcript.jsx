// The live transcript panel (`docs/06` §1.4).
//
// Every line carries the modality it arrived by. That is not decoration: §1.4.1
// says the FSM may not branch on modality, and §7.2's M10 checks that it did
// not — so the label has to be visible for a human reading a session to see
// what the measurement is about.
//
// The last line may be a *hypothesis* rather than a line: §1.4 says "ASR
// partials may be shown greyed; finals replace them", and that is exactly what
// happens here — the partial comes down the media plane while the caller is
// still speaking, and is dropped the moment the final arrives as a real
// transcript line on the control socket.

import { useEffect, useRef } from 'react'

const MODALITY_LABEL = {
  typed: 'typed',
  click: 'clicked',
  voice: 'spoken',
  text: '',
}

function clockTime(at) {
  if (!at) return ''
  return new Date(at * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function Transcript({ lines, awaiting, partial }) {
  const endRef = useRef(null)
  const hypothesis = partial?.text ?? ''

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [lines.length, awaiting, hypothesis])

  if (!lines.length && !awaiting && !hypothesis) {
    return (
      <div className="transcript transcript-empty">
        <p className="muted">
          Nothing yet. Join the room, then say or type what the camera is doing — for
          example, <em>“my Rove R2-4K stopped recording after the firmware update”</em>.
        </p>
      </div>
    )
  }

  return (
    <div className="transcript">
      {lines.map((line, index) => (
        <div key={`${line.at}-${index}`} className={`line line-${line.role}`}>
          <div className="line-meta">
            <span className="line-role">{line.role === 'caller' ? 'You' : 'Agent'}</span>
            {MODALITY_LABEL[line.modality] ? (
              <span className="badge">{MODALITY_LABEL[line.modality]}</span>
            ) : null}
            {line.turn ? <span className="muted">turn {line.turn}</span> : null}
            <span className="muted">{clockTime(line.at)}</span>
          </div>
          <div className="line-text">{line.text}</div>
        </div>
      ))}
      {hypothesis && (
        <div className="line line-caller line-pending">
          <div className="line-meta">
            <span className="line-role">You</span>
            <span className="badge">hearing…</span>
          </div>
          <div className="line-text muted">{hypothesis}</div>
        </div>
      )}
      {awaiting && (
        <div className="line line-agent line-pending">
          <div className="line-meta">
            <span className="line-role">Agent</span>
            <span className="muted">thinking…</span>
          </div>
          <div className="line-text muted">working out the next step</div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  )
}
