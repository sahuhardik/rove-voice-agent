// The current diagnostic step (`docs/06` §1.4).
//
// §1.4 asks for the step "exactly as spoken", so the headline here is the
// server's `spoken_form`, not the ontology description — a user comparing what
// they heard with what is on screen should find the same sentence. The step id,
// family and destructive flag are shown underneath, because they are what makes
// the panel auditable rather than decorative.

function Row({ label, children }) {
  return (
    <div className="kv">
      <span className="kv-key">{label}</span>
      <span className="kv-value">{children}</span>
    </div>
  )
}

export default function StepPanel({ step, reply }) {
  if (!step && !reply) {
    return <p className="muted">No step proposed yet.</p>
  }

  if (!step) {
    return (
      <div>
        <p className="step-spoken">
          {reply?.escalate ? 'Handing off to a human.' : 'No step this turn.'}
        </p>
        {reply?.rationale && <p className="muted">{reply.rationale}</p>}
      </div>
    )
  }

  return (
    <div className="step">
      <p className="step-spoken">{step.spoken}</p>
      <Row label="step">
        <code>{step.step_id}</code>
      </Row>
      {step.family && <Row label="family">{step.family}</Row>}
      {step.description && <Row label="what it is">{step.description}</Row>}
      <Row label="destructive">
        {step.destructive ? (
          <span className="warn-text">yes — gated before it is proposed</span>
        ) : (
          'no'
        )}
      </Row>
      {reply?.citations?.length ? (
        <Row label="citations">
          <ul className="citations">
            {reply.citations.map((citation) => (
              <li key={citation}>
                <code>{citation}</code>
              </li>
            ))}
          </ul>
        </Row>
      ) : null}
      {reply?.dropped_claims?.length ? (
        <Row label="guard dropped">
          <ul className="citations">
            {reply.dropped_claims.map((claim, index) => (
              <li key={index} className="warn-text">
                {claim}
              </li>
            ))}
          </ul>
        </Row>
      ) : null}
      {reply?.rationale && <Row label="why">{reply.rationale}</Row>}
      {reply?.latency_ms != null && (
        <Row label="turn took">{reply.latency_ms} ms in the core</Row>
      )}
    </div>
  )
}
