// The media leg, Phase 3: the browser joins a **LiveKit room** (`docs/07` D-02).
//
// `src/webrtc.js` is this file's Phase 2b sibling and is still here, still
// wired, because D-02 keeps Pipecat as the documented fallback rather than
// deleting it. The difference between the two is the whole of what D-02 bought:
//
// * **Phase 2b** — the page offers SDP to `/api/offer`, our process answers,
//   and the peer connection terminates *in* the API process. One caller, one
//   `RTCPeerConnection`, and a second participant is a rewrite.
// * **Phase 3** — the page takes the credential `POST /api/session` minted
//   (`server/livekit_tokens.py`: HS256, one room, one identity, minutes) and
//   presents it to the **media server**. The agent is another participant in
//   the same room (`server/livekit_agent.py`), and §5.3's human support seat
//   is one more `mint()` call with a different identity.
//
// What rides on the room is exactly what rode on the peer connection, so the
// panels did not have to change:
//
// * **up** — the microphone, published as one audio track, Opus, 20 ms frames;
// * **down** — the agent's voice track, subscribed and attached to the page's
//   one `<audio>` element;
// * **the `rove` data topic** — audio levels, Silero speech segments, ASR
//   partials and the §2.3 endpoint decisions. Facts about the media path,
//   travelling on the media path, as they did on the Pipecat data channel.
//
// Everything else — typed turns, the diagnostic state, the transcript — is
// still on the control socket in `useSession.js`, which is why the four panels
// keep rendering while this connection is down.
//
// `server/livekit_peer.py` is the headless stand-in for this file: same join,
// same publish, same subscribe, same topic. When it is green and the browser is
// red, the difference is the browser rather than the protocol.

import { ConnectionState, Room, RoomEvent, Track } from 'livekit-client'
import { summariseStats } from './stats.js'

/** How often the page samples its own view of the link. Same as Phase 2b. */
const STATS_PERIOD_MS = 2000

/** The data topic the agent publishes on (`server/livekit_agent.py:TOPIC`). */
export const TOPIC = 'rove'

/**
 * LiveKit's connection states, said in the vocabulary the connection bar
 * already speaks (`components/ConnectionBar.jsx:PC_TONE`). A reconnect is a
 * *warning* and not a failure: §1.4.2 says "reconnection is expected, not
 * exceptional", and the SDK recovers from it without the page doing anything.
 */
const STATE_NAMES = {
  [ConnectionState.Connected]: 'connected',
  [ConnectionState.Connecting]: 'connecting',
  [ConnectionState.Reconnecting]: 'connecting',
  [ConnectionState.SignalReconnecting]: 'connecting',
  [ConnectionState.Disconnected]: 'disconnected',
}

export class LiveKitLink {
  /**
   * @param {object} options
   * @param {string} options.url Where the media server is. Comes down with the
   *   mint (`MintedSession.livekit_url`), so the page has no build-time config.
   * @param {string} options.room The room the token was minted for.
   * @param {() => string} options.getToken The current join token. Read at
   *   `start()` rather than held, because `useSession` renews it under us.
   * @param {() => (HTMLAudioElement|null)} [options.getAudioElement] Where the
   *   agent's voice should play.
   */
  constructor({
    url,
    room,
    getToken,
    onStateChange,
    onMessage,
    onStats,
    onTrack,
    onLog,
    getAudioElement,
  }) {
    this.url = url
    this.room = room
    this.getToken = getToken
    this.onStateChange = onStateChange ?? (() => {})
    this.onMessage = onMessage ?? (() => {})
    this.onStats = onStats ?? (() => {})
    this.onTrack = onTrack ?? (() => {})
    this.onLog = onLog ?? (() => {})
    this.getAudioElement = getAudioElement ?? (() => null)

    this.lkRoom = null
    this.remoteTrack = null
    this.statsTimer = null
    this.closed = false
  }

  get connectionState() {
    if (this.closed || this.lkRoom == null) return 'closed'
    return STATE_NAMES[this.lkRoom.state] ?? 'closed'
  }

  /**
   * Join the room, take the microphone, publish it.
   *
   * `restart` drops the room and re-joins rather than renegotiating — the
   * drop-and-rejoin path. The *session* is unchanged either way, because
   * `DiagnosticState` is server-side (§1.4.2) and the control socket never
   * went down.
   */
  async start({ restart = false } = {}) {
    if (this.lkRoom) await this.stop({ quiet: true })
    this.closed = false

    const lkRoom = new Room({
      // Browser AEC with the true playout reference is the whole reason §8.1
      // chose WebRTC over anything simpler, and it is what makes Phase 3's
      // barge-in (Milestone 6.2) possible at all. Ask for it explicitly rather
      // than inheriting whatever the SDK's defaults happen to be.
      audioCaptureDefaults: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
      // One audio track each way and nothing else: there is no video to adapt
      // and no second subscriber to pause a layer for.
      adaptiveStream: false,
      dynacast: false,
      disconnectOnPageLeave: true,
    })
    this.lkRoom = lkRoom

    lkRoom.on(RoomEvent.ConnectionStateChanged, (state) => {
      this.onStateChange(STATE_NAMES[state] ?? 'closed')
      if (state === ConnectionState.Disconnected) this.stopStatsLoop()
    })
    lkRoom.on(RoomEvent.Disconnected, (reason) => {
      this.onLog(`room disconnected: ${reason ?? 'no reason given'}`)
      this.onStateChange(this.closed ? 'closed' : 'disconnected')
      this.stopStatsLoop()
    })
    lkRoom.on(RoomEvent.Reconnecting, () => this.onLog('room: reconnecting'))
    lkRoom.on(RoomEvent.Reconnected, () => this.onLog('room: reconnected'))
    lkRoom.on(RoomEvent.MediaDevicesError, (error) =>
      this.onLog(`media devices: ${error?.message ?? error}`),
    )

    lkRoom.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
      if (track.kind !== Track.Kind.Audio) return
      this.remoteTrack = track
      this.onLog(`subscribed to ${participant.identity} (${publication.trackSid})`)
      this.attachAudio()
    })
    lkRoom.on(RoomEvent.TrackUnsubscribed, (track) => {
      if (track !== this.remoteTrack) return
      try {
        track.detach()
      } catch {
        /* already gone */
      }
      this.remoteTrack = null
    })

    // The `rove` topic, which is the Pipecat data channel by another name.
    lkRoom.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic && topic !== TOPIC) return
      try {
        this.onMessage(JSON.parse(new TextDecoder().decode(payload)))
      } catch {
        this.onLog('data topic: unparsable message')
      }
    })

    // Autoplay: clicking **Join room** is the gesture that lets the browser
    // play the greeting, but a tab that was never focused can still refuse.
    // Say so rather than letting the agent appear mute.
    lkRoom.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (!lkRoom.canPlaybackAudio) this.onLog('audio playback is blocked — click the page')
    })

    await lkRoom.connect(this.url, this.getToken())
    // Publishing is separate from joining, so a refused microphone is a room
    // we are in with nothing to say rather than a failed join.
    await lkRoom.localParticipant.setMicrophoneEnabled(true)
    this.attachAudio()
    try {
      await lkRoom.startAudio()
    } catch {
      /* reported through AudioPlaybackStatusChanged */
    }
    this.onLog(restart ? 'room re-joined' : 'room joined')
    this.onStateChange(STATE_NAMES[lkRoom.state] ?? 'connecting')
    this.startStatsLoop()
    return {
      room: lkRoom.name,
      identity: lkRoom.localParticipant.identity,
      participants: lkRoom.remoteParticipants.size,
    }
  }

  /**
   * Put the agent's voice in the page's one `<audio>` element.
   *
   * `track.attach(element)` rather than a raw `srcObject`: the SDK keeps the
   * element in `attachedElements`, which is what `room.startAudio()` unblocks
   * when a browser refuses autoplay. Handing the element a `MediaStream`
   * ourselves would work until it did not, and then silently.
   */
  attachAudio() {
    const element = this.getAudioElement()
    if (!element || !this.remoteTrack) return
    this.remoteTrack.attach(element)
    this.onTrack(element.srcObject ?? null)
  }

  /** §2.3's typing suppressor, on the same topic the agent reads. */
  sendTyping() {
    const lkRoom = this.lkRoom
    if (!lkRoom || lkRoom.state !== ConnectionState.Connected) return false
    lkRoom.localParticipant
      .publishData(new TextEncoder().encode(JSON.stringify({ type: 'user.typing' })), {
        reliable: true,
        topic: TOPIC,
      })
      .catch((error) => this.onLog(`typing signal failed: ${error.message}`))
    return true
  }

  // -- the link's own numbers ---------------------------------------------

  /**
   * RTT, jitter and loss, from the room rather than from one peer connection.
   *
   * LiveKit is an SFU, so there are two transports and the numbers live on
   * both: the inbound stream (the agent's voice, and the jitter buffer §2.2
   * line 9 is about) is on the subscriber, and the outbound stream plus the
   * SFU's RTCP report of our uplink is on the publisher. Both reports are
   * merged into one and reduced by the *same* `summariseStats` the Phase 2b
   * path uses — so the `net.client_stats` trace records mean the same thing on
   * both transports and the unit trap in `stats.js` is handled once.
   *
   * Ids are namespaced on the way in because the two reports number their
   * entries independently and a collision would silently drop a stream.
   */
  async sampleStats() {
    const lkRoom = this.lkRoom
    if (!lkRoom) return null
    const sources = []
    const microphone = lkRoom.localParticipant.getTrackPublication(Track.Source.Microphone)
    if (microphone?.track) sources.push(['up', microphone.track])
    if (this.remoteTrack) sources.push(['down', this.remoteTrack])
    if (!sources.length) return null

    const merged = new Map()
    for (const [leg, track] of sources) {
      let report
      try {
        report = await track.getRTCStatsReport()
      } catch (error) {
        this.onLog(`getStats(${leg}) failed: ${error.message}`)
        continue
      }
      report?.forEach((entry, id) => merged.set(`${leg}:${id}`, entry))
    }
    if (!merged.size) return null
    return { ...summariseStats(merged), connection_state: this.connectionState }
  }

  startStatsLoop() {
    this.stopStatsLoop()
    this.statsTimer = window.setInterval(async () => {
      if (!this.lkRoom || this.lkRoom.state !== ConnectionState.Connected) return
      const sample = await this.sampleStats()
      if (sample) this.onStats(sample)
    }, STATS_PERIOD_MS)
  }

  stopStatsLoop() {
    if (this.statsTimer != null) {
      window.clearInterval(this.statsTimer)
      this.statsTimer = null
    }
  }

  // -- leaving -------------------------------------------------------------

  /** Leave the room and let go of the microphone. Both, or neither. */
  async stop({ quiet = false } = {}) {
    this.closed = true
    this.stopStatsLoop()
    const lkRoom = this.lkRoom
    this.lkRoom = null
    if (this.remoteTrack) {
      try {
        this.remoteTrack.detach()
      } catch {
        /* already gone */
      }
      this.remoteTrack = null
    }
    if (lkRoom) {
      try {
        // `stopTracks` is the default and is what we want: the microphone goes
        // back to the browser, so the tab stops showing a recording indicator
        // for a room nobody is in.
        await lkRoom.disconnect()
      } catch {
        /* already gone */
      }
    }
    if (!quiet) this.onStateChange('closed')
  }

  /** Mute without leaving — the track stays published, silently. */
  setMuted(muted) {
    const lkRoom = this.lkRoom
    if (!lkRoom) return
    lkRoom.localParticipant
      .setMicrophoneEnabled(!muted)
      .catch((error) => this.onLog(`mute failed: ${error.message}`))
  }
}
