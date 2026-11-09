// The control plane: one WebSocket, and everything the page renders from it.
//
// `docs/06` §1.4.2 puts `DiagnosticState` on the server and says why — "a
// dropped connection costs the in-flight turn and nothing else". This hook is
// the consequence of that decision on the browser side: it holds a *projection*
// and owns none of it. On connect the server sends a `hello` with a full
// snapshot, so a reload, a re-join or a second tab all render the same session
// without replaying a single turn.
//
// It is deliberately separate from the media link. The socket survives a media
// drop, which is what lets the transcript and the state panels keep rendering
// while the peer connection re-establishes — and what makes the drop-and-rejoin
// check in `client/README.md` observable rather than a blank page.

import { useCallback, useEffect, useRef, useState } from 'react'
import { controlSocketUrl, openSession, renewToken } from './api.js'

/** Renew at half the TTL: one missed renewal is survivable, two are not. */
const RENEW_FRACTION = 0.5

/** Reconnect backoff for the control socket, in milliseconds. */
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000]

const MAX_EVENTS = 400

export function useSession() {
  const [session, setSession] = useState(null)
  const [status, setStatus] = useState('idle') // idle | joining | open | reconnecting | closed | error
  const [transcript, setTranscript] = useState([])
  const [diagnostic, setDiagnostic] = useState(null)
  const [step, setStep] = useState(null)
  const [lastReply, setLastReply] = useState(null)
  const [events, setEvents] = useState([])
  const [awaitingReply, setAwaitingReply] = useState(false)
  const [error, setError] = useState('')
  const [tokenExpiresAt, setTokenExpiresAt] = useState(null)

  const tokenRef = useRef('')
  const roomRef = useRef('')
  const socketRef = useRef(null)
  const renewTimer = useRef(null)
  const retryTimer = useRef(null)
  const attempt = useRef(0)
  const wantOpen = useRef(false)

  const getToken = useCallback(() => tokenRef.current, [])

  const pushEvent = useCallback((event) => {
    setEvents((previous) => {
      const next = [...previous, event]
      return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next
    })
  }, [])

  const applySnapshot = useCallback((snapshot) => {
    if (!snapshot) return
    setTranscript(snapshot.transcript ?? [])
    setDiagnostic(snapshot.state ?? null)
    setStep(snapshot.step ?? null)
  }, [])

  // -- the socket ---------------------------------------------------------

  const connectSocket = useCallback(() => {
    if (!roomRef.current || !tokenRef.current) return
    const socket = new WebSocket(controlSocketUrl(roomRef.current, tokenRef.current))
    socketRef.current = socket

    socket.addEventListener('open', () => {
      attempt.current = 0
      setStatus('open')
      setError('')
    })

    socket.addEventListener('message', (raw) => {
      let message
      try {
        message = JSON.parse(raw.data)
      } catch {
        return
      }
      switch (message.type) {
        case 'hello':
          applySnapshot(message.snapshot)
          break
        case 'transcript':
          setTranscript((previous) => [...previous, message.line])
          break
        case 'turn.reply':
          setLastReply(message.reply)
          setStep(message.reply.step ?? null)
          setDiagnostic(message.reply.state ?? null)
          setAwaitingReply(false)
          break
        case 'trace':
          pushEvent(message.event)
          break
        case 'error':
          setError(String(message.detail ?? 'server error'))
          setAwaitingReply(false)
          break
        default:
          break
      }
    })

    socket.addEventListener('close', () => {
      if (socketRef.current === socket) socketRef.current = null
      if (!wantOpen.current) {
        setStatus('closed')
        return
      }
      setStatus('reconnecting')
      const delay = BACKOFF_MS[Math.min(attempt.current, BACKOFF_MS.length - 1)]
      attempt.current += 1
      retryTimer.current = window.setTimeout(connectSocket, delay)
    })

    socket.addEventListener('error', () => {
      // `close` always follows, and that is where the retry lives.
      setError((previous) => previous || 'control socket error')
    })
  }, [applySnapshot, pushEvent])

  // -- the token ----------------------------------------------------------

  const scheduleRenewal = useCallback((ttlSeconds) => {
    if (renewTimer.current != null) window.clearTimeout(renewTimer.current)
    const delayMs = Math.max(5, Math.floor(ttlSeconds * RENEW_FRACTION)) * 1000
    renewTimer.current = window.setTimeout(async () => {
      if (!wantOpen.current) return
      try {
        const renewed = await renewToken(roomRef.current, tokenRef.current)
        tokenRef.current = renewed.token
        setTokenExpiresAt(renewed.expires_at)
        setSession((previous) => (previous ? { ...previous, ...renewed } : renewed))
        scheduleRenewal(renewed.ttl_seconds)
      } catch (renewError) {
        setError(`token renewal failed: ${renewError.message}`)
      }
    }, delayMs)
  }, [])

  // -- joining and leaving ------------------------------------------------

  const join = useCallback(async () => {
    setStatus('joining')
    setError('')
    try {
      const minted = await openSession()
      tokenRef.current = minted.token
      roomRef.current = minted.room
      wantOpen.current = true
      attempt.current = 0
      setSession(minted)
      setTokenExpiresAt(minted.expires_at)
      setTranscript([])
      setEvents([])
      setDiagnostic(null)
      setStep(null)
      setLastReply(null)
      connectSocket()
      scheduleRenewal(minted.ttl_seconds)
      return minted
    } catch (joinError) {
      setStatus('error')
      setError(joinError.message)
      throw joinError
    }
  }, [connectSocket, scheduleRenewal])

  const leave = useCallback(() => {
    wantOpen.current = false
    if (renewTimer.current != null) window.clearTimeout(renewTimer.current)
    if (retryTimer.current != null) window.clearTimeout(retryTimer.current)
    renewTimer.current = null
    retryTimer.current = null
    socketRef.current?.close()
    socketRef.current = null
    setStatus('closed')
  }, [])

  useEffect(() => () => leave(), [leave])

  // -- sending ------------------------------------------------------------

  const sendRaw = useCallback((message) => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    socket.send(JSON.stringify(message))
    return true
  }, [])

  /**
   * §1.4.1: a click and a typed string are the *same* event type.
   *
   * The only difference that reaches the wire is the `modality` label, and the
   * server puts that in the trace rather than into the core — which is what
   * makes §7.2's M10 ("same branch whichever modality answered") measurable.
   */
  const sendTurn = useCallback(
    (text, modality = 'typed') => {
      const value = (text ?? '').trim()
      if (!value) return false
      setAwaitingReply(true)
      const sent = sendRaw({ type: 'user.text', text: value, modality })
      if (!sent) {
        setAwaitingReply(false)
        setError('not connected — the turn was not sent')
      }
      return sent
    },
    [sendRaw],
  )

  const sendStats = useCallback(
    (stats) => sendRaw({ type: 'net.stats', ...stats }),
    [sendRaw],
  )

  /**
   * §2.3's typing suppressor, for when there is no media link to carry it.
   *
   * The media plane is the shorter path to the endpointer and is what the page
   * uses when it is up — see `App.jsx`. This is the one that still works while
   * the audio is down, which is the case §2.3 is actually about: someone who
   * stopped speaking to type an SSID.
   */
  const sendTyping = useCallback(() => sendRaw({ type: 'user.typing' }), [sendRaw])

  const sendClientEvent = useCallback(
    (name, fields = {}) => sendRaw({ type: 'client.event', name, ...fields }),
    [sendRaw],
  )

  return {
    session,
    status,
    transcript,
    diagnostic,
    step,
    lastReply,
    events,
    awaitingReply,
    error,
    tokenExpiresAt,
    getToken,
    join,
    leave,
    sendTurn,
    sendStats,
    sendTyping,
    sendClientEvent,
    setError,
  }
}
