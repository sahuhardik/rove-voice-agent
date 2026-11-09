// The console, wired up (`docs/06` §5.3, `docs/07` D-17, §9.3 item 14).
//
// This file owns the DOM and the network; `panels.js` owns the HTML and owns
// no DOM at all. The split is deliberate: the §5.2 panel is the deliverable of
// this milestone, and a rendering bug in it is a human being told something
// untrue about somebody else's camera, so the rendering is pure functions that
// can be read — and tested — without a browser.
//
// **The two-step join is a two-step control.** §6.3 says the caller is told a
// human can hear them and read the transcript *before* the join, not after, so
// "Disclose" and "Join" are two buttons and the second is disabled until the
// first has run. The server refuses the join either way (409); the UI simply
// does not offer the button that would earn that refusal. Neither one is the
// safety property on its own — the server's refusal is — but a console whose
// buttons disagreed with the server's rules would teach its operator the wrong
// model of what is allowed.
//
// **Nothing here speaks for the caller.** The console socket's accepted message
// set is `ping`, `refresh` and `support.note`; there is no control on this page
// that composes a caller turn, because §7.2's M10 is computed over a transcript
// whose caller lines are the caller's.

import {
  collect,
  disclose,
  getTrace,
  join,
  leave,
  listRooms,
  mintObserver,
} from './api.js'
import {
  claimsPanel,
  consentPanel,
  handoffPanel,
  ledgerPanel,
  roomList,
  statePanel,
  tracePanel,
  transcriptPanel,
} from './panels.js'
import { SupportSocket } from './socket.js'

/** How often the panel is rebuilt while nothing is happening.
 *
 * D-17: the handoff is "rendered from `DiagnosticState` at the moment they are
 * admitted, **and live thereafter**". The socket pushes on every change, so
 * this interval is the floor rather than the mechanism — it exists so that the
 * clock fields (duration, age) move and so that a missed push self-heals.
 */
const REFRESH_MS = 4000

const $ = (id) => document.getElementById(id)

/** Session state. The support key never leaves this object, and this object
 *  never leaves memory: no `localStorage`, so a reload asks again. */
const view = {
  key: '',
  room: '',
  token: '',
  identity: '',
  socket: null,
  snapshot: null,
  handoff: null,
  traceEvents: [],
  traceSeq: 0,
  refreshTimer: null,
  pendingRefresh: null,
}

// --------------------------------------------------------------------------
// Small DOM helpers
// --------------------------------------------------------------------------

function show(element, visible) {
  element.hidden = !visible
}

function setError(element, message) {
  element.textContent = message || ''
  show(element, Boolean(message))
}

function setNotice(message) {
  setError($('session-notice'), message)
}

function setConnection(status) {
  const pill = $('connection')
  pill.textContent = status
  pill.className = `pill pill-${status === 'connected' ? 'ok' : status === 'error' ? 'bad' : 'idle'}`
}

/** Run an async action, putting whatever it throws where a human can read it.
 *
 * The server's refusals explain themselves — a 409 on the join says §6.3 has
 * not been satisfied and a 409 on collection says the caller did not consent
 * to storage — so the detail is surfaced verbatim rather than replaced with a
 * friendlier sentence that would lose which rule fired.
 */
async function guard(what, action) {
  setError($('session-error'), '')
  try {
    return await action()
  } catch (error) {
    setError($('session-error'), `${what}: ${error.message}`)
    return null
  }
}

// --------------------------------------------------------------------------
// The gate: support key → room list → observer token
// --------------------------------------------------------------------------

$('gate-form').addEventListener('submit', async (event) => {
  event.preventDefault()
  const key = $('support-key').value.trim()
  if (!key) {
    setError($('gate-error'), 'the support key is required')
    return
  }
  setError($('gate-error'), '')
  try {
    const { rooms } = await listRooms(key)
    view.key = key
    $('room-list').innerHTML = roomList(rooms)
  } catch (error) {
    setError($('gate-error'), error.message)
  }
})

// Delegated, because the table is replaced wholesale on every list.
$('room-list').addEventListener('click', async (event) => {
  const button = event.target.closest('button.pick')
  if (!button) return
  const room = button.dataset.room
  try {
    const minted = await mintObserver(view.key, room)
    openSession(minted)
  } catch (error) {
    setError($('gate-error'), error.message)
  }
})

// --------------------------------------------------------------------------
// One session
// --------------------------------------------------------------------------

function openSession(minted) {
  view.room = minted.room
  view.token = minted.token
  view.identity = minted.identity
  view.snapshot = null
  view.handoff = null
  view.traceEvents = []
  view.traceSeq = 0

  show($('gate'), false)
  show($('session'), true)
  setError($('session-error'), '')
  setNotice('')
  $('session-room').textContent = minted.room
  $('session-meta').textContent =
    `${minted.session_id} · observing as ${minted.identity} · ` +
    `${minted.scope} · token expires in ${minted.ttl_seconds}s`

  view.socket = new SupportSocket({
    room: minted.room,
    token: minted.token,
    onStatus: setConnection,
    onMessage: onMessage,
  })
  view.socket.open()

  view.refreshTimer = window.setInterval(() => view.socket && view.socket.refresh(), REFRESH_MS)
  // Seed the trace from the REST surface: the socket only carries events from
  // the moment it connected, and a human arriving mid-session wants what has
  // already happened.
  guard('trace', async () => {
    const { events } = await getTrace(view.room, view.token, 0)
    mergeTrace(events)
    render()
  })
}

function closeSession() {
  if (view.socket) view.socket.close()
  view.socket = null
  window.clearInterval(view.refreshTimer)
  view.refreshTimer = null
  view.room = ''
  view.token = ''
  show($('session'), false)
  show($('gate'), true)
  setConnection('not connected')
}

function mergeTrace(events) {
  for (const event of events || []) {
    if (event.seq !== undefined && event.seq <= view.traceSeq) continue
    if (event.seq !== undefined) view.traceSeq = event.seq
    view.traceEvents.push(event)
  }
}

/** Ask the server for a fresh snapshot, at most once per animation beat.
 *
 * Several messages often describe one change — a join sends a transcript line
 * and a participants update — and refreshing per message would re-render the
 * whole console two or three times for one event.
 */
function scheduleRefresh() {
  if (view.pendingRefresh) return
  view.pendingRefresh = window.setTimeout(() => {
    view.pendingRefresh = null
    if (view.socket) view.socket.refresh()
  }, 120)
}

function onMessage(message) {
  switch (message.type) {
    case 'hello':
      view.snapshot = message.snapshot
      view.handoff = message.handoff
      render()
      return
    case 'trace':
      mergeTrace([message.event])
      render()
      return
    case 'support.note':
      setNotice(`note: ${message.text}`)
      return
    case 'error':
      setError($('session-error'), message.detail || 'the server refused that')
      return
    case 'pong':
      return
    default:
      // transcript, turn.reply, consent, participants — every one of them
      // changes what the panels say, and the authoritative answer to what
      // they say now is the snapshot.
      scheduleRefresh()
  }
}

// --------------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------------

function render() {
  const snapshot = view.snapshot
  const handoff = view.handoff
  if (!snapshot) return

  const consent = snapshot.consent || {}
  const agentMode = snapshot.agent_mode
  const participants = snapshot.participants || []

  $('panel-consent').innerHTML = consentPanel(consent)
  $('panel-transcript').innerHTML = transcriptPanel(snapshot.transcript, {
    displayed: snapshot.transcript_displayed !== false,
  })
  $('panel-state').innerHTML = statePanel(snapshot.state, { agentMode, participants })
  // The handoff's ledger rows carry the step description and the destructive
  // flag; the snapshot's carry neither, because the caller's page renders the
  // step it was given rather than the ontology. Prefer the richer one and fall
  // back so the panel is never blank while the first handoff is in flight.
  $('panel-ledger').innerHTML = ledgerPanel(handoff?.already_tried || snapshot.state?.ledger)
  // The citations live on the handoff, not the snapshot: §5.2 asks for
  // "chunk_ids + doc_code + page + tier + retrieval date", and resolving a
  // chunk id to that row is the handoff builder's job.
  $('panel-claims').innerHTML = claimsPanel(handoff?.authority)
  $('panel-handoff').innerHTML = handoffPanel(handoff)
  $('panel-trace').innerHTML = tracePanel(view.traceEvents)

  const mode = $('agent-mode')
  mode.textContent = `agent: ${agentMode || '—'}`
  mode.className = `pill pill-${agentMode === 'transcribing' ? 'ok' : 'idle'}`

  const joined = participants.some((p) => p.identity === view.identity && p.present)
  // §6.3: the join is offered only once the caller has been told it may happen.
  $('btn-join').disabled = !consent.escalation_disclosed || joined
  $('btn-disclose').disabled = Boolean(consent.escalation_disclosed)
  show($('btn-leave'), joined)
}

// --------------------------------------------------------------------------
// The controls
// --------------------------------------------------------------------------

$('btn-disclose').addEventListener('click', () =>
  guard('disclosure', async () => {
    await disclose(view.room, view.token, '')
    setNotice(
      'The caller has been told a human can hear them and read the transcript. ' +
        'The join is now allowed (§6.3).',
    )
    view.socket.refresh()
  }),
)

$('btn-join').addEventListener('click', () =>
  guard('join', async () => {
    const name = $('display-name').value.trim()
    const result = await join(view.room, view.token, name)
    setNotice(
      `Joined. The agent is now ${result.agent_mode} — it has stopped proposing ` +
        'steps and is keeping the transcript and the ledger (§5.3).',
    )
    view.handoff = result.handoff || view.handoff
    view.socket.refresh()
  }),
)

$('btn-leave').addEventListener('click', () =>
  guard('leave', async () => {
    // The agent does **not** resume by default: §5.3 says what the join does
    // and says nothing about a departure, so handing the session back is an
    // explicit act rather than a side effect of closing a tab.
    const resume = window.confirm(
      'Hand the session back to the agent?\n\n' +
        'OK — the agent resumes proposing steps.\n' +
        'Cancel — you leave and the agent stays in transcribing mode.',
    )
    const result = await leave(view.room, view.token, resume)
    setNotice(`Left the room. The agent is ${result.agent_mode}.`)
    view.socket.refresh()
  }),
)

$('btn-collect').addEventListener('click', () =>
  guard('collection', async () => {
    const result = await collect(view.room, view.token)
    const receipt = result.receipt
    setNotice(
      `Collected ${receipt.lines} line(s) over ${receipt.turns} turn(s) into the ` +
        `pilot corpus as ${receipt.session_id}` +
        `${receipt.redacted ? ', identifiers redacted (§6.3)' : ''}. ${receipt.audio}`,
    )
  }),
)

$('btn-close').addEventListener('click', closeSession)
