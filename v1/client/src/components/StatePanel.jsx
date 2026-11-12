// `DiagnosticState`, as the browser renders it (`docs/06` §1.4, §3.3).
//
// A projection of the server's record, never a copy the page owns. The
// attempted-step ledger is the part worth having on screen: §1.4's UI table
// asks for it by name, and a user who can see "you already tried this" is a
// user who can correct the agent before it wastes their time repeating it.

function Row({ label, children }) {
  return (
    <div className="kv">
      <span className="kv-key">{label}</span>
      <span className="kv-value">{children}</span>
    </div>
  )
}

function confidence(value) {
  if (value == null) return '—'
  return `${Math.round(value * 100)}%`
}

export default function StatePanel({ state }) {
  if (!state) {
    return <p className="muted">No session state yet.</p>
  }

  const { device, problem, ledger, answers, safety, escalation } = state

  return (
    <div className="state">
      <Row label="fsm">
        <code>{state.fsm_state}</code> · turn {state.turn}
      </Row>

      <h3>Device</h3>
      <Row label="model">
        {device?.model || <span className="muted">unidentified</span>}
        {device?.model ? <span className="muted"> ({confidence(device.confidence)})</span> : null}
      </Row>
      {device?.hw_revision && <Row label="revision">{device.hw_revision}</Row>}
      {device?.firmware_version && <Row label="firmware">{device.firmware_version}</Row>}
      {device?.candidates?.length ? (
        <Row label="candidates">{device.candidates.join(', ')}</Row>
      ) : null}

      <h3>Problem</h3>
      <Row label="category">{problem?.category || <span className="muted">—</span>}</Row>
      <Row label="taxonomy">
        {problem?.taxonomy_id ? <code>{problem.taxonomy_id}</code> : <span className="muted">—</span>}
      </Row>
      {problem?.verbatim_symptom && <Row label="said">“{problem.verbatim_symptom}”</Row>}
      {problem?.hypothesis && <Row label="hypothesis">{problem.hypothesis}</Row>}

      <h3>Attempted steps</h3>
      {ledger?.length ? (
        <ul className="ledger">
          {ledger.map((entry) => (
            <li key={`${entry.step_id}-${entry.source}`}>
              <code>{entry.step_id}</code>
              <span className={`badge badge-${entry.outcome}`}>{entry.outcome}</span>
              <span className="muted">
                via {entry.source}
                {entry.count > 1 ? ` ×${entry.count}` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Nothing attempted yet.</p>
      )}

      {answers?.length ? (
        <>
          <h3>Answers on record</h3>
          <ul className="ledger">
            {answers.map((answer) => (
              <li key={answer.step_id}>
                <code>{answer.step_id}</code>
                <span className="badge">{answer.reading}</span>
                <span className="muted">{answer.modality}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h3>Safety</h3>
      <Row label="driving">{safety?.driving ? <span className="warn-text">yes</span> : 'no'}</Row>
      <Row label="footage at stake">{safety?.footage_at_stake ? 'yes' : 'no'}</Row>
      {safety?.hazard_flags?.length ? (
        <Row label="flags">
          <span className="warn-text">{safety.hazard_flags.join(', ')}</span>
        </Row>
      ) : null}

      {escalation?.triggered ? (
        <>
          <h3>Escalation</h3>
          <Row label="reason">
            <span className="warn-text">
              <code>{escalation.reason_code}</code> {escalation.reason}
            </span>
          </Row>
        </>
      ) : null}
    </div>
  )
}
