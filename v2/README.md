# Rove support agent — v2

A voice agent that diagnoses Rove dash cam problems by reasoning from Rove's own
documentation. It sits beside the original system (repo root) so the two can be
compared; nothing outside `v2/` was changed.

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
| Safety | `rove/safety.py` | Rules before and after the model, runtime grounding check, required escalations |
| Web | `server/` | `python -m v2.server` → caller page with hold-to-talk voice and typing |
| Voice (production) | `voice/livekit_worker.py` | LiveKit Agents pipeline (Silero VAD, Transcribe, Polly) with this agent as its LLM step |
| Evaluation | `eval/head_to_head.py`, `eval/conversations.py` | Simulated customers on the 30 golden scenarios, judged by a separate model; old vs v2 |

No vector database, no embeddings, no state machine: each model's documentation
fits in the prompt (largest pack set ≈ 20k tokens), so the agent reads it whole.

## Run it

```bash
python -m venv .venv && .venv/Scripts/pip install -r v2/requirements.txt   # (bin/ on Linux/macOS)
# AWS credentials with Bedrock, Transcribe and Polly in us-east-1 (env vars or ~/.aws/credentials)

python -m pytest v2/tests                # 107 offline tests, no AWS needed
python -m v2.server                      # http://127.0.0.1:8000 — talk or type

# Voice through LiveKit (what production uses):
livekit-server --dev                     # or LiveKit Cloud: set LIVEKIT_URL / KEY / SECRET
python -m v2.voice.livekit_worker dev
python -m v2.server                      # open http://localhost:8000 and press Start call (live WebRTC voice)
                                         # /classic keeps the push-to-talk and typing page

# Live checks (need AWS; the LiveKit one needs the two processes above)
python -m v2.tests.live_voice_roundtrip http://127.0.0.1:8000
python -m v2.tests.live_livekit_call
python -m v2.eval.conversations
python -m v2.eval.head_to_head --systems old,v2

# Rebuild knowledge after the documents change
python -m v2.knowledge.build_text && python -m v2.knowledge.compile_packs && python -m v2.knowledge.factcheck
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
