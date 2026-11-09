// The page. One room, one caller, four panels.
//
// `docs/06` §1.4 asks for a specific thing and not a chat window: the user can
// *see* what the agent thinks it is working on. So the transcript is one panel
// of four, beside the diagnostic state, the current step and the state of the
// link itself — and the text field is not a fallback for when voice fails but
// a first-class input for "strings the voice channel mangles — SSIDs, serial
// numbers, card markings, error text".
//
// The two planes are kept visibly apart, because they fail apart: the control
// socket carries turns and state, the media link carries audio. Losing the
// microphone does not lose the session, and the UI should not pretend otherwise.
//
// **Two media links, one page (`docs/07` D-02).** The mint says which transport
// this process is running and the page obeys it: `livekit` joins a room on the
// media server (`src/livekit.js`, Phase 3), `smallwebrtc` offers SDP to our own
// process (`src/webrtc.js`, the Phase 2b fallback, kept wired). Everything below
// the `startMedia` call is written against the properties both links share —
// `start`, `stop`, `setMuted`, and the four callbacks — so the panels never
// learn which one is underneath them.

import { useCallback, useEffect, useRef, useState } from 'react'
import { LiveKitLink } from './livekit.js'
import { MediaLink, microphoneAvailable } from './webrtc.js'
import { useSession } from './useSession.js'
import ConnectionBar from './components/ConnectionBar.jsx'
import Transcript from './components/Transcript.jsx'
import Composer from './components/Composer.jsx'
import StatePanel from './components/StatePanel.jsx'
import StepPanel from './components/StepPanel.jsx'
import EventLog from './components/EventLog.jsx'
// Decoration only (`components/Doodles.jsx`): inline SVG, `aria-hidden`, and
// never the label for anything. Every heading below still carries its own
// words, so removing these would cost the page nothing but its face.
import {
  Blob,
  IconState,
  IconStep,
  IconTrace,
  IconTranscript,
  Mascot,
} from './components/Doodles.jsx'

export default function App() {
  const session = useSession()
  const {
    session: minted,
    status,
    sendStats,
    sendClientEvent,
    getToken,
  } = session

  const [pcState, setPcState] = useState('closed')
  const [stats, setStats] = useState(null)
  const [level, setLevel] = useState(null)
  const [segments, setSegments] = useState([])
  const [mediaError, setMediaError] = useState('')
  const [muted, setMuted] = useState(false)
  const [busy, setBusy] = useState(false)
  //: The recogniser's running hypothesis (§1.4: "partials may be shown greyed;
  //: finals replace them"). Lives here rather than in `useSession` because it
  //: arrives on the media plane, and it goes when the final line arrives.
  const [partial, setPartial] = useState(null)
  const [asr, setAsr] = useState(null)

  const mediaRef = useRef(null)
  const audioRef = useRef(null)
  const secure = microphoneAvailable()
  const transport = minted?.transport ?? 'livekit'

  const handleStats = useCallback(
    (sample) => {
      setStats(sample)
      sendStats(sample)
    },
    [sendStats],
  )

  const handleMessage = useCallback((message) => {
    // Media-plane facts, arriving on the media plane: `SpeechReporter` in
    // `server/pipeline.py` on the fallback, the `rove` data topic in
    // `server/livekit_agent.py` on LiveKit. Same shapes either way.
    if (message.type === 'audio.level') {
      setLevel(message)
    } else if (message.type === 'speech.start') {
      setLevel((previous) => ({ ...(previous ?? {}), speaking: true }))
    } else if (message.type === 'speech.end') {
      setLevel((previous) => ({ ...(previous ?? {}), speaking: false }))
      setSegments((previous) => [...previous.slice(-19), message])
    } else if (message.type === 'asr.partial') {
      setPartial(message.text ? message : null)
    } else if (message.type === 'asr.state') {
      // §2.4 tier 4: no recogniser is a typed-only session, not a dead one.
      // The user is told, because a user who can see that the microphone is
      // not being heard will type instead of repeating themselves.
      setAsr(message)
    }
  }, [])

  const startMedia = useCallback(
    async ({ restart = false } = {}) => {
      if (!minted && !restart) return
      const room = mediaRef.current?.room ?? minted?.room
      if (!room) return
      setMediaError('')
      setBusy(true)
      try {
        if (mediaRef.current) await mediaRef.current.stop()
        const common = {
          room,
          getToken,
          onStateChange: setPcState,
          onMessage: handleMessage,
          onStats: handleStats,
          onTrack: (stream) => {
            if (audioRef.current && stream) audioRef.current.srcObject = stream
          },
          onLog: () => {},
        }
        // D-02's two transports. The mint decided which one this process is
        // running; the page does not get a vote and does not need one.
        const link =
          minted?.transport === 'smallwebrtc'
            ? new MediaLink(common)
            : new LiveKitLink({
                ...common,
                url: minted?.livekit_url ?? '',
                getAudioElement: () => audioRef.current,
              })
        mediaRef.current = link
        // `restart` is the LiveKit link's word and `restartPc` the fallback's;
        // each reads the one it knows and ignores the other. The fallback is
        // left on a fresh peer connection rather than a renegotiation, which
        // is what it did in Phase 2b.
        await link.start({
          restart,
          iceServers: minted?.ice_servers ?? [],
        })
        setMuted(false)
        sendClientEvent(restart ? 'media.rejoined' : 'media.started', {
          transport: minted?.transport ?? '',
        })
      } catch (error) {
        setMediaError(error.message)
        sendClientEvent('media.failed', { error: error.message })
      } finally {
        setBusy(false)
      }
    },
    [getToken, handleMessage, handleStats, minted, sendClientEvent],
  )

  const handleJoin = useCallback(async () => {
    setBusy(true)
    try {
      await session.join()
    } catch {
      // `useSession` has already surfaced it.
    } finally {
      setBusy(false)
    }
  }, [session])

  // The microphone is asked for once the room exists, not before: a permission
  // prompt with nothing behind it is a prompt the user is right to refuse.
  useEffect(() => {
    if (status === 'open' && minted && !mediaRef.current && secure) {
      startMedia()
    }
  }, [minted, secure, startMedia, status])

  const dropMedia = useCallback(async () => {
    sendClientEvent('media.dropped_by_user')
    await mediaRef.current?.stop()
    mediaRef.current = null
    setPcState('closed')
    setStats(null)
    setLevel(null)
    setPartial(null)
  }, [sendClientEvent])

  // The drop-and-rejoin of `client/README.md`. On LiveKit this is a fresh room
  // connection rather than a renegotiation, and it costs nothing that matters:
  // `DiagnosticState` is server-side (§1.4.2), so the transcript, the step and
  // the state panel are exactly where they were.
  const rejoinMedia = useCallback(async () => {
    await startMedia({ restart: true })
  }, [startMedia])

  const leave = useCallback(async () => {
    await mediaRef.current?.stop()
    mediaRef.current = null
    setPcState('closed')
    setStats(null)
    setLevel(null)
    setSegments([])
    setPartial(null)
    setAsr(null)
    session.leave()
  }, [session])

  const toggleMute = useCallback(() => {
    setMuted((previous) => {
      const next = !previous
      mediaRef.current?.setMuted(next)
      sendClientEvent(next ? 'mic.muted' : 'mic.unmuted')
      return next
    })
  }, [sendClientEvent])

  /**
   * §2.3's one signal a phone call does not have.
   *
   * Someone part-way through typing an SSID has not finished their turn, and
   * the endpointer is told so rather than inferring it from silence. It goes
   * down the media link's data topic when there is one — that is the path
   * `server/livekit_peer.py` stands in for — and falls back to the control
   * socket, which reaches the same `note_typing`.
   */
  const noteTyping = useCallback(() => {
    if (mediaRef.current?.sendTyping?.()) return
    session.sendTyping()
  }, [session])

  // §1.4: "finals replace them". The final arrives as a transcript line on the
  // control socket, so the hypothesis is cleared by the line that supersedes it.
  useEffect(() => {
    setPartial(null)
  }, [session.transcript.length])

  useEffect(() => {
    const link = mediaRef.current
    return () => {
      link?.stop()
    }
  }, [])

  return (
    <div className="app">
      <Blob className="blob blob-one" />
      <Blob className="blob blob-two" />

      <header className="masthead">
        <div className="masthead-brand">
          <Mascot className="mascot" />
          <div>
            <h1>Rove troubleshooting</h1>
            <p className="subtitle">
              {transport === 'livekit'
                ? 'Phase 3 — the browser joins a LiveKit room. Speech is segmented by Silero VAD, transcribed by Amazon Transcribe and ended by the §2.3 endpointer. Speak, type or click to answer.'
                : 'Phase 2b fallback — SmallWebRTC, peer connection in the API process. Speech is captured and segmented; it is not transcribed on this transport. Type or click to answer.'}
            </p>
          </div>
        </div>
        <ConnectionBar
          status={status}
          pcState={pcState}
          stats={stats}
          level={level}
          segments={segments}
          minted={minted}
          tokenExpiresAt={session.tokenExpiresAt}
          secure={secure}
          muted={muted}
          busy={busy}
          onJoin={handleJoin}
          onLeave={leave}
          onDropMedia={dropMedia}
          onRejoinMedia={rejoinMedia}
          onToggleMute={toggleMute}
        />
      </header>

      {(session.error || mediaError) && (
        <div className="banner banner-error">
          {session.error && <div>{session.error}</div>}
          {mediaError && <div>microphone / transport: {mediaError}</div>}
          {!secure && (
            <div>
              This page is not a secure context, so the browser will not grant a microphone.
              Open it over HTTPS or at <code>http://localhost</code> — see{' '}
              <code>client/README.md</code>.
            </div>
          )}
        </div>
      )}

      {asr && asr.available === false && (
        <div className="banner banner-error">
          <div>
            The recogniser is not available, so this session is typed-only
            {asr.detail ? `: ${asr.detail}` : '.'} Everything else — the step, the state and
            the agent's voice — still works.
          </div>
        </div>
      )}

      <main className="grid">
        <section className="panel panel-transcript">
          <h2>
            <IconTranscript className="panel-icon" />
            Transcript
          </h2>
          <Transcript
            lines={session.transcript}
            awaiting={session.awaitingReply}
            partial={partial}
          />
          <Composer
            disabled={status !== 'open'}
            awaiting={session.awaitingReply}
            step={session.step}
            onSend={session.sendTurn}
            onTyping={noteTyping}
          />
        </section>

        <section className="panel panel-step">
          <h2>
            <IconStep className="panel-icon" />
            Current step
          </h2>
          <StepPanel step={session.step} reply={session.lastReply} />
        </section>

        <section className="panel panel-state">
          <h2>
            <IconState className="panel-icon" />
            Diagnostic state
          </h2>
          <StatePanel state={session.diagnostic} />
        </section>

        <section className="panel panel-events">
          <h2>
            <IconTrace className="panel-icon" />
            Session trace
          </h2>
          <EventLog events={session.events} />
        </section>
      </main>

      {/* The agent's voice. Muted-by-default autoplay is blocked in every
          browser, so this element is unmuted and only ever carries server
          audio the user asked for by joining. */}
      <audio ref={audioRef} autoPlay playsInline />
    </div>
  )
}
