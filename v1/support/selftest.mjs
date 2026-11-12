// Parse, wiring and escaping checks for the console (`docs/06` §5.2, §1.4).
//
//     node support/build.mjs && node support/selftest.mjs
//
// `server/test_support.py` runs this, and it exists because the other tests
// cannot: they assert that `/support/assets/main.js` is *served*, which a file
// with a syntax error does perfectly well. Three things are checked here and
// each one is a failure that would otherwise reach a human mid-session:
//
// 1. **Every module parses.** A `SyntaxError` in `panels.js` is a blank console.
// 2. **Every element `main.js` reaches for exists in `index.html`.** A renamed
//    id is a button that silently does nothing — and on this page the buttons
//    are the §6.3 disclosure and the §5.3 join.
// 3. **The panels escape.** `panels.js` renders a stranger's typed words and
//    carries `verbatim_symptom` word for word, on purpose (§5.2). Word for word
//    includes the words that look like markup.
//
// A stub DOM rather than a headless browser: the thing under test is this code,
// and importing it under a stub is enough to prove it parses and binds. What a
// real browser would add — layout, CSS, actual event dispatch — is not what
// these three failures live in.

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const DIST = join(HERE, 'dist')
const ASSETS = join(DIST, 'assets')

// --------------------------------------------------------------------------
// A stub DOM, built from the ids `index.html` actually declares
// --------------------------------------------------------------------------

const html = readFileSync(join(DIST, 'index.html'), 'utf8')
const declaredIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]))
assert.ok(declaredIds.size > 5, 'index.html declares almost no ids — did the build run?')

/** Ids `main.js` asked for. Anything not in `declaredIds` is a wiring bug. */
const requestedIds = new Set()

function stubElement(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    className: '',
    value: '',
    hidden: false,
    disabled: false,
    dataset: {},
    addEventListener() {},
    closest: () => null,
  }
}

const elements = new Map()

globalThis.document = {
  getElementById(id) {
    requestedIds.add(id)
    if (!elements.has(id)) elements.set(id, stubElement(id))
    return elements.get(id)
  },
}

globalThis.window = {
  location: { protocol: 'http:', host: 'localhost:8080' },
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: () => 0,
  confirm: () => false,
}
globalThis.WebSocket = class {
  static OPEN = 1
  constructor() {
    this.readyState = 0
  }
  close() {}
  send() {}
}
globalThis.fetch = async () => {
  throw new Error('selftest does not reach the network')
}

// --------------------------------------------------------------------------
// 1 & 2 — every module parses, and every id it binds to exists
// --------------------------------------------------------------------------

const panels = await import(pathToFileURL(join(ASSETS, 'panels.js')).href)
await import(pathToFileURL(join(ASSETS, 'api.js')).href)
await import(pathToFileURL(join(ASSETS, 'socket.js')).href)
// Last, because this one binds the handlers on import.
await import(pathToFileURL(join(ASSETS, 'main.js')).href)

assert.ok(requestedIds.size > 0, 'main.js bound to nothing — it did not run')

// Importing only exercises the ids `main.js` touches at module scope — the
// seven handler bindings. The ids inside `render()` and `openSession()` are
// reached on a live session, which is exactly when a typo in one would first
// be noticed, so they are checked statically instead.
const mainSource = readFileSync(join(ASSETS, 'main.js'), 'utf8')
for (const match of mainSource.matchAll(/\$\('([^']+)'\)/g)) requestedIds.add(match[1])
for (const match of mainSource.matchAll(/getElementById\('([^']+)'\)/g)) {
  requestedIds.add(match[1])
}

const missing = [...requestedIds].filter((id) => !declaredIds.has(id))
assert.deepEqual(
  missing,
  [],
  `main.js reaches for ids index.html does not declare: ${missing.join(', ')}`,
)
assert.ok(
  requestedIds.size >= 15,
  `only ${requestedIds.size} ids found in main.js — the static scan missed them`,
)

// --------------------------------------------------------------------------
// 3 — the panels escape what they render
// --------------------------------------------------------------------------

const payload = '<img src=x onerror="alert(1)">'

assert.equal(
  panels.esc(payload),
  '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
  'esc() let markup through',
)

const rendered = [
  panels.transcriptPanel([{ role: 'caller', text: payload, turn: 1, modality: 'typed' }]),
  // §5.2 carries `verbatim_symptom` word for word. Word for word, escaped.
  panels.handoffPanel({ user_said: { verbatim: payload }, device: {}, context: {} }),
  panels.claimsPanel([{ claim: payload, turn: 1, citations: [] }]),
  panels.ledgerPanel([{ step_id: payload, count: 1, source: 'agent', outcome: 'no change' }]),
  panels.roomList([
    {
      room: payload,
      duration_s: 1,
      turn: 1,
      taxonomy_id: 'SD-01',
      agent_mode: 'proposing',
      humans_present: [],
    },
  ]),
  panels.tracePanel([{ type: payload, elapsed_s: 1 }]),
  // Every panel in this list is handed the payload somewhere, so that the
  // "escaped, not dropped" assertion below means something for all of them.
  panels.consentPanel({ display: payload, storage: 'undecided', jurisdiction: 'two_party' }),
  panels.statePanel({ fsm_state: payload, turn: 1 }, { agentMode: 'proposing', participants: [] }),
]

for (const [index, markup] of rendered.entries()) {
  // The tag is what matters: `onerror=` as *text* is harmless once the angle
  // brackets and quotes around it are entities, and asserting on the attribute
  // name alone would fail on correctly escaped output.
  assert.ok(
    !markup.includes('<img'),
    `panel ${index} rendered an unescaped tag from session data`,
  )
  assert.ok(
    !markup.includes('onerror="alert'),
    `panel ${index} rendered an unescaped attribute from session data`,
  )
  assert.ok(
    markup.includes('&lt;img'),
    `panel ${index} dropped the payload instead of escaping it — ` +
      '§5.2 carries verbatim_symptom word for word',
  )
}

// The consent panel must never say "stored" when nothing is (§6.3).
const undecided = panels.consentPanel({
  display: 'undecided',
  storage: 'undecided',
  jurisdiction: 'two_party',
  may_display: true,
  may_store: false,
})
assert.ok(undecided.includes('nothing is stored'), 'the §6.3 default is not visible')
assert.ok(!undecided.includes('may be collected'), 'the panel claimed collection is allowed')

console.log(
  `support console selftest: ${rendered.length} panels escaped, ` +
    `${requestedIds.size} ids bound, all declared in index.html`,
)
