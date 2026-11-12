# CodeBoarding architecture output for Rove

Architecture diagrams and documentation for this repo, in CodeBoarding's output
format: an `analysis.json`, a top-level Mermaid diagram, and one nested diagram
per component.

**Read this first: the CodeBoarding engine did not generate this output.** The
analysis and every description in it were written by this run (Claude Sonnet 5.5)
from reading the code. Section 1 says why. Section 3 lists where it disagrees
with docs 06 and 08.

| File | What it is |
|---|---|
| [`overview.md`](overview.md) | Top-level diagram (9 components, 16 relations), relation table, details |
| `<Component_Name>.md` (9 files) | Nested diagram for one component, its sub-components, files and symbols |
| [`analysis.json`](analysis.json) | The same model as data, in CodeBoarding's `analysis.json` shape |
| [`repro/config.toml.example`](repro/config.toml.example) | Provider config to reproduce this with the real engine |
| [`tools/`](tools) | `components.py` (the model), `build.py` (renders), `check.py` (verifies) |

Docs 01 to 08 are untouched. Nothing outside `docs/codeboarding/` was changed.

## 1. How this was produced, and why not by the engine

I read the engine at `/home/ubuntu/codeboarding-upstream` (CodeBoarding 0.15.3): its
README, `pyproject.toml`, `agents/llm_config.py` and `output_generators/markdown.py`. Two
independent facts stopped a real run on this machine:

1. **Bedrock is supported, but only with a bearer token.** The `aws` provider is
   selected only when `AWS_BEARER_TOKEN_BEDROCK` is set (`agents/llm_config.py`,
   `selection_envs`). It does not use an IAM profile. The brief says this machine's Bedrock access
   is the EC2 default AWS profile, which is IAM. I did not create or invent a token.
   The engine also defaults to `anthropic.claude-sonnet-4-6`, which is not one of
   the models this project has.
2. **The engine cannot be installed in this environment.** It requires Python
   `>=3.12,<3.13` (`pyproject.toml`). The only interpreter here is 3.14, and the
   worktree `.venv` is 3.14. Its language servers are also downloaded on first use
   from the web, which this task ruled out.

So this follows the fallback you specified: **the description step was done by this
run, not by CodeBoarding.** Concretely:

| Engine step | Done here? |
|---|---|
| Static analysis (language servers, call graph) | No |
| Clustering of code into components | No. I chose the 9 top-level components and their sub-components by reading the code, starting from the 9 you listed |
| Component descriptions | Yes, written by me from docstrings and code |
| Relations | Yes, but each cites an import or call as `evidence`. All carry `"is_static": false` because none comes from call-graph analysis |
| Output format | Matched: `analysis.json` keys, `graph LR` diagrams with `click` links, Details / Related Classes / Source Files sections |

`analysis.json` records this in `metadata` (`"engine_run": false`). Line numbers are not
typed: `build.py` resolves each symbol to its real span with the same code `check.py` uses.

**The 9 components** are the ones requested, plus one the repo has that the brief did not
list: the **Support Console** (`support/` and `server/support.py`). It is real code and
leaving it out would have broken "cover the whole system". "Hybrid Retrieval" and "RAG
Corpus and Ingest" are separate: retrieval is `agent/retrieval.py` plus the SQL in
`agent/store.py`; the corpus side is `ingest/` and `data/processed/`.

## 2. Verification

Run `.venv/bin/python docs/codeboarding/tools/check.py`. It checks:

- `analysis.json` shape; every component has a description; relation endpoints exist, each has a label and cites evidence.
- Every file exists. Every Python symbol exists (resolved with `ast`) and its start and end lines match the code. For `.js`, `.jsx`, `.mjs` and `.sh` files the symbol check is a text match, not a parse, so it is weaker.
- All 85 tracked source files under `agent/`, `server/`, `eval/`, `ingest/`, `client/src/`, `support/` and `scripts/` (tests and `__init__.py` excluded) belong to a component. Nothing is unowned and no component lists a file that does not exist.
- Every backticked repo path in every Markdown file exists, and every relative link and `click` target resolves.
- Mermaid structure (below).

**Mermaid: structural lint, not a real parse.** No Mermaid parser is installed here
(`mmdc`, `mermaid` and `@mermaid-js/mermaid-cli` are all absent) and I did not install one.
`check.py` instead enforces the subset of syntax these files use: block starts with
`graph LR`, node ids match `[A-Za-z_]\w*`, labels are quoted, every edge endpoint and `click`
target is declared, no duplicate nodes, fences are closed. It would catch the usual
rendering breakages. It would not catch every error a real parser does. Where a parser is
available, run `npx @mermaid-js/mermaid-cli -i docs/codeboarding/overview.md` on each file.

**Independent review.** A separate read-only reviewer checked every relation and every
description against the code and found about 30 claims true and these problems, all fixed:
a relation cited `step_select_step` where the retrieval call is actually in
`step_hypothesise`; five relations stated as unconditional what is conditional on the
transport, on TLS being configured, or on the host being a bare `name[:port]`; the relay's
path filter and default upstream URL were overstated; the store's schema list omitted
`lexeme_df` and `corpus_stats`; the server's route list omitted the static, `/support`,
support and conditional `/lk` routes; and prefetch was described as acting on every
partial when it needs a category-bearing partial of at least 4 words (`server/prefetch.py`,
`MIN_WORDS`).

## 3. Cross-check against docs 06 and 08

Docs 06 (architecture) and 08 (Mermaid diagrams) are design documents dated 2026-11-07
and say "design only, no code" (08, line 3). The code now exists. Each row below was
checked in the code. **Nothing in 06 or 08 was edited.** The two docs say that 06 wins any
dispute between them, so the code-side facts are given here for whoever owns the update.

### Disagreements

| # | 06 / 08 says | The code does | Where |
|---|---|---|---|
| 1 | 08 diagram 4 (`K2`): Postgres holds "checkpoints" | The checkpointer is `InMemorySaver`. Its docstring says Postgres is a later phase | `agent/graph.py` `make_checkpointer` |
| 2 | 08 diagram 4 (`K2`): Postgres holds "traces" | Traces are one JSONL file per session. Postgres holds only consented transcripts (`pilot_sessions`, `pilot_transcript_lines`) | `server/trace.py` `Trace`; `server/transcripts.py` |
| 3 | 08 diagram 5: a "physically separate" Tier-2/3 store | No Tier-2/3 store exists. Separation is a `CHECK (tier = 1)` on the chunk table. The known-issue watch is documented to write files under a data/known-issues directory that is not in the repo (it is created only when the watch runs) | `agent/retrieval.py` docstring; `ingest/known_issues.py` docstring |
| 4 | 08 diagram 1: output guard runs five checks (version regex, one action, citation, destructive phrase, unknown-stays-unknown) | `output_guard` has two drop rules: firmware-version-shaped tokens, and a device-specific claim with no Tier-1 citation. One-action and the destructive gate are enforced earlier, in `select`, `step_destructive_gate` and `step_propose_step`. I found no destructive-phrase or unknown-stays-unknown scan in the guard | `agent/core.py` `output_guard` |
| 5 | 08 diagram 4: Nova Lite is the Tier-3 latency fallback (D-08) | Tier 3 repoints the reasoning call at the Nova Micro id. Nova Lite is not referenced anywhere in the code | `server/latency.py` `_fast_tier`; `server/ladder.py` `Shed` |
| 6 | 08 diagram 4 (`M4`): an offline LLM judge (D-09) | None exists. `eval/score_grading.py` and `eval/run_grounding.py` say the judge waits for two-grader labels | `eval/score_grading.py` |
| 7 | 06 §8.8 / 08: React chosen largely for the voice framework's React hooks | The client depends on `livekit-client` and `react` only, with no LiveKit React package. `LiveKitLink` wraps the SDK directly | `client/package.json`; `client/src/livekit.js` |
| 8 | 08 diagram 1: escalation offers "same-room join, callback, ticket" | Same-room join is implemented (`/api/support/room/{room}/join`). I found no callback or ticket delivery code. `handoff.py` only mentions them | `server/support.py`; `server/handoff.py` |

### Structure notes (not disagreements)

- The step ontology (06 §3.6) lives in `eval/ontology.py`, and the runtime imports it (core, policy, state, graph, answers, llm and several server modules). The runtime therefore depends on the `eval` package. It is listed under the core here (sub-component "Step Ontology").
- `agent/state.py` and `agent/retrieval.py` import `ingest.metadata` for the model vocabulary.

### In the code, absent from 06 and 08

- **The HTTPS and wss relay.** A search of 06, 07 and 08 for `wss`, `relay`, `/lk` and `tls` finds nothing. It is component 8 here.
- **The support console as a second, no-framework browser app** (`support/`). 08 diagram 1 has no box for it. 07 D-17 describes it as not yet existing.
- **A JSONL retrieval backend** that takes over when Postgres does not answer (`JsonlBackend`, `default_backend`). 08 diagram 5 shows no fallback.
- **The `ROVE_TRANSPORT` switch** between the LiveKit default and the Pipecat fallback. 08 diagram 4 shows the fallback only as a dashed edge.

### Agreements (spot-checked)

LangGraph as an authored graph with no planner (`agent/graph.py`); filter-first hybrid
retrieval over Postgres plus pgvector with top 3 returned; Nova Micro for `classify`
and Nova Pro for `decide`; Titan Embeddings v2 with the dimension read from the database
and not hard-coded; Transcribe and Polly Neural; LiveKit as default with Pipecat kept as
fallback; 13 FSM states and five interrupts (diagram 3 matches `agent/state.py`);
Harness A, B and C; the two-grader pack with Cohen's kappa.

## 4. Reproducing

Regenerate this output from the model (no network, no model calls):

```bash
.venv/bin/python docs/codeboarding/tools/build.py   # renders analysis.json and the .md files
.venv/bin/python docs/codeboarding/tools/check.py   # exit 0 only if every check passes
```

`README.md` is hand-written and `build.py` does not touch it. When the code changes,
`check.py` fails on a moved or deleted symbol or an unowned file, and the fix is in
`tools/components.py`.

To run the real engine, which would replace the descriptions here with its own:

```bash
# needs Python 3.12 and a Bedrock API key; see repro/config.toml.example
cd /home/ubuntu/codeboarding-upstream && python3.12 -m venv .venv && .venv/bin/pip install -e .
export AWS_BEARER_TOKEN_BEDROCK=...  AWS_DEFAULT_REGION=us-east-1  AGENT_MODEL=amazon.nova-pro-v1:0
.venv/bin/codeboarding full --local /home/ubuntu/projects/rove-worktrees/codeboarding --render md
```

I did not run this. The engine's own commands are documented in its README (`full`,
`incremental`, `partial`, `--render md|html|rst|mdx`). If it is run, expect its
clustering to differ from the grouping here, and do not overwrite this directory without
diffing against section 3.
