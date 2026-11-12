// The media leg, Phase 2b: one `RTCPeerConnection` to the Python process.
//
// **This is the fallback path.** Phase 3 promoted the transport to LiveKit and
// `src/livekit.js` is what the page uses when the mint says `transport:
// "livekit"` — which is the default. `docs/07` D-02 keeps Pipecat wired rather
// than deleted, so this stays here, stays correct, and is one
// `ROVE_TRANSPORT=smallwebrtc` away from being the live path again.
//
// This is the browser half of what `server/headless_peer.py` does from Python,
// and deliberately the same shape, so that a green headless test and a red
// browser mean the difference is the browser rather than the protocol.
//
// Three things ride on this connection and nothing else does:
//
// * **up** — the microphone, Opus, 20 ms frames;
// * **down** — whatever the server speaks (Phase 2b: one Polly greeting);
// * **a data channel** — speech segments and audio levels from the server-side
//   Silero VAD. Those are facts about the media path, so they travel on it.
//
// Everything else — typed turns, the diagnostic state, the transcript — is on
// the control socket in `useSession.js`, which is why the panels keep
// rendering while this connection is down.

import { postCandidates, postOffer } from './api.js'
import { summariseStats } from './stats.js'

/** How often the page samples its own view of the link. */
const STATS_PERIOD_MS = 2000

export class MediaLink {
  constructor({ room, getToken, onStateChange, onMessage, onStats, onTrack, onLog }) {
    this.room = room
    this.getToken = getToken
    this.onStateChange = onStateChange ?? (() => {})
    this.onMessage = onMessage ?? (() => {})
    this.onStats = onStats ?? (() => {})
    this.onTrack = onTrack ?? (() => {})
    this.onLog = onLog ?? (() => {})

    this.pc = null
    this.pcId = null
    this.stream = null
    this.channel = null
    this.statsTimer = null
    this.pendingCandidates = []
    this.closed = false
  }

  get connectionState() {
    return this.pc?.connectionState ?? 'closed'
  }

  /**
   * Take the microphone, offer, and come up.
   *
   * `restartPc` asks the server for a fresh peer connection rather than a
   * renegotiation — the drop-and-rejoin path. The room, and so the
   * `DiagnosticState`, is unchanged either way.
   */
  async start({ restartPc = false, iceServers = [] } = {}) {
    this.closed = false
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // Browser AEC with the true playout reference is the whole reason
        // §8.1 chose WebRTC over anything simpler, and it is what makes
        // Phase 3's barge-in possible at all. Ask for it explicitly.
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
      video: false,
    })

    const pc = new RTCPeerConnection({ iceServers })
    this.pc = pc

    pc.addEventListener('connectionstatechange', () => {
      this.onStateChange(pc.connectionState)
      if (['failed', 'closed', 'disconnected'].includes(pc.connectionState)) {
        this.stopStatsLoop()
      }
    })
    pc.addEventListener('iceconnectionstatechange', () => {
      this.onLog(`ice: ${pc.iceConnectionState}`)
    })
    pc.addEventListener('track', (event) => {
      this.onTrack(event.streams[0] ?? new MediaStream([event.track]))
    })
    pc.addEventListener('icecandidate', (event) => {
      if (!event.candidate) return
      this.pendingCandidates.push({
        candidate: event.candidate.candidate,
        sdpMid: event.candidate.sdpMid,
        sdpMLineIndex: event.candidate.sdpMLineIndex,
      })
      this.flushCandidates()
    })

    this.channel = pc.createDataChannel('rove')
    this.channel.addEventListener('message', (event) => {
      try {
        this.onMessage(JSON.parse(event.data))
      } catch {
        this.onLog(`data channel: unparsable message`)
      }
    })

    for (const track of this.stream.getAudioTracks()) {
      pc.addTrack(track, this.stream)
    }

    const offer = await pc.createOffer({ offerToReceiveAudio: true })
    await pc.setLocalDescription(offer)

    const answer = await postOffer({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      room: this.room,
      token: this.getToken(),
      pcId: restartPc ? this.pcId : null,
      restartPc,
    })
    this.pcId = answer.pc_id ?? null
    await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type })
    this.flushCandidates()
    this.startStatsLoop()
    return answer
  }

  flushCandidates() {
    if (!this.pcId || !this.pendingCandidates.length) return
    const batch = this.pendingCandidates.splice(0, this.pendingCandidates.length)
    postCandidates({
      room: this.room,
      token: this.getToken(),
      pcId: this.pcId,
      candidates: batch,
    }).catch((error) => this.onLog(`ice post failed: ${error.message}`))
  }

  startStatsLoop() {
    this.stopStatsLoop()
    this.statsTimer = window.setInterval(async () => {
      if (!this.pc || this.pc.connectionState === 'closed') return
      try {
        const report = await this.pc.getStats()
        this.onStats({
          ...summariseStats(report),
          connection_state: this.pc.connectionState,
        })
      } catch (error) {
        this.onLog(`getStats failed: ${error.message}`)
      }
    }, STATS_PERIOD_MS)
  }

  stopStatsLoop() {
    if (this.statsTimer != null) {
      window.clearInterval(this.statsTimer)
      this.statsTimer = null
    }
  }

  /** Let go of the microphone as well as the socket. Both, or neither. */
  async stop() {
    this.closed = true
    this.stopStatsLoop()
    if (this.channel) {
      try {
        this.channel.close()
      } catch {
        /* already gone */
      }
      this.channel = null
    }
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop()
      this.stream = null
    }
    if (this.pc) {
      try {
        this.pc.close()
      } catch {
        /* already gone */
      }
      this.pc = null
    }
    this.onStateChange('closed')
  }

  /** Mute without dropping the connection — the mic stays ours, silently. */
  setMuted(muted) {
    if (!this.stream) return
    for (const track of this.stream.getAudioTracks()) track.enabled = !muted
  }
}

/**
 * `getUserMedia` needs a secure context: HTTPS, or `localhost`.
 *
 * Opening the page at `http://<ip>:8080` from another machine gives a page
 * that renders and types fine and a microphone that silently does not exist.
 * Naming that here means the UI can say so instead of the user guessing.
 */
export function microphoneAvailable() {
  return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia)
}
