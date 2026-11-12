# Rove support agent (v2)

A voice agent that diagnoses Rove dash cam problems by reasoning from Rove's own
documentation. This is the current application and lives at the repo root. The
original system (v1: LangGraph state machine, retrieval, custom voice stack) is kept,
unchanged, in [`v1/`](v1/README.md) for reference and comparison.

## Repository layout

```
rove/        the agent: prompt, case file, safety, scope gate, Bedrock/Ollama client, speech
server/      FastAPI app and the two web pages (live call, classic push-to-talk/typing)
voice/       LiveKit Agents worker (production voice path)
knowledge/   offline pipeline + reviewed per-model packs (clean/ text, packs/*.md, registry.json)
eval/        scenario suites, head-to-head, audits, E2E report
tests/       offline tests and live checks
data/        source corpus (raw/ and text/ manuals, Help Center); data/sessions/ is runtime output
v1/          the original application, kept intact (own README, docs, code, tests)
PROJECT_CONTEXT.md   one-file context for the whole project, v1 and v2
```
The shared `data/raw` and `data/text` corpus at the root is used by both generations;
v1's processed chunks are in `v1/data/processed`.

## How it works

```
data/ (manuals, Help Center)
   │  offline: knowledge/build_text.py → compile_packs.py → factcheck.py
   ▼
knowledge/packs/*.md     one reviewed pack per camera model + general + identify
   │
   ▼  every turn
customer words ─► safety.screen (rules) ─┬─► hard stop: hazard / asks for a person
                 backstop classifier ────┘
               ─► Agent: ONE model call reads the method + the right packs + the case file,
                  returns <case> update, <say> reply, <action>
               ─► safety.review: firmware versions, unconfirmed erase/reset, footage at risk,
                  driving, invented brands/specs, length → one rewrite, else a safe fallback
               ─► required escalations enforced by code (bricked after update, car wiring,
                  refunds/warranty)
   ▼
reply text ─► Polly ─► browser / LiveKit room        case file ─► UI, handoff, saved session
```

| Part | File | What it does |
|---|---|---|
| Source cleaning | `knowledge/build_text.py` | Repairs PDF ligature damage, strips scraper junk, extracts Help Center articles |
| Knowledge packs | `knowledge/compile_packs.py` | An LLM drafts one structured pack per model: identification, key facts, exact procedures, troubleshooting playbook, warnings, gaps — every line cited |
| Fact check | `knowledge/factcheck.py` | Every number+unit in a pack must appear in its sources; citations must resolve; no firmware versions |
| Agent | `rove/agent.py`, `rove/prompt.py` | The support-engineer method; one model call per turn |
| Case file | `rove/case.py` | Model, symptom, facts, steps tried, ranked causes, flags — drives no-repeat, UI and handoff |
| Scope gate | `rove/scope.py` | Code-level gate: only dash-cam troubleshooting reaches the model |
| Safety | `rove/safety.py` | Rules before and after the model, runtime grounding check, required escalations |
| Web | `server/` | `python -m server` → caller page with hold-to-talk voice and typing |
| Voice (production) | `voice/livekit_worker.py` | LiveKit Agents pipeline (Silero VAD, Transcribe, Polly) with this agent as its LLM step |
| Evaluation | `eval/head_to_head.py`, `eval/run_suite.py`, `eval/conversations.py` | Simulated customers on the 30 golden scenarios, judged by a separate model; 47-scenario E2E suite (`eval/E2E_REPORT.md`) |

No vector database, no embeddings, no state machine: each model's documentation
fits in the prompt (largest pack set ≈ 20k tokens), so the agent reads it whole.

## Run it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/ on Linux/macOS)
# AWS credentials with Bedrock, Transcribe and Polly in us-east-1 (env vars or ~/.aws/credentials)

python -m pytest tests                # offline tests, no AWS needed
python -m server                      # http://127.0.0.1:8000 — talk or type

# Voice through LiveKit (what production uses):
livekit-server --dev                     # or LiveKit Cloud: set LIVEKIT_URL / KEY / SECRET
python -m voice.livekit_worker dev
python -m server                      # open http://localhost:8000 and press Start call (live WebRTC voice)
                                         # /classic keeps the push-to-talk and typing page

# Live checks (need AWS; the LiveKit one needs the two processes above)
python -m tests.live_voice_roundtrip http://127.0.0.1:8000
python -m tests.live_livekit_call
python -m eval.conversations
python -m eval.head_to_head --systems v2

# Rebuild knowledge after the documents change
python -m knowledge.build_text && python -m knowledge.compile_packs && python -m knowledge.factcheck
```

## Models (`rove/config.py`, all overridable by environment variable)

| Role | Now | Intended once the AWS account has the Anthropic use-case form submitted |
|---|---|---|
| Agent (`ROVE_AGENT_MODEL`) | `moonshotai.kimi-k2.5` | `us.anthropic.claude-sonnet-5-5` (or `-4-6`) |
| Safety backstop (`ROVE_FAST_MODEL`) | `us.amazon.nova-2-lite-v1:0` | Claude Haiku |
| Pack compiler (`ROVE_OFFLINE_MODEL`) | `moonshotai.kimi-k2.5` | Claude Opus |

## Before production

- **Have someone from support review `knowledge/packs/`.** They are drafts. The
  fact check catches invented numbers, not wrong reasoning. Three errors were
  found and fixed by hand so far; see the git history of the packs.
- Enable Claude on the AWS account and switch the models above, then re-run the evaluation.
- Sessions are kept in memory and saved to `data/sessions/` as JSON; move to a database
  before running more than one server.
- Add authentication and rate limits to the web API, and real LiveKit keys.
