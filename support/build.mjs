// Build the support console (`docs/06` §5.3, `docs/07` D-17, §9.3 item 14).
//
//     node support/build.mjs            → support/dist
//     node support/build.mjs --base /x  → served under a different path
//
// **Node's standard library and nothing else.** No `npm install`, no lockfile,
// no `node_modules` under `support/`. That is a deliberate difference from
// `client/`, which is React behind Vite because `docs/07` D-15 chose React for
// *the caller's page* — a live, bidirectional surface whose framework choice
// D-15 says "is made by the voice framework, not by the UI", on the strength of
// LiveKit's React bindings (D-02). None of that reasoning reaches here: this
// console holds no media track, joins no room with an SDK, and renders from
// JSON over one WebSocket. D-15's own flip condition to "B (no framework)" is
// "the UI is still four panels", and D-15's alternative B was rejected on
// "the UI grows" — for the caller's page. An internal console that one person
// at a time reads over a caller's shoulder is the case where B's argument wins,
// and the cost of being wrong is rewriting seven small files.
//
// So "building" is: copy the ES modules, copy the stylesheet, and substitute
// the two placeholders in `index.html`. Browsers have loaded ES modules
// natively for years; there is nothing here that needs transpiling and a
// bundler would only add a thing to keep current.
//
// The output is `support/dist`, which `server/config.py` calls `console_dist`
// and `server/app.py` serves at `/support`. It is **not** committed — the same
// rule as `client/dist`, for the same reason: a build output in git is a second
// source of truth that will eventually disagree with the first.

import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, 'src')
const DIST = join(HERE, 'dist')
const ASSETS = join(DIST, 'assets')

/** `--base /support` → the path the console is served under. */
function argBase(argv) {
  const index = argv.indexOf('--base')
  if (index === -1) return '/support'
  const value = argv[index + 1]
  if (!value || value.startsWith('--')) {
    throw new Error('--base needs a path, e.g. --base /support')
  }
  return value.replace(/\/+$/, '')
}

/**
 * A build id a human can act on.
 *
 * The console renders another person's live session and the first question
 * about anything odd on screen is "which build is that?". A commit plus a
 * dirty marker answers it; a version number nobody bumps does not. Falls back
 * to a timestamp outside a git checkout.
 */
function buildId() {
  try {
    const sha = execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: HERE,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    const dirty = execFileSync('git', ['status', '--porcelain'], {
      cwd: HERE,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    return dirty ? `${sha}+dirty` : sha
  } catch {
    return new Date().toISOString().slice(0, 19).replace('T', ' ')
  }
}

function build(argv = process.argv.slice(2)) {
  const base = argBase(argv)
  const id = buildId()

  rmSync(DIST, { recursive: true, force: true })
  mkdirSync(ASSETS, { recursive: true })

  // Every module and the stylesheet, flat under `assets/`. Flat because the
  // imports in `main.js` are relative (`./panels.js`), so one directory keeps
  // the paths the same in `support/src` and in the served tree — which means
  // the files that run in a browser are the files on disk, and a stack trace
  // from the console names something you can open.
  const copied = []
  for (const name of readdirSync(SRC).sort()) {
    if (!/\.(js|css)$/.test(name)) continue
    cpSync(join(SRC, name), join(ASSETS, name))
    copied.push(name)
  }
  if (!copied.includes('main.js')) {
    throw new Error(`no main.js in ${SRC} — nothing would load`)
  }
  if (!copied.includes('console.css')) {
    throw new Error(`no console.css in ${SRC} — index.html links it`)
  }

  const html = readFileSync(join(HERE, 'index.html'), 'utf8')
  if (!html.includes('__BASE__') || !html.includes('__BUILD__')) {
    throw new Error('index.html is missing __BASE__ or __BUILD__')
  }
  writeFileSync(
    join(DIST, 'index.html'),
    html.replaceAll('__BASE__', base).replaceAll('__BUILD__', id),
  )

  console.log(`support console → ${DIST}`)
  console.log(`  base   ${base}`)
  console.log(`  build  ${id}`)
  console.log(`  assets ${copied.join(', ')}`)
  return { dist: DIST, base, build: id, assets: copied }
}

build()
