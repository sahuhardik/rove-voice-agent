// The console's live feed: `WS /ws/support` (`server/support.py`).
//
// Read-mostly by construction, not by politeness. The socket joins
// `session.observers` rather than `session.listeners`, so the caller's turn
// dispatcher never sees it, and the server's accepted message set is three
// items long — `ping`, `refresh`, `support.note`. Sending `user.text` here is
// refused with its reason: a support human typing into the caller's dispatcher
// would author a caller line, and `docs/06` §7.2's M10 is computed over a
// transcript whose caller lines are the caller's.
//
// Reconnection is expected rather than exceptional (§1.4.2 says so about the
// caller's socket and it is no less true here). The session is server-side, so
// a reconnect replays `hello` with a full snapshot and nothing is lost but the
// gap itself.

const RECONNECT_MS = [500, 1000, 2000, 4000, 8000]

export class SupportSocket {
  constructor({ room, token, onMessage, onStatus }) {
    this.room = room
    this.token = token
    this.onMessage = onMessage
    this.onStatus = onStatus || (() => {})
    this.socket = null
    this.attempt = 0
    this.closed = false
    this.pinger = null
  }

  url() {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const room = encodeURIComponent(this.room)
    const token = encodeURIComponent(this.token)
    return `${scheme}://${window.location.host}/ws/support?room=${room}&token=${token}`
  }

  open() {
    if (this.closed) return
    this.onStatus('connecting')
    const socket = new WebSocket(this.url())
    this.socket = socket

    socket.onopen = () => {
      this.attempt = 0
      this.onStatus('connected')
      // A heartbeat, so a silent session is distinguishable from a dead
      // socket. A console that cannot tell those apart will eventually show a
      // frozen session as a calm one, which is the failure mode §7.6 is about.
      this.pinger = window.setInterval(() => this.send({ type: 'ping' }), 20000)
    }

    socket.onmessage = (event) => {
      let message
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      this.onMessage(message)
    }

    socket.onclose = () => {
      window.clearInterval(this.pinger)
      this.pinger = null
      if (this.closed) return
      this.onStatus('reconnecting')
      const delay = RECONNECT_MS[Math.min(this.attempt, RECONNECT_MS.length - 1)]
      this.attempt += 1
      window.setTimeout(() => this.open(), delay)
    }

    socket.onerror = () => this.onStatus('error')
  }

  send(message) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message))
    }
  }

  /** Ask for a fresh snapshot — after a join, or after anything we did. */
  refresh() {
    this.send({ type: 'refresh' })
  }

  close() {
    this.closed = true
    window.clearInterval(this.pinger)
    if (this.socket) this.socket.close()
    this.onStatus('closed')
  }
}
