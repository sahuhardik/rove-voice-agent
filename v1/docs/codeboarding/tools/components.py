"""The component model: the single source of truth for docs/codeboarding.

Authored by reading the code (see ../README.md, "How this was produced"), in the
shape CodeBoarding's analysis.json uses. build.py renders every output from this
file and resolves line numbers from the code itself; check.py verifies that every
file, symbol and evidence reference named here exists.

Conventions
- `files`: [(repo path, [qualified symbols])]. Symbols are verified by check.py.
- `evidence`: "path:symbol" citations that justify a relation (an import or a call).
- No component is listed unless it has files in this repo.
"""

from __future__ import annotations

DESCRIPTION = (
    "Rove is a voice troubleshooting agent for a consumer dash-cam line. A React page "
    "joins a LiveKit room; a Python agent worker in the FastAPI process hears the caller "
    "(Amazon Transcribe), decides when the turn has ended, and speaks (Amazon Polly). Every "
    "turn runs through a LangGraph state machine that retrieves Tier-1 chunks from Postgres "
    "plus pgvector, filters the legal next steps in code, lets a Bedrock Nova model choose "
    "among them, and passes the result through a deterministic output guard. The corpus is "
    "built offline by ingest/, the whole system is scored by three eval harnesses, an https "
    "page reaches the media server through a same-origin wss relay, and a separate support "
    "console can join a live session."
)

COMPONENTS = [
    # ------------------------------------------------------------------ 1
    {
        "name": "React Client",
        "description": (
            "The browser page (Vite + React 18, `livekit-client` as the only runtime "
            "dependency besides React). It renders a projection of the server's diagnostic "
            "state in four panels and offers click-or-type next to the voice channel. It "
            "never owns state: a reload loses nothing."
        ),
        "subs": [
            {
                "name": "Session Control Plane",
                "description": (
                    "One WebSocket plus the REST calls that start it. `api.js` mints the "
                    "session and renews the token; `useSession` holds the state projection "
                    "the panels render from."
                ),
                "files": [
                    ("client/src/useSession.js", ["useSession"]),
                    ("client/src/api.js", ["openSession", "renewToken", "controlSocketUrl", "postOffer", "postCandidates"]),
                    ("client/src/main.jsx", []),
                ],
            },
            {
                "name": "Media Links",
                "description": (
                    "The two media legs. `LiveKitLink` joins a LiveKit room with the minted "
                    "token (the default transport); `MediaLink` is the Pipecat SmallWebRTC "
                    "fallback. `summariseStats` turns browser `getStats()` into the RTT, "
                    "jitter and loss numbers the page shows and the trace records."
                ),
                "files": [
                    ("client/src/livekit.js", ["LiveKitLink"]),
                    ("client/src/webrtc.js", ["MediaLink", "microphoneAvailable"]),
                    ("client/src/stats.js", ["summariseStats"]),
                ],
            },
            {
                "name": "Panels and Page",
                "description": (
                    "`App` lays out transcript, current step, diagnostic state and "
                    "connection bar. Each panel is a small component; `Composer` is the "
                    "click-or-type input and `EventLog` shows the live trace."
                ),
                "files": [
                    ("client/src/App.jsx", ["App"]),
                    ("client/src/components/Transcript.jsx", ["Transcript"]),
                    ("client/src/components/StepPanel.jsx", ["StepPanel"]),
                    ("client/src/components/StatePanel.jsx", ["StatePanel"]),
                    ("client/src/components/Composer.jsx", ["Composer"]),
                    ("client/src/components/ConnectionBar.jsx", ["ConnectionBar"]),
                    ("client/src/components/LevelMeter.jsx", ["LevelMeter"]),
                    ("client/src/components/EventLog.jsx", ["EventLog"]),
                    ("client/src/components/Doodles.jsx", ["Mascot"]),
                    ("client/src/styles.css", []),
                ],
            },
        ],
        "sub_relations": [
            ("Session Control Plane", "Panels and Page", "supplies the state projection and transcript", ["client/src/App.jsx:useSession"]),
            ("Media Links", "Panels and Page", "supplies mic level and link statistics", ["client/src/App.jsx:LiveKitLink"]),
            ("Media Links", "Session Control Plane", "reuses api.js for the SDP offer on the fallback path", ["client/src/webrtc.js:postOffer"]),
        ],
    },
    # ------------------------------------------------------------------ 2
    {
        "name": "FastAPI Server",
        "description": (
            "One FastAPI process on one port. It mints short-lived session credentials, "
            "serves the built client, owns the control WebSocket, runs every typed turn "
            "against the diagnostic core, and holds consent, handoff, trace and transcript "
            "records. In the default transport it does not carry media."
        ),
        "subs": [
            {
                "name": "App and Settings",
                "description": (
                    "`create_app` assembles the routes (`/healthz`, `/api/session`, "
                    "`/api/session/{room}/token`, `/api/offer`, `/api/ice`, "
                    "`/api/trace/{room}`, `/ws`), the static client, the `/support` console and the support routes, and, under the livekit transport, `/lk`. `/api/offer` and `/api/ice` serve only the Pipecat fallback. `Settings` reads every option from the "
                    "environment; `main` runs uvicorn."
                ),
                "files": [
                    ("server/app.py", ["create_app", "AppState", "run_turn", "broadcast"]),
                    ("server/config.py", ["Settings"]),
                    ("server/__main__.py", ["main"]),
                ],
            },
            {
                "name": "Session Credentials",
                "description": (
                    "Mints and verifies the short-lived, single-room, single-identity "
                    "tokens. `livekit_tokens` is the JWT the LiveKit media server accepts; "
                    "`tokens` is the earlier token for the Pipecat fallback."
                ),
                "files": [
                    ("server/livekit_tokens.py", ["mint", "verify", "Claims"]),
                    ("server/tokens.py", ["mint", "verify", "MintedSession", "new_room_id"]),
                ],
            },
            {
                "name": "Turn Bridge",
                "description": (
                    "The click-or-type path and the session registry. A click, a typed "
                    "string and a transcribed utterance enter as the same event; "
                    "`run_typed_turn` calls `agent.core.diagnose`, `fanout` pushes the "
                    "result to every participant."
                ),
                "files": [
                    ("server/core_bridge.py", ["Session", "SessionRegistry", "run_typed_turn", "fanout", "project_state", "session_snapshot"]),
                ],
            },
            {
                "name": "Consent, Handoff and Records",
                "description": (
                    "Per-session consent, the escalation handoff rendered from "
                    "`DiagnosticState`, the per-session JSONL trace, and consented "
                    "transcripts written to Postgres (`pilot_sessions`, "
                    "`pilot_transcript_lines`)."
                ),
                "files": [
                    ("server/consent.py", ["ConsentState"]),
                    ("server/handoff.py", ["build_handoff"]),
                    ("server/trace.py", ["Trace"]),
                    ("server/transcripts.py", ["collect", "check_consent", "redact"]),
                ],
            },
            {
                "name": "Server Verifier",
                "description": "`python -m server.verify` starts a server, checks the mint, the media path, the trace and a typed turn, then stops it.",
                "files": [("server/verify.py", ["run", "BackgroundServer", "verify_mint"])],
            },
        ],
        "sub_relations": [
            ("App and Settings", "Session Credentials", "mints a token for each new session", ["server/app.py:create_app"]),
            ("App and Settings", "Turn Bridge", "routes control-socket turns and typed input", ["server/app.py:run_turn"]),
            ("Turn Bridge", "Consent, Handoff and Records", "writes the trace and builds the handoff from session state", ["server/core_bridge.py:Session"]),
            ("Server Verifier", "App and Settings", "starts and probes the real app", ["server/verify.py:BackgroundServer"]),
        ],
    },
    # ------------------------------------------------------------------ 3
    {
        "name": "LiveKit Voice Pipeline",
        "description": (
            "The media path in production: an agent worker that joins the LiveKit room as a "
            "participant, with Silero VAD, context-dependent endpointing, streaming Amazon "
            "Transcribe, incremental Amazon Polly, speculative prefetch and a latency ladder. "
            "A Pipecat SmallWebRTC path is kept as a documented fallback."
        ),
        "subs": [
            {
                "name": "Agent Worker",
                "description": "`AgentWorker` runs the LiveKit worker; `entrypoint` joins a room; `RoomVoiceAgent` owns one room's audio loop, barge-in and turn dispatch.",
                "files": [("server/livekit_agent.py", ["AgentWorker", "RoomVoiceAgent", "entrypoint", "AgentHost", "VoiceStats"])],
            },
            {
                "name": "Endpointing",
                "description": "Decides end-of-turn with a hangover chosen by FSM state rather than one global silence threshold.",
                "files": [("server/endpointing.py", ["Endpointer", "classify_turn", "Hangover", "EndpointDecision"])],
            },
            {
                "name": "Streaming ASR",
                "description": "Amazon Transcribe Streaming with custom-vocabulary biasing; emits partials that the prefetch consumes.",
                "files": [("server/transcribe.py", ["TranscribeStream", "ensure_vocabulary", "alias_candidates"])],
            },
            {
                "name": "Incremental TTS",
                "description": "Amazon Polly Neural: whole-utterance synthesis with a disk cache, and clause-by-clause incremental synthesis.",
                "files": [("server/polly.py", ["synthesize_incremental", "synthesize_pcm", "split_clauses", "ClauseBuffer"])],
            },
            {
                "name": "Speculative Prefetch",
                "description": "On a category-bearing ASR partial of enough words, runs retrieval early and discards the result if the final transcript disagrees.",
                "files": [("server/prefetch.py", ["SpeculativePrefetch", "shortlist_for", "category_bearing"])],
            },
            {
                "name": "Latency and Ladder",
                "description": "Measures the nine-component latency budget per turn and applies the graded degradation ladder on a measured breach.",
                "files": [
                    ("server/latency.py", ["LatencyBook", "TurnLatency", "measure_core", "summarise"]),
                    ("server/ladder.py", ["Ladder", "shed_for", "Shed"]),
                ],
            },
            {
                "name": "Dev Media Server and Headless Peers",
                "description": "Runs `livekit-server --dev` locally, joins rooms without a browser, and verifies the voice path end to end (`python -m server.verify_livekit`).",
                "files": [
                    ("server/livekit_dev.py", ["start_dev_server", "DevServer", "find_binary"]),
                    ("server/livekit_peer.py", ["HeadlessParticipant", "open_session"]),
                    ("server/verify_livekit.py", ["run", "verify_barge_in"]),
                ],
            },
            {
                "name": "Pipecat Fallback",
                "description": "The Pipecat SmallWebRTC peer connection inside the server process (`/api/offer`), its headless test peer, and the ICE-candidate rewrite for hosts behind 1:1 NAT.",
                "files": [
                    ("server/pipeline.py", ["attach_media", "MediaSession", "SpeechReporter"]),
                    ("server/headless_peer.py", ["HeadlessPeer", "open_session"]),
                    ("server/sdp.py", ["rewrite_host_candidates"]),
                ],
            },
        ],
        "sub_relations": [
            ("Agent Worker", "Endpointing", "asks for an end-of-turn decision", ["server/livekit_agent.py:RoomVoiceAgent"]),
            ("Agent Worker", "Streaming ASR", "streams 16 kHz frames in, receives partials and finals", ["server/livekit_agent.py:RoomVoiceAgent"]),
            ("Agent Worker", "Incremental TTS", "speaks each cleared clause", ["server/livekit_agent.py:RoomVoiceAgent"]),
            ("Agent Worker", "Speculative Prefetch", "offers it every ASR partial", ["server/livekit_agent.py:RoomVoiceAgent"]),
            ("Agent Worker", "Latency and Ladder", "records per-turn timings and applies shed tiers", ["server/livekit_agent.py:RoomVoiceAgent"]),
            ("Dev Media Server and Headless Peers", "Agent Worker", "joins a room the worker serves", ["server/livekit_peer.py:HeadlessParticipant"]),
        ],
    },
    # ------------------------------------------------------------------ 4
    {
        "name": "LangGraph Diagnostic Core",
        "description": (
            "The `agent` package: a typed `DiagnosticState`, a LangGraph `StateGraph` whose "
            "nodes are authored step functions, a next-step policy that removes illegal moves "
            "before the model sees a candidate list, a Bedrock Nova wrapper, and a "
            "deterministic output guard. `core.diagnose(utterance, state)` is the entry point."
        ),
        "subs": [
            {
                "name": "Diagnostic State",
                "description": "The typed record the policy reads instead of the transcript: 13 FSM states, five interrupts, the attempted-step ledger, hypotheses, device identification.",
                "files": [("agent/state.py", ["DiagnosticState", "State", "Interrupt", "Ledger", "DeviceIdentification"])],
            },
            {
                "name": "State Graph",
                "description": "The LangGraph `StateGraph`: routing functions, an in-memory checkpointer, and `run_turn` / `resume_turn`.",
                "files": [("agent/graph.py", ["build_graph", "run_turn", "resume_turn", "make_checkpointer", "route_triage"])],
            },
            {
                "name": "Step Functions and Output Guard",
                "description": "One function per FSM state, `diagnose` as the entry point, and `output_guard`, the last deterministic check before text is spoken or rendered.",
                "files": [("agent/core.py", ["diagnose", "output_guard", "step_triage", "step_select_step", "step_destructive_gate", "CoreAgent", "TurnResult"])],
            },
            {
                "name": "Next-Step Policy",
                "description": "Produces the legal candidate set: hazard stop, no-repeat, model clearance, destructive gate; also decides escalation.",
                "files": [("agent/policy.py", ["candidate_steps", "select", "escalation", "legal_step_ids", "CandidateDecision"])],
            },
            {
                "name": "Answers and Symptom Coverage",
                "description": "`answers.py` stores what the caller said in reply to a question as typed data; `symptoms.py` tells a genuine route apart from a nearest-category force.",
                "files": [
                    ("agent/answers.py", ["read_answer", "validate_rules", "AnswerRule"]),
                    ("agent/symptoms.py", ["assess", "is_nearest_category_force", "Coverage"]),
                ],
            },
            {
                "name": "Bedrock LLM",
                "description": "A thin boto3 wrapper: `classify` on Nova Micro, `decide` on Nova Pro, plus `NullLLM` for model-free runs.",
                "files": [("agent/llm.py", ["BedrockLLM", "NullLLM", "LLM", "parse_json_object", "Classification", "TurnDecision"])],
            },
            {
                "name": "Step Ontology",
                "description": "The canonical step ids and the taxonomy-id to candidate-step map. It lives in the `eval/` package but is imported by the runtime core, policy, state and server.",
                "files": [("eval/ontology.py", ["legal_candidates", "validate", "AttemptedStep", "Step", "Family"])],
            },
        ],
        "sub_relations": [
            ("State Graph", "Step Functions and Output Guard", "every graph node is a step function from core.py", ["agent/graph.py:build_graph"]),
            ("State Graph", "Diagnostic State", "checkpoints the typed record", ["agent/graph.py:make_checkpointer"]),
            ("Step Functions and Output Guard", "Next-Step Policy", "asks for the legal candidates and the escalation decision", ["agent/core.py:step_select_step"]),
            ("Step Functions and Output Guard", "Bedrock LLM", "calls classify and decide", ["agent/core.py:step_triage"]),
            ("Step Functions and Output Guard", "Answers and Symptom Coverage", "reads typed answers and checks symptom coverage", ["agent/core.py:step_triage"]),
            ("Next-Step Policy", "Step Ontology", "filters candidates from the ontology", ["agent/policy.py:candidate_steps"]),
            ("Next-Step Policy", "Diagnostic State", "reads the ledger and device identification", ["agent/policy.py:candidate_steps"]),
        ],
    },
    # ------------------------------------------------------------------ 5
    {
        "name": "Hybrid Retrieval",
        "description": (
            "Filter first, then search. `retrieval.retrieve` applies model, category and "
            "speakable filters, fuses BM25 and dense scores, reranks and returns the top three "
            "Tier-1 chunks. The chunk store is Postgres plus pgvector (Titan embeddings); a "
            "JSONL backend takes over when Postgres does not answer."
        ),
        "subs": [
            {
                "name": "Filter, Fuse and Rerank",
                "description": "The retrieval chain over a `Backend`: model filter (confirmed / probable / unknown), fusion of lexical and dense scores, rerank, top 3 with chunk ids.",
                "files": [("agent/retrieval.py", ["retrieve", "rerank", "model_filter", "Chunk", "RetrievalResult", "Hit"])],
            },
            {
                "name": "Retrieval Backends",
                "description": "`PostgresBackend` runs the filter and both halves of the search as SQL; `JsonlBackend` serves `data/processed/chunks.jsonl` with stdlib BM25; `default_backend` picks one once.",
                "files": [("agent/retrieval.py", ["Backend", "PostgresBackend", "JsonlBackend", "default_backend"])],
            },
            {
                "name": "Postgres and pgvector Store",
                "description": "Schema (`source_registry`, `chunks`, `chunk_lexemes`, `lexeme_df`, `corpus_stats`, `embedding_model`, `chunk_embeddings`), the migration that loads the corpus, Titan embedding calls, and the SQL halves of the hybrid search.",
                "files": [("agent/store.py", ["connect", "migrate", "embed", "embed_query", "bm25_scores", "dense_scores", "fetch_chunk_rows", "model_predicate"])],
            },
        ],
        "sub_relations": [
            ("Filter, Fuse and Rerank", "Retrieval Backends", "asks the backend for a pool, lexical scores and dense scores", ["agent/retrieval.py:retrieve"]),
            ("Retrieval Backends", "Postgres and pgvector Store", "PostgresBackend calls the store's SQL halves", ["agent/retrieval.py:PostgresBackend"]),
        ],
    },
    # ------------------------------------------------------------------ 6
    {
        "name": "RAG Corpus and Ingest",
        "description": (
            "The offline path that builds the Tier-1 corpus: `python -m ingest.run` chunks "
            "the saved manuals and help-center pages under `data/raw/` and `data/text/`, "
            "attaches metadata and the source registry, and writes `data/processed/chunks.jsonl` "
            "and `data/processed/sources.json`. `agent.store.migrate` loads those into Postgres. "
            "Tier-2 and Tier-3 collection scripts live in `scripts/` and never feed the speech path."
        ),
        "subs": [
            {
                "name": "Chunking",
                "description": "Parses HTML and manual text and packs chunks; a procedure is never split.",
                "files": [("ingest/chunk.py", ["chunk_corpus", "chunk_source", "parse_html", "parse_manual", "pack"])],
            },
            {
                "name": "Metadata and Registry",
                "description": "Declared (not inferred) model applicability, clearance flags and the source registry; `run.py` writes both output files.",
                "files": [
                    ("ingest/metadata.py", ["build_metadata", "Source", "Chunk", "redact_firmware_versions"]),
                    ("ingest/run.py", ["main", "build_registry", "write_outputs"]),
                ],
            },
            {
                "name": "Corpus Validation",
                "description": "`python -m ingest.validate` checks the corpus against the design rules; breaches exit non-zero.",
                "files": [("ingest/validate.py", ["check_chunks", "check_procedures_atomic", "check_step_ids", "main"])],
            },
            {
                "name": "Known-Issue Watch",
                "description": "A watcher over public pages whose output is asserted to be Tier 2; it is not a vendor feed and is never speakable.",
                "files": [("ingest/known_issues.py", ["assert_monitor_output_is_tier2", "KnownIssueRecord", "confirm_with_tier1", "WatchedPage"])],
            },
            {
                "name": "Tier 2 and 3 Collection Scripts",
                "description": "Scripts for discovery-only samples (app-store reviews) and for reading saved pages; their output is never a verified fix.",
                "files": [
                    ("scripts/collect_app_reviews.py", []),
                    ("scripts/html2txt.py", []),
                    ("scripts/probe_amazon_aggregators.py", []),
                    ("scripts/probe_amazon_round2.py", []),
                    ("scripts/probe_play.py", []),
                ],
            },
        ],
        "sub_relations": [
            ("Metadata and Registry", "Chunking", "run.py calls chunk_corpus and attaches metadata to each chunk", ["ingest/run.py:main"]),
            ("Corpus Validation", "Metadata and Registry", "checks the files run.py writes", ["ingest/validate.py:check_chunks"]),
        ],
    },
    # ------------------------------------------------------------------ 7
    {
        "name": "Eval Harnesses",
        "description": (
            "The 30-scenario golden set (`eval/scenarios.json`) scored three ways: Harness A "
            "(text, single turn), Harness B (scripted multi-turn) and Harness C (synthesised "
            "speech through a real LiveKit room), plus grounding, latency-ladder and prefetch "
            "measurements and the two-grader pack with Cohen's kappa."
        ),
        "subs": [
            {
                "name": "Harness A",
                "description": "Single turn: pre-populates a `DiagnosticState` from the scenario, calls the agent once, scores the next step. `baseline.py` is the deliberately dumb floor agent.",
                "files": [
                    ("eval/harness.py", ["run_harness", "score", "state_from_scenario", "Scenario", "build_agent"]),
                    ("eval/run.py", ["main"]),
                    ("eval/baseline.py", ["DumbBaselineAgent", "match_taxonomy"]),
                ],
            },
            {
                "name": "Harness B",
                "description": "Scripted multi-turn: a deterministic responder plays the user down each branch.",
                "files": [
                    ("eval/harness_b.py", ["run_script", "ScriptedResponder", "CoreDriver", "validate_scripts"]),
                    ("eval/run_b.py", ["main"]),
                ],
            },
            {
                "name": "Harness C",
                "description": "End to end spoken: synthesised speech with road noise, injected at real-time pace through a real LiveKit participant, with an ASR-corruption pass.",
                "files": [
                    ("eval/harness_c.py", ["run_harness_c", "run_case", "build_cases", "synthesize_case"]),
                    ("eval/run_c.py", ["main"]),
                ],
            },
            {
                "name": "Grounding and Grader Pack",
                "description": "Structural grounding rate from the output guard's verdicts, the two-grader pack, and Cohen's kappa scoring.",
                "files": [
                    ("eval/grounding.py", ["run_harness_a", "run_harness_b", "structural_report", "scan_turn"]),
                    ("eval/run_grounding.py", ["main"]),
                    ("eval/build_grounding_pack.py", ["build", "draw_sample"]),
                    ("eval/score_grading.py", ["cohens_kappa", "report"]),
                ],
            },
            {
                "name": "Prefetch and Ladder Measurements",
                "description": "Replays that measure what speculative prefetch is worth and drive the degradation ladder until it fires and recovers.",
                "files": [
                    ("eval/run_prefetch.py", ["measure", "partial_stream"]),
                    ("eval/run_ladder.py", ["replay", "measured_m7"]),
                ],
            },
        ],
        "sub_relations": [
            ("Grounding and Grader Pack", "Harness A", "runs the core over Harness A and captures guard verdicts", ["eval/grounding.py:run_harness_a"]),
            ("Grounding and Grader Pack", "Harness B", "runs the scripted branches the same way", ["eval/grounding.py:run_harness_b"]),
        ],
    },
    # ------------------------------------------------------------------ 8
    {
        "name": "HTTPS and wss Relay",
        "description": (
            "A page served over https may not open `ws://`, and `livekit-server` does not "
            "terminate TLS on its signalling port. When the server runs with `ROVE_TLS_CERT` "
            "and `ROVE_TLS_KEY`, uvicorn terminates TLS and `/lk` relays only the signalling "
            "(`rtc` paths) to `settings.livekit_url` (default `ws://127.0.0.1:7880`). Media stays "
            "browser to media server. A testing-only certificate script and a headless wss verifier ship with it."
        ),
        "subs": [
            {
                "name": "wss Signalling Relay",
                "description": "`register_livekit_relay` mounts `/lk/{path}` as a WebSocket and HTTP pass-through; only `rtc` and `rtc/...` paths (signalling and its validate probe) are forwarded to `settings.livekit_url`; anything else is closed with 1008.",
                "files": [("server/livekit_relay.py", ["register_livekit_relay"])],
            },
            {
                "name": "TLS Testing Server",
                "description": "`scripts/serve_https_testing.sh` generates a throwaway CA and leaf certificate under `server/testing-tls/` and starts `python -m server` with `ROVE_TLS_CERT` and `ROVE_TLS_KEY`. Testing only. In `server/config.py`, `Settings.scheme` and `Settings.livekit_public_url` decide whether the page is handed `wss://<host>/lk`.",
                "files": [("scripts/serve_https_testing.sh", ["ROVE_TLS_CERT"])],
            },
            {
                "name": "wss Verifier",
                "description": "`python -m server.verify_wss` mints through the https page, asserts the browser would receive `wss://<host>/lk`, and joins a room through it.",
                "files": [("server/verify_wss.py", ["main"])],
            },
        ],
        "sub_relations": [
            ("TLS Testing Server", "wss Signalling Relay", "starts the TLS server that hosts the relay", ["scripts/serve_https_testing.sh:ROVE_TLS_CERT"]),
            ("wss Verifier", "wss Signalling Relay", "joins a room through /lk over wss", ["server/verify_wss.py:main"]),
        ],
    },
    # ------------------------------------------------------------------ 9
    {
        "name": "Support Console",
        "description": (
            "The human side of escalation. A no-framework browser console (`support/`, built "
            "with `node support/build.mjs`) and the server routes it calls (`/api/support/*`, "
            "`/ws/support`): observer tokens, a room list, the handoff panel, disclosure, "
            "joining the same room, and collecting a consented transcript."
        ),
        "subs": [
            {
                "name": "Support API",
                "description": "`register_support_routes` adds the observer, rooms, handoff, trace, disclose, join, leave and collect routes plus `/ws/support`.",
                "files": [("server/support.py", ["register_support_routes", "authorise_observer", "check_support_key", "room_summary"])],
            },
            {
                "name": "Browser Console",
                "description": "Pure panel renderers (`panels.js`), the DOM and network layer (`main.js`), the REST and WebSocket clients, a stdlib-only build and a self-test.",
                "files": [
                    ("support/src/main.js", []),
                    ("support/src/panels.js", []),
                    ("support/src/api.js", []),
                    ("support/src/socket.js", []),
                    ("support/src/console.css", []),
                    ("support/index.html", []),
                    ("support/build.mjs", []),
                    ("support/selftest.mjs", []),
                ],
            },
        ],
        "sub_relations": [
            ("Browser Console", "Support API", "calls /api/support/* and opens /ws/support", ["server/support.py:register_support_routes"]),
        ],
    },
]

# Relations between top-level components. Every one cites a real import or call.
RELATIONS = [
    ("React Client", "FastAPI Server", "mints a session, opens the /ws control socket, sends typed turns", ["client/src/api.js:openSession", "server/app.py:create_app"]),
    ("React Client", "LiveKit Voice Pipeline", "joins the LiveKit room and streams mic audio", ["client/src/livekit.js:LiveKitLink", "server/livekit_agent.py:AgentWorker"]),
    ("React Client", "HTTPS and wss Relay", "joins over wss://host/lk when the page is https and the host is a bare name[:port]", ["server/config.py:Settings.livekit_public_url", "server/livekit_relay.py:register_livekit_relay"]),
    ("HTTPS and wss Relay", "LiveKit Voice Pipeline", "forwards signalling to the LiveKit media server at settings.livekit_url (default ws://127.0.0.1:7880)", ["server/livekit_relay.py:register_livekit_relay", "server/config.py:Settings"]),
    ("FastAPI Server", "HTTPS and wss Relay", "under the livekit transport registers /lk; uvicorn terminates TLS when a cert and key are set", ["server/app.py:create_app", "server/__main__.py:main"]),
    ("FastAPI Server", "LiveKit Voice Pipeline", "under the livekit transport, starts the in-process agent worker and mints LiveKit tokens", ["server/livekit_agent.py:AgentWorker", "server/livekit_tokens.py:mint"]),
    ("FastAPI Server", "LangGraph Diagnostic Core", "runs each turn through core_bridge into agent.core.diagnose", ["server/core_bridge.py:run_typed_turn", "agent/core.py:diagnose"]),
    ("LiveKit Voice Pipeline", "FastAPI Server", "dispatches finalised utterances through core_bridge sessions", ["server/livekit_agent.py:RoomVoiceAgent", "server/core_bridge.py:Session"]),
    ("LiveKit Voice Pipeline", "Hybrid Retrieval", "prefetch retrieves on category-bearing ASR partials", ["server/prefetch.py:SpeculativePrefetch", "agent/retrieval.py:retrieve"]),
    ("LangGraph Diagnostic Core", "Hybrid Retrieval", "retrieves cleared Tier-1 chunks (in step_hypothesise) before the policy runs", ["agent/core.py:step_hypothesise", "agent/retrieval.py:retrieve"]),
    ("RAG Corpus and Ingest", "Hybrid Retrieval", "store.migrate loads chunks.jsonl and sources.json into Postgres", ["agent/store.py:migrate", "ingest/run.py:write_outputs"]),
    ("Hybrid Retrieval", "RAG Corpus and Ingest", "reads the model vocabulary from ingest.metadata", ["agent/retrieval.py:model_filter", "ingest/metadata.py:build_metadata"]),
    ("Eval Harnesses", "LangGraph Diagnostic Core", "scores core.CoreAgent through Harness A and B", ["eval/harness.py:build_agent", "agent/core.py:CoreAgent"]),
    ("Eval Harnesses", "LiveKit Voice Pipeline", "Harness C drives a real LiveKit room with synthesised speech", ["eval/harness_c.py:run_case", "server/livekit_peer.py:open_session"]),
    ("FastAPI Server", "Support Console", "registers the /api/support routes", ["server/app.py:create_app", "server/support.py:register_support_routes"]),
    ("Support Console", "FastAPI Server", "reads live sessions, handoff and traces from AppState", ["server/support.py:room_summary", "server/app.py:AppState"]),
]
