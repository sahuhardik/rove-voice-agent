// The doodle kit: every drawn shape on the page, as inline SVG.
//
// Three rules hold this file together, and all three are about *not* adding a
// dependency to a page that deliberately has none:
//
// 1. **Inline, never fetched.** No `<img>`, no sprite sheet, no icon font, no
//    network request. The markup is the artwork, so it ships in the same
//    bundle as everything else and cannot 404 on a slow link.
// 2. **`currentColor` for every stroke.** The CSS owns the palette; these
//    shapes inherit whatever colour the element they sit in already has. The
//    few deliberate flat fills read a custom property with a literal fallback,
//    so a shape still looks right if the stylesheet ever changes under it.
// 3. **Decoration only.** Every export is `aria-hidden` and `focusable="false"`.
//    Each one sits beside real text that already says what it means — the icon
//    is never the label, so a screen reader loses nothing by skipping it and a
//    keyboard user never tabs into an empty box.
//
// Nothing here holds state, takes a callback, or knows what the app does.

/** Shared geometry for the four panel marks. Stroked, round-capped, 24×24. */
const strokeProps = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2.2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Svg({ viewBox = '0 0 24 24', className, children }) {
  return (
    <svg
      className={className}
      viewBox={viewBox}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

/**
 * The little dashcam who introduces the page.
 *
 * It is the product with a face on it: the body is the camera, the lens is the
 * eye, and the stubby arm on top is the windscreen mount. Drawn once, large,
 * in the masthead — a mascot that appeared beside every panel would stop being
 * friendly and start being noise.
 */
export function Mascot({ className }) {
  return (
    <Svg viewBox="0 0 72 64" className={className}>
      {/* mount arm and suction cup */}
      <path d="M36 14V8" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" />
      <ellipse cx="36" cy="6" rx="9" ry="4" fill="var(--grape, #8b6bd9)" />
      {/* body */}
      <rect
        x="6"
        y="14"
        width="60"
        height="42"
        rx="14"
        fill="var(--sun, #ffd25e)"
        stroke="currentColor"
        strokeWidth="3.4"
      />
      {/* lens barrel */}
      <circle
        cx="27"
        cy="35"
        r="13"
        fill="var(--sky, #bfe3ff)"
        stroke="currentColor"
        strokeWidth="3.4"
      />
      <circle cx="27" cy="35" r="6" fill="currentColor" />
      <circle cx="23.5" cy="31.5" r="2.4" fill="#ffffff" />
      {/* recording light, and a smile that belongs to the body not the lens */}
      <circle cx="56" cy="24" r="3.4" fill="var(--bad, #d6453c)" />
      <path
        d="M48 38c0 4.4-3.4 7.6-7.4 7.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
    </Svg>
  )
}

/** Transcript — two speech bubbles, because a transcript is two people. */
export function IconTranscript({ className }) {
  return (
    <Svg className={className}>
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h7A2.5 2.5 0 0 1 15 7.5v3A2.5 2.5 0 0 1 12.5 13H8l-3.5 2.8V13A2.5 2.5 0 0 1 3 10.5Z" {...strokeProps} />
      <path d="M18 9.5a2.5 2.5 0 0 1 2.5 2.5v3a2.5 2.5 0 0 1-1.5 2.3v2.4L15.5 17" {...strokeProps} />
    </Svg>
  )
}

/** Current step — a flag on a pole: the one thing we are trying right now. */
export function IconStep({ className }) {
  return (
    <Svg className={className}>
      <path d="M6 21V4" {...strokeProps} />
      <path d="M6 5h9.5l-1.8 3.4 1.8 3.4H6" {...strokeProps} />
      <circle cx="6" cy="21" r="0.1" {...strokeProps} />
    </Svg>
  )
}

/** Diagnostic state — a clipboard: what we have written down so far. */
export function IconState({ className }) {
  return (
    <Svg className={className}>
      <rect x="4.5" y="4.5" width="15" height="16" rx="3.5" {...strokeProps} />
      <path d="M9 4.5V3.6A1.6 1.6 0 0 1 10.6 2h2.8A1.6 1.6 0 0 1 15 3.6v.9" {...strokeProps} />
      <path d="M8.5 11h7M8.5 15h4.5" {...strokeProps} />
    </Svg>
  )
}

/** Session trace — a line that happened, with the moments marked on it. */
export function IconTrace({ className }) {
  return (
    <Svg className={className}>
      <path d="M3 17c3 0 3-9 6-9s3 6 6 6 3-7 6-7" {...strokeProps} />
      <circle cx="9" cy="8" r="1.9" fill="currentColor" />
      <circle cx="15" cy="14" r="1.9" fill="currentColor" />
    </Svg>
  )
}

/** A paper plane, for the composer's submit button. */
export function IconSend({ className }) {
  return (
    <Svg className={className}>
      <path d="M20.5 3.5 10.5 13.5" {...strokeProps} />
      <path d="M20.5 3.5 14.3 20.5l-3.8-7-7-3.8Z" {...strokeProps} />
    </Svg>
  )
}

/** A microphone, for anything that talks about the voice leg. */
export function IconMic({ className }) {
  return (
    <Svg className={className}>
      <rect x="9" y="2.5" width="6" height="11" rx="3" {...strokeProps} />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0" {...strokeProps} />
      <path d="M12 17.5V21M9 21h6" {...strokeProps} />
    </Svg>
  )
}

/**
 * A soft background blob.
 *
 * Purely atmospheric, sized and placed by CSS, and `aria-hidden` like the rest.
 * It exists so the page has something rounded behind the panels instead of a
 * flat wash, which is most of what makes a layout read as drawn rather than
 * printed.
 */
export function Blob({ className }) {
  return (
    <Svg viewBox="0 0 200 200" className={className}>
      <path
        d="M44 22c22-16 58-14 82 2s38 46 30 72-34 44-62 48-58-6-72-28-0-62 22-78Z"
        fill="currentColor"
      />
    </Svg>
  )
}
