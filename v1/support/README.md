# `support/` — the support console (`docs/06` §5.3, `docs/07` D-17)

`docs/07` D-17 chose the same-session join and named what it was missing:

> **Same-session join** — *chosen*. … needs a live queue, an available human, and an
> agent-side console that can join a room — and **that console does not exist**
> (`06` §9.3 item 14).

This is that console. It is Phase 4 scaffolding, not the pilot: no queue, no routing,
no availability model, no live users. It is the thing those would need to exist on top of.

| file | what it holds |
| --- | --- |
| `index.html` | the shell and the gate. `__BASE__` and `__BUILD__` are substituted at build |
| `src/main.js` | the DOM and the network: the gate, the session, the controls |
| `src/panels.js` | pure functions — session data in, HTML out. No DOM, no network |
| `src/api.js` | the `/api/support/*` surfaces |
| `src/socket.js` | `WS /ws/support`, with reconnection |
| `src/console.css` | one stylesheet, no framework |
| `build.mjs` | copy the modules, substitute the two placeholders. Node stdlib only |
| `selftest.mjs` | parse every module, check every id binds, check every panel escapes |

## Building and running it

From the repository root:

```bash
node support/build.mjs            # writes support/dist
node support/selftest.mjs         # parse, wiring and escaping checks
.venv/bin/python -m server        # serves it at /support
```

Then open **`http://<this-host>:8080/support`**. The console is served from the **same
process** as the rooms it observes, so there is one origin, no CORS to arrange and no
second thing to operate. `ROVE_WEB_PORT` moves the port; `/support` moves with it.

Without a build, `/support` returns 503 with the command to run — the same shape as `/`
without `client/dist`. `GET /healthz` reports `"console": true` once the build is there,
which is the cheapest way to tell a missing build from a missing route.

No `npm install`, no lockfile, no `node_modules` here. Browsers have loaded ES modules
natively for years and nothing in these files needs transpiling.

### The support key you type into the gate

The gate asks for `ROVE_SUPPORT_KEY`. Pin it, or let the process generate one:

```bash
ROVE_SUPPORT_KEY=<something> .venv/bin/python -m server
```

Unset, `server/config.py` generates one per process and `python -m server` **prints it in
the banner** — a key nobody can read is not a security property, it is a locked room with
the key inside. Generated is right for one process on one host and wrong the moment there
are two behind a load balancer, because each would mint under a different key. Pin it then.

`ROVE_OBSERVER_TTL_SECONDS` sets how long a minted observer token lasts (default 300,
ceiling 900 in `server/tokens.py`). The console re-mints; it does not hold a longer one.

### Driving it, in the order the buttons are numbered

1. **List live rooms.** Type the support key, submit. The picker shows one row per live
   room — duration, turn, FSM state, taxonomy id, whether it escalated, whether a human is
   already in it. No transcript and no caller words: choosing a room should not require
   reading one.
2. **Pick a room.** That mints the observer token (`observe:room`, a fresh
   `observer-…` identity, this room only) and opens `WS /ws/support`. The panels fill from
   the `hello` snapshot and stay live from there.
3. **Disclose, then join.** The two steps are two buttons; see below.
4. **Collect transcript**, if §6.3's storage consent exists. It will not exist unless the
   caller granted it on their own page.
5. **Close** returns to the gate. The key is in memory only, so a reload asks again.

### Checking it end to end

```bash
.venv/bin/python -m unittest server.test_support -v    # 35 cases
```

That builds the console, runs `selftest.mjs` over the result, then starts a server and
drives every surface. The self-test is not redundant with the HTTP cases: those assert
that `/support/assets/main.js` is *served*, which a file with a syntax error does
perfectly well, and they cannot see that a renamed id has turned the §6.3 disclosure
button into a no-op or that a panel rendered a stranger's typed words as markup.

### Why not React, when `docs/07` D-15 says React

D-15 chose React for **the caller's page**, and its reasoning is explicit that *"the
decision is made by the voice framework, not by the UI"* — LiveKit's browser SDK (D-02)
arrives as hooks, and anything else means maintaining that glue by hand for a client whose
entire job is to be reliable. None of that reaches here: the console holds no media track,
joins no room with an SDK, and renders from JSON over one WebSocket. D-15's own flip
condition to its alternative B (no framework) is *"the UI is still four panels"*, and B
was rejected on *"the UI grows"* — for the caller's page. An internal console that one
person at a time reads over a caller's shoulder is the case where B's argument wins. The
cost of being wrong is rewriting seven small files.

## What the panels show

Seven, in three columns, all of them fed by the one `WS /ws/support` feed. The snapshot
is the authority and every change re-asks for it, so there is no partial state to keep in
sync; the four-second interval is a floor that moves the clocks and self-heals a missed
push, not the mechanism.

| panel | source | what a joining human reads |
| --- | --- | --- |
| Consent | `snapshot.consent` | §6.3's **two** decisions, each with its own value and modality, whether the GREET notice was spoken and shown, and whether the join has been disclosed |
| Transcript | `snapshot.transcript` | the conversation so far, escaped, and the withheld notice instead if the caller declined *display* |
| Diagnostic state | `snapshot.state` | FSM state, turn, model and confidence, category and taxonomy id, safety flags, escalation — §3.3's record, not a guess from the transcript |
| Already tried | `handoff.already_tried` | §5.2's ledger, in order, with the step description, who proposed it, the outcome and whether it was destructive |
| On what authority | `handoff.authority` | every spoken claim with its `chunk_id`, `doc_code`, page, tier and retrieval date — and `uncited` where a claim has no chunk behind it |
| Handoff | `handoff` | the §5.2 panel: the caller's first words verbatim, the device block, the hypothesis with what is and is not ruled out, the escalation block, and anything `withheld` |
| Trace | `GET …/trace` | the session trace, seeded from the REST surface so a human arriving mid-session sees what already happened |

The §5.2 panel is **rendered from `DiagnosticState` on every request**, not snapshotted at
the join (`docs/07` D-17: *"and live thereafter"*). `panels.js` is pure functions — session
data in, HTML out, no DOM and no network — because a rendering bug here is a human being
told something untrue about somebody else's camera.

## The two credentials

They do different jobs and neither is the caller's token.

- **The support key** (`ROVE_SUPPORT_KEY`) authorises the **mint**, and only the mint. A
  room id is not a secret — it travels in URLs and in the trace — so possession of one must
  not be enough to watch the session it names. The key is held in memory for the life of the
  tab and never written to storage: a console that left a standing credential in
  `localStorage` would be worse than one that asks again after a reload. It is a stand-in
  for whatever the support organisation already authenticates its people with; `docs/06`
  §9.3 item 2 owns that answer.
- **The observer token** (`observe:room`, identity `observer-…`) authorises everything else,
  for exactly one room, for minutes. It is **not** the caller's token and cannot be used
  where the caller's is: `server/tokens.py` defaults `verify` to the caller scope, so every
  caller surface refuses an observer token without being edited for it, and every support
  surface names `observe:room` out loud. A fresh identity is minted per admission rather
  than a standing support identity, because the room is the unit of access.

`server/test_support.py` asserts both directions, on every surface and both sockets.

## The two-step join (`docs/06` §6.3, §5.3)

The buttons are numbered because the order is a rule, not a preference:

1. **Disclose the join.** §6.3: a human joining the room can hear the caller and read the
   transcript, *"and the agent makes it before the join, not after"*. This speaks and shows
   the disclosure and records that it happened.
2. **Join the room.** The server refuses with **409** until step 1 has run. The console
   also disables the button — but the server's refusal is the safety property; the disabled
   button only keeps the UI from teaching its operator the wrong model of what is allowed.

On the join, the agent **stops proposing steps and drops to transcribing** (§5.3). That
flip is in `server/core_bridge.py`, at the turn dispatcher, not in `agent/`: the core
decides what the next step is, and *"there should not be a next step"* is a fact about who
is in the room rather than a diagnostic judgement.

Leaving does **not** resume the agent. §5.3 says what the join does and says nothing about
a departure, so handing the session back is an explicit act — a caller who has been told a
human is handling it should not find the agent proposing steps again because somebody
closed a tab.

## What this console will not do

- **Speak as the caller.** The socket's accepted message set is `ping`, `refresh` and
  `support.note`; `user.text` is refused by name. `docs/06` §7.2's M10 is computed over a
  transcript whose caller lines are the caller's.
- **Store anything on its own.** "Collect transcript" writes to the pilot corpus only if
  §6.3's storage consent exists — a 409 means the caller did not grant it and nothing was
  attempted, a 503 means consent exists and Postgres does not. The console shows the two
  differently because they are different facts.
- **Render an uncleared chunk.** The citations panel shows chunk ids, doc codes, pages,
  tiers and retrieval dates — the row `docs/06` §5.2 asks for — and never a chunk body.
  §1.4.1: *"the screen may never carry a claim the voice channel is not cleared to speak"*,
  and there is no reference-material pane here for the same reason there is none on the
  caller's page.
- **Be indexed.** `noindex, nofollow, no-referrer`. The correct number of search engines
  that have seen a stranger's troubleshooting session is zero.
