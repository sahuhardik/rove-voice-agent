// The support surfaces, as the console uses them (`docs/06` §5.3).
//
// Same origin as the server that owns the rooms — the console is served from
// `/support` by the same process (`server/app.py`), so there is no base URL to
// configure and no CORS to arrange. That is the same argument `docs/06` §8.1.1
// makes for the spike being one process: a second deployable here would buy
// nothing and cost an operations story.
//
// Two credentials appear in this file and they do different jobs:
//
//   * the **support key** authorises the mint, and only the mint. It is held in
//     memory for the life of the tab and never written to storage — a console
//     that left a standing credential in `localStorage` would be worse than one
//     that asks again after a reload.
//   * the **observer token** authorises everything else, for exactly one room,
//     under the `observe:room` scope. It is not the caller's token and cannot
//     be used where the caller's token is used; the server refuses it on the
//     scope claim before it reads anything else.

/** Throw with the server's own words — its 409s explain themselves. */
async function fail(response, what) {
  let detail = ''
  try {
    const body = await response.json()
    detail = body.detail ?? JSON.stringify(body)
  } catch {
    detail = await response.text()
  }
  throw new Error(`${what}: HTTP ${response.status} ${detail}`)
}

async function postJson(url, body, what) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await fail(response, what)
  return response.json()
}

/** Live rooms. The picker's input; carries no caller words (see `room_summary`). */
export async function listRooms(key) {
  const response = await fetch(`/api/support/rooms?key=${encodeURIComponent(key)}`)
  if (!response.ok) await fail(response, 'room list refused')
  return response.json()
}

/**
 * Mint an observer token for one room.
 *
 * A fresh identity per admission rather than a standing support credential:
 * the room is the unit of access, so two sessions handled by the same person
 * carry two identities and neither token is usable on the other's room.
 */
export async function mintObserver(key, room) {
  return postJson('/api/support/observer', { key, room }, 'observer mint refused')
}

/** The §5.2 panel, rebuilt from `DiagnosticState` on every call. */
export async function getHandoff(room, token) {
  const response = await fetch(
    `/api/support/room/${encodeURIComponent(room)}/handoff?token=${encodeURIComponent(token)}`,
  )
  if (!response.ok) await fail(response, 'handoff refused')
  return response.json()
}

/**
 * The session's trace, from `since_seq` onwards (§7.5).
 *
 * The socket only carries events from the moment it connected, so this seeds
 * the panel with what already happened — a human arriving at turn 9 needs the
 * first eight, and "what the agent did before I got here" is most of why the
 * trace is on screen at all.
 */
export async function getTrace(room, token, sinceSeq = 0) {
  const response = await fetch(
    `/api/support/room/${encodeURIComponent(room)}/trace` +
      `?token=${encodeURIComponent(token)}&since_seq=${Number(sinceSeq) || 0}`,
  )
  if (!response.ok) await fail(response, 'trace refused')
  return response.json()
}

/**
 * The §6.3 second consent surface — made *before* the join, never after.
 *
 * Its own call because it is its own event: the caller is told that a human
 * will be able to hear them and read the transcript, and that has to be able to
 * happen while the join is still only an intention. The server will refuse the
 * join until this has run.
 */
export async function disclose(room, token, text) {
  return postJson(
    `/api/support/room/${encodeURIComponent(room)}/disclose`,
    { token, text },
    'disclosure refused',
  )
}

/**
 * Same-session join (`docs/07` D-17).
 *
 * There is no transfer. The caller's session does not move; a second
 * participant is admitted to the room they are already in, and the agent stops
 * proposing steps and drops to transcribing (§5.3).
 */
export async function join(room, token, displayName) {
  return postJson(
    `/api/support/room/${encodeURIComponent(room)}/join`,
    { token, display_name: displayName },
    'join refused',
  )
}

/** Leave. The agent does not resume unless this says so, explicitly. */
export async function leave(room, token, resumeAgent) {
  return postJson(
    `/api/support/room/${encodeURIComponent(room)}/leave`,
    { token, resume_agent: Boolean(resumeAgent) },
    'leave failed',
  )
}

/**
 * Write the transcript to the pilot corpus, if §6.3 allows it.
 *
 * A 409 here means the caller has not granted storage consent and nothing was
 * attempted; a 503 means consent exists and the database does not. The console
 * shows the two differently because they are different facts.
 */
export async function collect(room, token) {
  return postJson(
    `/api/support/room/${encodeURIComponent(room)}/collect`,
    { token, redact: true },
    'collection refused',
  )
}
