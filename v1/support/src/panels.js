// The panels the joining human reads (`docs/06` §5.2, §1.4, §3.3, §4.4).
//
// Pure functions: session data in, HTML string out, no DOM access and no
// network. `main.js` owns both. That split is worth keeping because the §5.2
// panel is the deliverable of this milestone and a rendering bug in it is a
// human being told something untrue about somebody else's camera.
//
// **Everything is escaped.** The transcript holds a stranger's typed words and
// the handoff holds `verbatim_symptom`, which §5.2 carries word for word on
// purpose. Word for word includes the words that look like markup.

/** The only way text reaches the page. */
export function esc(value) {
  if (value === null || value === undefined) return ''
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const dash = (value) => (value === null || value === undefined || value === '' ? '—' : value)

function clock(seconds) {
  if (!Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`
}

function at(stamp) {
  if (!stamp) return ''
  return new Date(stamp * 1000).toLocaleTimeString()
}

function rows(pairs) {
  return pairs
    .map(([label, value]) => `<tr><th>${esc(label)}</th><td>${value}</td></tr>`)
    .join('')
}

function head(title, note) {
  return `<h2>${esc(title)}${note ? `<span class="note">${esc(note)}</span>` : ''}</h2>`
}

// --------------------------------------------------------------------------
// Consent (§6.3)
// --------------------------------------------------------------------------

/**
 * The consent panel.
 *
 * Display and storage are shown as two rows because §6.3 makes them two
 * decisions: "the live transcript is rendered in the browser whether or not it
 * is retained, so 'displayed' and 'stored' are separate decisions and the
 * consent gate governs storage, not display". A single "consent: yes/no" row
 * would be a lie about which of those two this session actually has.
 */
export function consentPanel(consent) {
  if (!consent) return head('Consent') + '<p class="muted">—</p>'
  const badge = (value) =>
    `<span class="chip chip-${esc(value)}">${esc(value)}</span>`
  const store = consent.may_store
  return (
    head('Consent', 'docs/06 §6.3') +
    `<table class="kv">${rows([
      ['Display', `${badge(consent.display)} <span class="muted">${consent.may_display ? 'transcript rendered' : 'transcript withheld'}</span>`],
      ['Storage', `${badge(consent.storage)} <span class="muted">${store ? 'may be collected' : 'nothing is stored'}</span>`],
      ['Disclosed', consent.disclosed ? `yes · ${esc(at(consent.disclosed_at))} ${consent.disclosed_spoken ? 'spoken' : ''} ${consent.disclosed_shown ? 'shown' : ''}` : '<b class="warn">no</b>'],
      ['Jurisdiction', `${esc(consent.jurisdiction)}${consent.requires_affirmative ? ' · affirmative answer required' : ''}`],
      ['Modality', `${esc(dash(consent.storage_modality))}`],
      ['Join disclosed', consent.escalation_disclosed ? `yes · ${esc(at(consent.escalation_disclosed_at))}` : '<b class="warn">no — §6.3 says before the join</b>'],
    ])}</table>` +
    (store
      ? ''
      : `<p class="gatebox">Nothing from this session is written anywhere. §6.3:
         <em>recording is off until a consent decision exists</em> — and
         <code>undecided</code> is not a decision.</p>`)
  )
}

// --------------------------------------------------------------------------
// Transcript (§1.4)
// --------------------------------------------------------------------------

export function transcriptPanel(lines, { displayed = true } = {}) {
  if (!displayed) {
    return (
      head('Transcript') +
      `<p class="gatebox">The caller declined the <em>display</em> decision, so
       the live transcript is not rendered here either. §6.3 keeps display and
       storage apart; this is the display one.</p>`
    )
  }
  if (!lines || !lines.length) {
    return head('Transcript') + '<p class="muted">Nothing said yet.</p>'
  }
  const body = lines
    .map(
      (line) => `
      <li class="line line-${esc(line.role)}">
        <span class="who">${esc(line.role)}</span>
        <span class="said">${esc(line.text)}</span>
        <span class="meta">t${esc(line.turn)} · ${esc(line.modality)} · ${esc(at(line.at))}</span>
      </li>`,
    )
    .join('')
  return head('Transcript', `${lines.length} lines`) + `<ol class="transcript">${body}</ol>`
}

// --------------------------------------------------------------------------
// DiagnosticState (§3.3)
// --------------------------------------------------------------------------

export function statePanel(state, { agentMode, participants } = {}) {
  if (!state) return head('Diagnostic state') + '<p class="muted">—</p>'
  const people = (participants || [])
    .map(
      (p) =>
        `<span class="chip ${p.present ? 'chip-granted' : 'chip-undecided'}">${esc(
          p.display_name || p.identity,
        )}${p.present ? '' : ' (left)'}</span>`,
    )
    .join(' ')
  return (
    head('Diagnostic state', 'docs/06 §3.3') +
    `<table class="kv">${rows([
      ['FSM state', `<code>${esc(state.fsm_state)}</code>`],
      ['Turn', esc(state.turn)],
      [
        'Agent',
        `<span class="chip chip-${agentMode === 'transcribing' ? 'granted' : 'undecided'}">${esc(
          dash(agentMode),
        )}</span>${agentMode === 'transcribing' ? ' <span class="muted">not proposing steps — §5.3</span>' : ''}`,
      ],
      ['In the room', people || '<span class="muted">caller and agent only</span>'],
      ['Model', `${esc(dash(state.device?.model))} <span class="muted">${esc(dash(state.device?.confidence))}</span>`],
      ['HW revision', esc(dash(state.device?.hw_revision))],
      ['Firmware', esc(dash(state.device?.firmware_version))],
      ['Category', esc(dash(state.problem?.category))],
      ['Taxonomy', `<code>${esc(dash(state.problem?.taxonomy_id))}</code>`],
      ['Hypothesis', esc(dash(state.problem?.hypothesis))],
      [
        'Safety',
        `driving: ${esc(dash(state.safety?.driving))} · footage: ${esc(
          dash(state.safety?.footage_at_stake),
        )}${(state.safety?.hazard_flags || []).length ? ` · <b class="warn">hazard: ${esc((state.safety.hazard_flags || []).join(', '))}</b>` : ''}`,
      ],
      [
        'Escalation',
        state.escalation?.triggered
          ? `<b class="warn">${esc(state.escalation.reason_code)}</b> — ${esc(state.escalation.reason)}`
          : '<span class="muted">not triggered</span>',
      ],
    ])}</table>`
  )
}

// --------------------------------------------------------------------------
// The attempted-step ledger (§3.3, §5.2 ALREADY TRIED)
// --------------------------------------------------------------------------

/**
 * §5.2 prints this "in order" and so does this panel.
 *
 * The order is the content: it is what tells a human arriving mid-session what
 * has already been ruled out by doing, and it is what §7.2's M4 is computed
 * against. `source` is shown because "the caller had already tried it" and
 * "we asked them to" are different facts about the same step id.
 */
export function ledgerPanel(ledger) {
  if (!ledger || !ledger.length) {
    return head('Already tried') + '<p class="muted">Nothing attempted yet.</p>'
  }
  const body = ledger
    .map(
      (entry, index) => `
      <tr>
        <td class="num">${index + 1}</td>
        <td><code>${esc(entry.step_id)}</code>${entry.destructive ? ' <span class="chip chip-declined">destructive</span>' : ''}</td>
        <td class="num">${entry.count ? `×${esc(entry.count)}` : ''}</td>
        <td>${esc(entry.source)}</td>
        <td>${esc(entry.outcome)}</td>
      </tr>`,
    )
    .join('')
  return (
    head('Already tried', `${ledger.length} · docs/06 §5.2`) +
    `<table class="grid-table"><thead><tr><th>#</th><th>step</th><th></th><th>source</th><th>outcome</th></tr></thead><tbody>${body}</tbody></table>`
  )
}

// --------------------------------------------------------------------------
// Spoken claims and their citations (§4.4, §5.2 "ON WHAT AUTHORITY")
// --------------------------------------------------------------------------

/**
 * Every claim the agent has spoken, with the chunks behind it.
 *
 * §5.2 asks for "spoken claims + chunk_ids + doc_code + page + tier +
 * retrieval date", and the reason it asks for all six is that a chunk id on
 * its own is not an authority — it is a key into one. A claim with no chunk
 * behind it is called out rather than shown as an empty list, because that is
 * precisely the case §4.5's output guard exists to make impossible and a
 * silent empty row would hide it having happened.
 */
export function claimsPanel(claims) {
  if (!claims || !claims.length) {
    return head('What was said, and on what authority') + '<p class="muted">No claims spoken yet.</p>'
  }
  const body = claims
    .map((claim) => {
      const cites = (claim.citations || [])
        .map(
          (cite) => `
          <li>
            <code>${esc(cite.chunk_id)}</code>
            <span class="meta">${esc(dash(cite.doc_code))}${cite.page ? ` · ${esc(cite.page)}` : ''}${
              cite.tier ? ` · tier ${esc(cite.tier)}` : ''
            }${cite.retrieval_date ? ` · ${esc(cite.retrieval_date)}` : ''}${
              cite.verification_status ? ` · ${esc(cite.verification_status)}` : ''
            }</span>
            ${cite.title ? `<span class="meta">${esc(cite.title)}</span>` : ''}
            ${cite.resolved === false ? '<b class="warn">unresolved in this corpus snapshot</b>' : ''}
          </li>`,
        )
        .join('')
      return `
        <li class="claim">
          <p class="said">${esc(claim.claim)}</p>
          <span class="meta">turn ${esc(claim.turn)}</span>
          ${claim.uncited ? '<p class="warn">no chunk cited — §4.5</p>' : `<ul class="cites">${cites}</ul>`}
        </li>`
    })
    .join('')
  return (
    head('What was said, and on what authority', 'docs/06 §5.2') +
    `<ul class="claims">${body}</ul>`
  )
}

// --------------------------------------------------------------------------
// The handoff payload (§5.2)
// --------------------------------------------------------------------------

/**
 * The §5.2 panel itself.
 *
 * D-17: the handoff "is not something sent somewhere — it is the panel the
 * joining human sees, rendered from `DiagnosticState` at the moment they are
 * admitted and live thereafter". So this re-renders on every poll rather than
 * freezing at the join, and the field order follows §5.2's layout so that the
 * document and the screen can be read against each other.
 */
export function handoffPanel(handoff) {
  if (!handoff) return head('Handoff') + '<p class="muted">—</p>'
  const device = handoff.device || {}
  const context = handoff.context || {}
  const hypothesis = handoff.hypothesis || {}
  const escalation = handoff.escalation || {}

  const answered = (handoff.already_answered || [])
    .map(
      (answer) =>
        `<li><code>${esc(answer.step_id)}</code> → <b>${esc(answer.reading)}</b>${
          answer.verbatim ? ` <span class="muted">“${esc(answer.verbatim)}”</span>` : ''
        }</li>`,
    )
    .join('')

  const ruledOut = (hypothesis.ruled_out || [])
    .map((entry) => `<li>${esc(entry.text)} <span class="muted">— ${esc(entry.reason)}</span></li>`)
    .join('')
  const notRuledOut = (hypothesis.not_ruled_out || [])
    .map((entry) => `<li>${esc(entry.text)} <span class="muted">(${esc(entry.confidence)})</span></li>`)
    .join('')

  const withheld = (handoff.withheld || [])
    .map((entry) => `<li><code>${esc(entry.field)}</code> “${esc(entry.span)}” — ${esc(entry.reason)}</li>`)
    .join('')

  const footageFlag = ['wanted', 'insurance_or_police'].includes(context.footage_at_stake)

  return (
    head('Handoff', 'docs/06 §5.2') +
    `<p class="muted mono">${esc(handoff.session_id)} · ${esc(clock(handoff.duration_s))} ·
      ${esc(handoff.agent_version)} · corpus ${esc(handoff.corpus_snapshot_date)}</p>

     <h3>User said (verbatim, turn 1)</h3>
     <blockquote>${esc(dash(handoff.user_said?.verbatim))}</blockquote>

     <table class="kv">${rows([
       ['Symptom', esc(dash(handoff.symptom_summary))],
       ['Category', esc(dash(handoff.category))],
       ['Taxonomy', `<code>${esc(dash(handoff.taxonomy_id))}</code> · ${esc(dash(handoff.taxonomy_status))}`],
     ])}</table>

     <h3>Device</h3>
     <table class="kv">${rows([
       ['Model', `${esc(dash(device.model))} · ${esc(dash(device.hw_revision))}`],
       ['Confidence', `${esc(dash(device.confidence))} <span class="muted">${esc(dash(device.why))}</span>`],
       [
         'Firmware',
         device.firmware?.value
           ? `${esc(device.firmware.value)} <span class="muted">(${esc(device.firmware.source)})</span>`
           : '<span class="muted">not obtained — never agent-stated</span>',
       ],
       ['Card', esc(dash(JSON.stringify(device.card || {}) === '{}' ? '' : JSON.stringify(device.card)))],
       ['Power', esc(dash(JSON.stringify(device.power || {}) === '{}' ? '' : JSON.stringify(device.power)))],
     ])}</table>

     <h3>Context</h3>
     <table class="kv">${rows([
       ['Change event', esc(dash(context.change_event))],
       ['Environment', esc(dash(context.environment))],
       [
         'Footage at stake',
         footageFlag
           ? `<b class="warn">${esc(context.footage_at_stake)}</b>`
           : esc(dash(context.footage_at_stake)),
       ],
     ])}</table>

     <h3>Already answered</h3>
     ${answered ? `<ul class="plain">${answered}</ul>` : '<p class="muted">Nothing recorded.</p>'}

     <h3>Agent's hypothesis</h3>
     ${
       hypothesis.top
         ? `<p>${esc(hypothesis.top.text)} <span class="muted">— confidence ${esc(
             hypothesis.top.confidence,
           )}, held ${esc(hypothesis.top.turns_held)} turn(s)</span></p>`
         : '<p class="muted">None yet.</p>'
     }
     ${ruledOut ? `<h4>Ruled out, and why</h4><ul class="plain">${ruledOut}</ul>` : ''}
     ${notRuledOut ? `<h4>Not ruled out</h4><ul class="plain">${notRuledOut}</ul>` : ''}

     <h3>Escalation</h3>
     <table class="kv">${rows([
       [
         'Reason code',
         escalation.triggered
           ? `<b class="warn">${esc(escalation.reason_code)}</b>`
           : '<span class="muted">not triggered</span>',
       ],
       ['Recording + consent', esc(escalation.recording_and_consent)],
       ['Transcript pointer', `<span class="mono">${esc(escalation.transcript_pointer)}</span>`],
     ])}</table>

     ${
       withheld
         ? `<h3>Withheld</h3><ul class="plain small">${withheld}</ul>
            <p class="muted small">§5.2 forbids two things in this payload: a declaration
            that the hardware is faulty, and any warranty or returns statement. What was
            removed is listed rather than silently dropped.</p>`
         : ''
     }`
  )
}

// --------------------------------------------------------------------------
// Trace (§7.5)
// --------------------------------------------------------------------------

export function tracePanel(events) {
  if (!events || !events.length) return head('Trace') + '<p class="muted">—</p>'
  const interesting = new Set([
    'agent.mode',
    'support.joined',
    'support.left',
    'support.note',
    'escalation.disclosed',
    'consent.decision',
    'consent.disclosed',
    'turn.not_proposed',
    'transcript.collected',
    'transcript.refused',
    'observer.minted',
    'observer.refused',
  ])
  const body = events
    .slice(-120)
    .reverse()
    .map(
      (event) => `
      <li class="${interesting.has(event.type) ? 'hot' : ''}">
        <code>${esc(event.type)}</code>
        <span class="meta">+${esc(event.elapsed_s)}s</span>
        ${event.reason ? `<span class="meta">${esc(event.reason)}</span>` : ''}
        ${event.mode ? `<span class="meta">→ ${esc(event.mode)}</span>` : ''}
        ${event.text ? `<span class="meta">${esc(String(event.text).slice(0, 90))}</span>` : ''}
      </li>`,
    )
    .join('')
  return head('Trace', `${events.length} events`) + `<ul class="trace">${body}</ul>`
}

// --------------------------------------------------------------------------
// The room picker
// --------------------------------------------------------------------------

export function roomList(rooms) {
  if (!rooms || !rooms.length) {
    return '<p class="muted">No live rooms. A room exists from the moment a caller opens the page.</p>'
  }
  const body = rooms
    .map(
      (room) => `
      <tr data-room="${esc(room.room)}">
        <td><code>${esc(room.room)}</code></td>
        <td>${esc(clock(room.duration_s))}</td>
        <td class="num">${esc(room.turn)}</td>
        <td>${esc(dash(room.taxonomy_id))}</td>
        <td>${room.escalated ? `<b class="warn">${esc(room.escalation_reason_code || 'escalated')}</b>` : ''}${
          room.hazard ? ' <b class="warn">hazard</b>' : ''
        }</td>
        <td>${esc(room.agent_mode)}</td>
        <td>${room.humans_present.length ? esc(room.humans_present.join(', ')) : '<span class="muted">—</span>'}</td>
        <td><button class="primary pick" data-room="${esc(room.room)}">Observe</button></td>
      </tr>`,
    )
    .join('')
  return `<table class="grid-table"><thead><tr>
      <th>room</th><th>age</th><th>turns</th><th>taxonomy</th><th>flags</th>
      <th>agent</th><th>in the room</th><th></th>
    </tr></thead><tbody>${body}</tbody></table>`
}
