// The four server surfaces, as the page uses them.
//
// Everything is relative to the page's own origin: the client is served by the
// same process it talks to (`server/app.py` mounts `client/dist`), so there is
// no base URL to configure and no CORS to arrange. `npm run dev` keeps that
// true by proxying `/api`, `/ws` and `/healthz` to :8080.

/** The one credential the browser ever holds (`docs/06` §1.4.2). */
export async function openSession() {
  const response = await fetch('/api/session', { method: 'POST' })
  if (!response.ok) throw new Error(`mint failed: HTTP ${response.status}`)
  return response.json()
}

/**
 * Re-mint for the room we are already in.
 *
 * §1.4.2 wants a credential measured in minutes and sessions that outlive it.
 * The page bridges the two by renewing while it is open, so a drop-and-rejoin
 * ten minutes in still presents an unexpired token for the *same* room — and
 * so keeps the `DiagnosticState` the server has been building. Renewal needs an
 * unexpired token; there is no grace window.
 */
export async function renewToken(room, token) {
  const response = await fetch(`/api/session/${encodeURIComponent(room)}/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!response.ok) throw new Error(`renew failed: HTTP ${response.status}`)
  return response.json()
}

/** Signalling. Returns the SDP answer. */
export async function postOffer({ sdp, type, room, token, pcId, restartPc }) {
  const response = await fetch('/api/offer', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      sdp,
      type,
      room,
      token,
      pc_id: pcId ?? null,
      restart_pc: Boolean(restartPc),
    }),
  })
  if (!response.ok) {
    throw new Error(`offer refused: HTTP ${response.status} ${await response.text()}`)
  }
  return response.json()
}

/** Trickled ICE candidates. Best-effort: a failure here is not fatal. */
export async function postCandidates({ room, token, pcId, candidates }) {
  if (!candidates.length) return
  await fetch('/api/ice', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ room, token, pc_id: pcId, candidates }),
  })
}

export function controlSocketUrl(room, token) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const query = `room=${encodeURIComponent(room)}&token=${encodeURIComponent(token)}`
  return `${scheme}://${window.location.host}/ws?${query}`
}
