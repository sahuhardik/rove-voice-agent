// The click-or-type path (`docs/06` §1.4, §1.4.1).
//
// Two inputs, one event. The quick answers are buttons because the common
// replies in this session type are one word long and a button is faster and
// more reliable than either typing or speaking them — §2.3 notes that a click
// "short-circuits the hangover entirely". The text field is for the strings
// §3.4 calls confusable: SSIDs, serial numbers, card markings, error text.
//
// Both go out as `user.text` with a `modality` label and nothing else
// different, because §1.4.1 requires that the core cannot tell them apart.

import { useRef, useState } from 'react'

const QUICK_ANSWERS = ['Yes', 'No', 'Done that', 'Not sure', "It didn't help", 'That fixed it']

/**
 * How often a keystroke is allowed to reach the endpointer.
 *
 * §2.3 only needs to know that typing is *happening*; `note_typing` stamps a
 * float and nothing more. One signal a second says that as well as thirty do,
 * and does not put a packet on the media plane per character.
 */
const TYPING_SIGNAL_MS = 1000

export default function Composer({ disabled, awaiting, step, onSend, onTyping }) {
  const [value, setValue] = useState('')
  const lastTypingAt = useRef(0)
  const blocked = disabled || awaiting

  // §2.3: "someone part-way through typing an SSID has not finished". The
  // endpointer is told, rather than left to read it as silence and close the
  // turn on half an answer.
  function typed(next) {
    setValue(next)
    const now = Date.now()
    if (onTyping && next && now - lastTypingAt.current >= TYPING_SIGNAL_MS) {
      lastTypingAt.current = now
      onTyping()
    }
  }

  function submit(event) {
    event?.preventDefault()
    if (blocked) return
    if (onSend(value, 'typed')) setValue('')
  }

  function quick(answer) {
    if (blocked) return
    onSend(answer, 'click')
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className="quick">
        {QUICK_ANSWERS.map((answer) => (
          <button
            type="button"
            key={answer}
            className="chip"
            disabled={blocked}
            onClick={() => quick(answer)}
          >
            {answer}
          </button>
        ))}
      </div>
      <div className="composer-row">
        <input
          type="text"
          value={value}
          disabled={blocked}
          placeholder={
            disabled
              ? 'Join the room to start'
              : step
                ? 'Answer, or type anything the microphone would mangle'
                : 'Tell me what the camera is doing'
          }
          onChange={(event) => typed(event.target.value)}
          aria-label="Message"
        />
        <button className="primary" type="submit" disabled={blocked || !value.trim()}>
          {awaiting ? 'Working…' : 'Send'}
        </button>
      </div>
    </form>
  )
}
