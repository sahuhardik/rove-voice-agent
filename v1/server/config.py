"""Settings for the server, all from the environment.

One documented port (:data:`DEFAULT_PORT`) bound on ``0.0.0.0``, so a browser
outside this host can reach the session. Everything else has a working default
so that ``.venv/bin/python -m server`` is the whole operation.

**One setting decides the shape of the process**: :attr:`Settings.transport`.

``livekit`` (the default) is `docs/07` D-02's production target — the browser
joins a **room** on a media server, and the agent worker joins the same room as
a participant. ``smallwebrtc`` is D-02's documented fallback: a Pipecat peer
connection inside this process, one dependency, nothing to operate. D-02 keeps
both deliberately:

> **Pipecat is not discarded — it is the Phase 3 spike and the fallback.**

So neither path is a build flag that rots. Both are wired, both are tested, and
flipping `ROVE_TRANSPORT` is the whole of the flip condition D-02 describes.
"""

from __future__ import annotations

import os
import re
import secrets
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from server import livekit_tokens, tokens, transcribe

#: The one documented port. HTTP, WebSocket and WebRTC signalling all live on
#: it; the media itself is UDP on ephemeral ports, which `server/README.md`
#: spells out because it is the part that surprises people.
DEFAULT_PORT = 8080
DEFAULT_HOST = "0.0.0.0"

#: Polly, Neural engine (`docs/07` D-10 — pinned, governed by IAM rather than
#: by the Bedrock access question, so C-2 does not gate it).
DEFAULT_POLLY_VOICE = "Amy"
DEFAULT_POLLY_ENGINE = "neural"
DEFAULT_GREETING = (
    "You're connected to the Rove troubleshooting assistant. "
    "I can hear you — tell me what the camera is doing, or type it instead."
)

#: 16 kHz both ways: what Silero VAD v5 wants, what Amazon Transcribe
#: Streaming takes, and what Polly will return as PCM. Nothing resamples.
AUDIO_SAMPLE_RATE = 16000

#: The two transports D-02 keeps. `livekit` is the production target; the
#: Pipecat peer-in-process path is the documented fallback and stays wired.
TRANSPORT_LIVEKIT = "livekit"
TRANSPORT_SMALLWEBRTC = "smallwebrtc"
TRANSPORTS = (TRANSPORT_LIVEKIT, TRANSPORT_SMALLWEBRTC)

#: Where a `livekit-server --dev` on this host answers.
DEFAULT_LIVEKIT_URL = "ws://127.0.0.1:7880"

REPO_ROOT = Path(__file__).resolve().parent.parent


def _flag(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _detect_public_ip(timeout: float = 2.0) -> str:
    """Ask EC2's metadata service for this host's public address.

    Only used when ``ROVE_PUBLIC_IP=auto``. A host behind 1:1 NAT — which is
    every EC2 instance with a public IP — gathers ICE candidates holding its
    *private* address, and a browser elsewhere cannot reach those. See
    `server/sdp.py`.
    """
    try:
        token_request = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        imds_token = urllib.request.urlopen(token_request, timeout=timeout).read().decode()
        address_request = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/public-ipv4",
            headers={"X-aws-ec2-metadata-token": imds_token},
        )
        return urllib.request.urlopen(address_request, timeout=timeout).read().decode().strip()
    except Exception:  # noqa: BLE001 — not on EC2, or no public address
        return ""


#: A bare `name`, `v4` or `[v6]` with an optional port: nothing that could
#: smuggle a path, userinfo or query into the URL built from a Host header.
_HOST_RE = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?")


@dataclass(frozen=True)
class Settings:
    """Everything the process needs, resolved once at startup."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    #: Signing secret for the join tokens. Generated per process when unset,
    #: which is correct for a spike and wrong for two processes behind a load
    #: balancer — `server/README.md` says so.
    token_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    token_secret_is_ephemeral: bool = True
    token_ttl_seconds: int = tokens.DEFAULT_TTL_SECONDS
    #: The one gate on minting a support **observer** token (`docs/06` §5.3).
    #: Generated per process when unset, for the same reason `token_secret` is
    #: and with the same caveat: it is right for a console nobody has deployed
    #: and wrong the moment two processes are behind a load balancer. §9.3
    #: item 2 owns what replaces it — whatever the support organisation
    #: already authenticates its people with.
    support_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    support_key_is_ephemeral: bool = True
    #: Observer tokens are short-lived on the same principle as join tokens
    #: (§1.4.2) and capped by the same ceiling in `tokens.py`. A session a
    #: human is working lasts longer than one of these; the console re-mints,
    #: and the credential on the wire is never valid for more than one TTL.
    observer_ttl_seconds: int = tokens.DEFAULT_TTL_SECONDS
    #: The address to advertise in ICE candidates, for a host behind 1:1 NAT.
    public_ip: str = ""
    ice_servers: tuple[str, ...] = ()
    trace_dir: Path = REPO_ROOT / "data" / "traces" / "phase2b"
    polly_voice: str = DEFAULT_POLLY_VOICE
    polly_engine: str = DEFAULT_POLLY_ENGINE
    polly_cache_dir: Path = REPO_ROOT / "data" / "cache" / "polly"
    greeting_text: str = DEFAULT_GREETING
    #: Whether the typed turn calls Bedrock. The core degrades to its
    #: rule-based floor without it (`agent/core.py`), so a server with no AWS
    #: reach still answers.
    use_llm: bool = True
    chunks_path: str | None = None
    audio_sample_rate: int = AUDIO_SAMPLE_RATE
    #: Silero VAD v5 hangover (`docs/06` §2.2 line 2, §2.3). Phase 2b reports
    #: segments with it; Phase 3 is where it becomes context-dependent.
    vad_start_secs: float = 0.2
    vad_stop_secs: float = 0.6
    vad_confidence: float = 0.7
    client_dist: Path = REPO_ROOT / "client" / "dist"
    #: The support console's build output (`support/build.mjs`). Served at
    #: `/support` by the same process, so there is still one thing to run.
    console_dist: Path = REPO_ROOT / "support" / "dist"
    tls_certfile: str = ""
    tls_keyfile: str = ""
    #: How often each side samples RTT/jitter/loss into the trace.
    stats_period_secs: float = 5.0

    # -- LiveKit (`docs/07` D-02) -----------------------------------------
    #: Which transport this process runs. See the module docstring.
    transport: str = TRANSPORT_LIVEKIT
    #: Where the media server is. Handed to the browser in the mint response
    #: so the page needs no build-time configuration (`docs/06` §1.4.2).
    livekit_url: str = DEFAULT_LIVEKIT_URL
    #: The key pair the media server knows us by. Defaults to the **published**
    #: `--dev` pair; see `livekit_keys_are_dev` and `server/livekit_dev.py`.
    livekit_api_key: str = livekit_tokens.DEV_API_KEY
    livekit_api_secret: str = livekit_tokens.DEV_API_SECRET
    #: Whether we are running on the dev key pair. Printed at startup, reported
    #: on `/healthz`, and written into the trace — because a credential that is
    #: in LiveKit's own documentation must never be silently in production.
    livekit_keys_are_dev: bool = True
    #: Run the agent worker inside this process. The worker joins each room as
    #: a participant; in-process is what lets it reach the server-side
    #: `DiagnosticState` directly (`server/README.md` says what changes if it
    #: does not).
    livekit_worker_inprocess: bool = True

    # -- Amazon Transcribe Streaming (`docs/07` D-05) ---------------------
    #: Whether the voice path transcribes. Off, a session is typed-only and
    #: every other part of the pipeline still runs — which is what makes the
    #: hermetic tests possible without AWS.
    use_transcribe: bool = True
    #: The custom-vocabulary name (`server/transcribe.py` layer 1). Empty
    #: disables biasing; the recogniser still runs.
    transcribe_vocabulary: str = transcribe.DEFAULT_VOCABULARY_NAME
    #: Create or refresh the vocabulary at startup. Idempotent and non-fatal.
    transcribe_ensure_vocabulary: bool = True
    transcribe_region: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        secret = env.get("ROVE_TOKEN_SECRET", "").strip()
        support_key = env.get("ROVE_SUPPORT_KEY", "").strip()
        public_ip = env.get("ROVE_PUBLIC_IP", "").strip()
        if public_ip.lower() == "auto":
            public_ip = _detect_public_ip()
        ice = tuple(
            url.strip() for url in env.get("ROVE_ICE_SERVERS", "").split(",") if url.strip()
        )
        trace_dir = env.get("ROVE_TRACE_DIR", "").strip()
        chunks_path = env.get("ROVE_CHUNKS_PATH", "").strip()

        transport = env.get("ROVE_TRANSPORT", TRANSPORT_LIVEKIT).strip().lower()
        if transport not in TRANSPORTS:
            raise ValueError(
                f"ROVE_TRANSPORT must be one of {', '.join(TRANSPORTS)}, got {transport!r}"
            )
        # Absent a real key pair we fall back to LiveKit's published `--dev`
        # one, because a local loop that refuses to start teaches nobody
        # anything. What must never happen is that fact being invisible, so it
        # is carried as a field rather than inferred later.
        api_key = env.get("ROVE_LIVEKIT_API_KEY", "").strip()
        api_secret = env.get("ROVE_LIVEKIT_API_SECRET", "").strip()
        keys_are_dev = not (api_key and api_secret)
        if keys_are_dev:
            api_key, api_secret = livekit_tokens.DEV_API_KEY, livekit_tokens.DEV_API_SECRET

        # `ROVE_TRANSCRIBE_VOCABULARY=none` turns biasing off, which is how the
        # §8.2 "biasing behaviour on our confusables is unmeasured" claim gets
        # measured: run the same utterance with and without it.
        vocabulary = env.get(
            "ROVE_TRANSCRIBE_VOCABULARY", transcribe.DEFAULT_VOCABULARY_NAME
        ).strip()
        if vocabulary.lower() in ("none", "off", "-"):
            vocabulary = ""

        return cls(
            host=env.get("ROVE_WEB_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=int(env.get("ROVE_WEB_PORT", DEFAULT_PORT)),
            token_secret=secret or secrets.token_urlsafe(32),
            token_secret_is_ephemeral=not secret,
            token_ttl_seconds=int(env.get("ROVE_TOKEN_TTL_SECONDS", tokens.DEFAULT_TTL_SECONDS)),
            support_key=support_key or secrets.token_urlsafe(24),
            support_key_is_ephemeral=not support_key,
            observer_ttl_seconds=int(
                env.get("ROVE_OBSERVER_TTL_SECONDS", tokens.DEFAULT_TTL_SECONDS)
            ),
            public_ip=public_ip,
            ice_servers=ice,
            trace_dir=Path(trace_dir) if trace_dir else cls.trace_dir,
            polly_voice=env.get("ROVE_POLLY_VOICE", DEFAULT_POLLY_VOICE).strip(),
            polly_engine=env.get("ROVE_POLLY_ENGINE", DEFAULT_POLLY_ENGINE).strip(),
            greeting_text=env.get("ROVE_GREETING_TEXT", DEFAULT_GREETING),
            use_llm=_flag(env, "ROVE_USE_LLM", True),
            chunks_path=chunks_path or None,
            tls_certfile=env.get("ROVE_TLS_CERT", "").strip(),
            tls_keyfile=env.get("ROVE_TLS_KEY", "").strip(),
            transport=transport,
            livekit_url=env.get("ROVE_LIVEKIT_URL", DEFAULT_LIVEKIT_URL).strip()
            or DEFAULT_LIVEKIT_URL,
            livekit_api_key=api_key,
            livekit_api_secret=api_secret,
            livekit_keys_are_dev=keys_are_dev,
            livekit_worker_inprocess=_flag(env, "ROVE_LIVEKIT_WORKER_INPROCESS", True),
            use_transcribe=_flag(env, "ROVE_USE_TRANSCRIBE", True),
            transcribe_vocabulary=vocabulary,
            transcribe_ensure_vocabulary=_flag(env, "ROVE_TRANSCRIBE_ENSURE_VOCABULARY", True),
            transcribe_region=env.get("ROVE_TRANSCRIBE_REGION", "").strip(),
        )

    @property
    def scheme(self) -> str:
        return "https" if self.tls_certfile and self.tls_keyfile else "http"

    def livekit_public_url(self, scheme: str, host: str) -> str:
        """The signalling URL to hand a browser that reached us over `scheme`.

        Over https the page may not open `ws://`, so it gets `wss://{host}/lk`,
        which `server/livekit_relay.py` forwards to `livekit_url`. Over http (or
        for a `host` that is not a bare `name[:port]`) it gets `livekit_url`
        unchanged. The media (ICE/UDP) path never uses this URL.
        """
        if scheme != "https" or not _HOST_RE.fullmatch(host or ""):
            return self.livekit_url
        return f"wss://{host}/lk"

    @property
    def is_livekit(self) -> bool:
        return self.transport == TRANSPORT_LIVEKIT

    def ice_server_payload(self) -> list[dict[str, Any]]:
        """ICE servers in the shape `RTCPeerConnection` takes them."""
        return [{"urls": url} for url in self.ice_servers]
