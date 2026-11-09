"""Per-session consent (`docs/06` §6.3).

§6.3 opens by saying this is a legal decision and not an engineering one, and
then states the one thing engineering *is* on the hook for:

> The architecture is built so that the answer is configurable and so that the
> **unsafe default is impossible**.

That sentence is the whole specification for this module. It is implemented as
three rules, and each one is a property of the type rather than a convention
the call sites are trusted to keep.

**Rule 1 — nothing is stored until a storage decision exists.**
:meth:`ConsentState.may_store` returns ``True`` for exactly one value of one
field: ``storage == "granted"``. Not "not declined", not "undecided means the
operator's default" — granted, explicitly, and recorded with when and by what
modality. Every write path in `server/transcripts.py` asks this question first
and raises before it opens a database connection, so an un-consented session
does not reach the network, let alone the disk. The same gate governs the audio
tap §6.3 puts "at the WebRTC edge, on the server side of the room": Phase 3
owns that tap, this owns the predicate it is gated on
(:meth:`may_record_audio`).

**Rule 2 — display and storage are separate decisions.**

> the **live transcript is rendered in the browser whether or not it is
> retained**, so "displayed" and "stored" are separate decisions and the
> consent gate governs storage, not display.

So they are two fields, decided independently, and granting one does not move
the other. The asymmetry between them is deliberate and matches the sentence
above: display is refused only when the caller has *declined* it, because
rendering a caller's own words back into their own browser retains nothing;
storage is permitted only when the caller has *granted* it, because it does.
A caller who declines everything still gets full service — §6.3 says so, and
the diagnostic state record, which the handoff needs, is not transcript and is
not gated here.

**Rule 3 — a decision requires a prior disclosure.**
§6.3 puts disclosure in ``GREET``, "before any diagnostic exchange, in one
sentence, spoken *and* shown — a consent notice that only exists in audio the
user may have missed is weak evidence of consent". :meth:`decide` refuses a
decision that has no :meth:`disclose` before it, so a UI that forgot to show
the notice cannot produce a record that claims the caller agreed to it.

**The jurisdiction matrix** §6.3 names is the one configurable part:
``two_party`` requires an affirmative answer, ``one_party`` treats the
disclosure itself as sufficient for *display* and still requires an explicit
grant for *storage*. The default is ``two_party``, which is the stricter
reading, because the unsafe default has to be the impossible one.

**The second consent surface**, at escalation (§6.3, §5.3): a human joining the
room can hear the caller and read the transcript, "and the agent makes it
before the join, not after". :meth:`disclose_escalation` records that, and
`server/support.py` refuses the join without it.

What this module deliberately does **not** do: decide any of the open questions
in `docs/06` §9.3 item 4. It makes them configurable and it makes the wrong
answer unreachable. The jurisdictions, the retention clocks and the wording are
Legal's.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

#: The three values a decision can hold. `undecided` is not a third kind of
#: yes: `may_store` reads it as no, every time.
UNDECIDED = "undecided"
GRANTED = "granted"
DECLINED = "declined"
DECISIONS = frozenset({UNDECIDED, GRANTED, DECLINED})

#: The two decisions §6.3 keeps apart.
DISPLAY = "display"
STORAGE = "storage"
KINDS = (DISPLAY, STORAGE)

#: §6.3's "one-party/two-party jurisdiction matrix", as the only knob. Which
#: jurisdiction a given session is in is not something this process can know;
#: it is configuration, and `docs/06` §9.3 item 4 owns the mapping.
TWO_PARTY = "two_party"
ONE_PARTY = "one_party"
JURISDICTIONS = frozenset({TWO_PARTY, ONE_PARTY})

#: Retention classes (§6.3, "Two retention classes"). Only `evaluation` is
#: gated by `storage`; `operational` is the handoff payload and the outcome
#: tag, which are not transcript and are kept because the support case needs
#: them.
RETENTION_OPERATIONAL = "operational"
RETENTION_EVALUATION = "evaluation"


class ConsentError(RuntimeError):
    """A consent operation that would produce a record that is not true."""


@dataclass
class ConsentState:
    """One session's consent record. Two decisions, never collapsed into one."""

    #: Whether the live transcript may be rendered. §6.3: rendering is not
    #: retention, so this is refused only on an explicit decline.
    display: str = UNDECIDED
    #: Whether anything may be written anywhere. §6.3: granted or nothing.
    storage: str = UNDECIDED
    jurisdiction: str = TWO_PARTY

    #: When the GREET disclosure was made, and what the caller was shown. A
    #: decision with no disclosure before it is refused.
    disclosed_at: float | None = None
    disclosure_text: str = ""
    #: §6.3 wants the notice "spoken *and* shown". Both are recorded; a
    #: disclosure that was only one of them is still a disclosure, but the
    #: record says which, so the evidence can be judged rather than assumed.
    disclosed_spoken: bool = False
    disclosed_shown: bool = False

    display_decided_at: float | None = None
    storage_decided_at: float | None = None
    #: voice | typed | click (§1.4.1, and §6.4's "a click on an affirmative
    #: control counts as consent and is recorded as such, with the modality
    #: stored").
    display_modality: str = ""
    storage_modality: str = ""

    #: The §5.3 / §6.3 second surface: the human join is its own disclosure,
    #: and it happens before the join.
    escalation_disclosed_at: float | None = None
    escalation_disclosure_text: str = ""

    history: list[dict[str, Any]] = field(default_factory=list)

    # -- the gates -------------------------------------------------------

    def may_display(self) -> bool:
        """May the live transcript be rendered? (§6.3 — not a retention question.)"""
        return self.display != DECLINED

    def may_store(self) -> bool:
        """May *anything* be written to the pilot corpus? One value: granted.

        This is the predicate `docs/06` §6.3's "Recording is off until a
        consent decision exists for the session" reduces to. `undecided` is a
        no and stays a no; there is no operator default that turns it into a
        yes, because a default that could would be the unsafe default §6.3
        says must be impossible.
        """
        return self.storage == GRANTED

    def may_record_audio(self) -> bool:
        """The predicate the §6.3 WebRTC-edge audio tap is gated on.

        Identical to :meth:`may_store` today, and named separately because the
        tap is Phase 3's and will want to ask this question by its own name.
        Phase 2b/4 write no audio at all under any answer.
        """
        return self.may_store()

    def may_retain(self, retention_class: str) -> bool:
        """§6.3's two retention classes, as one question.

        `operational` — the handoff payload and the outcome tag — is not
        transcript and is kept regardless: §6.3 is explicit that a caller who
        declines "still gets full service" and that "the diagnostic state
        record is kept (it is needed for the handoff)". `evaluation` is the
        corpus, and it is gated.
        """
        if retention_class == RETENTION_OPERATIONAL:
            return True
        if retention_class == RETENTION_EVALUATION:
            return self.may_store()
        raise ConsentError(f"unknown retention class {retention_class!r}")

    @property
    def requires_affirmative(self) -> bool:
        """Two-party: an announcement is not an answer (§6.3)."""
        return self.jurisdiction == TWO_PARTY

    @property
    def decided(self) -> bool:
        """Both decisions have been taken, either way."""
        return self.display != UNDECIDED and self.storage != UNDECIDED

    # -- recording the decisions ------------------------------------------

    def disclose(
        self,
        *,
        text: str,
        spoken: bool = False,
        shown: bool = False,
        now: float | None = None,
    ) -> "ConsentState":
        """Record the GREET disclosure (§6.3). Idempotent on the first one.

        Raises:
            ConsentError: If neither `spoken` nor `shown` is true — a
                disclosure nobody received is not a disclosure.
        """
        if not (spoken or shown):
            raise ConsentError(
                "a disclosure must be spoken, shown, or both — §6.3 wants both"
            )
        if not text.strip():
            raise ConsentError("a disclosure must say something")
        stamp = time.time() if now is None else now
        if self.disclosed_at is None:
            self.disclosed_at = stamp
            self.disclosure_text = text
        self.disclosed_spoken = self.disclosed_spoken or bool(spoken)
        self.disclosed_shown = self.disclosed_shown or bool(shown)
        self._log("disclosed", spoken=bool(spoken), shown=bool(shown), at=stamp)
        return self

    def decide(
        self,
        kind: str,
        decision: str,
        *,
        modality: str = "click",
        now: float | None = None,
    ) -> "ConsentState":
        """Record one decision — display *or* storage, never both at once.

        Taking one argument for the kind rather than two booleans is the point:
        there is no call shape here that sets both in one go, so there is no
        way to write a UI control that quietly carries storage consent along
        with display consent.

        Raises:
            ConsentError: On an unknown kind or decision, or on a decision
                with no disclosure before it (§6.3).
        """
        if kind not in KINDS:
            raise ConsentError(f"consent kind must be one of {KINDS}, got {kind!r}")
        if decision not in (GRANTED, DECLINED):
            raise ConsentError(
                f"a decision is {GRANTED!r} or {DECLINED!r}, not {decision!r}"
            )
        if self.disclosed_at is None:
            raise ConsentError(
                "no disclosure has been made for this session — §6.3 puts the "
                "notice in GREET, before any decision can mean anything"
            )
        stamp = time.time() if now is None else now
        if kind == DISPLAY:
            self.display = decision
            self.display_decided_at = stamp
            self.display_modality = modality
        else:
            self.storage = decision
            self.storage_decided_at = stamp
            self.storage_modality = modality
        self._log("decided", kind=kind, decision=decision, modality=modality, at=stamp)
        return self

    def disclose_escalation(
        self, *, text: str, now: float | None = None
    ) -> "ConsentState":
        """The §5.3 / §6.3 second surface, recorded *before* the join."""
        if not text.strip():
            raise ConsentError("an escalation disclosure must say something")
        stamp = time.time() if now is None else now
        self.escalation_disclosed_at = stamp
        self.escalation_disclosure_text = text
        self._log("escalation_disclosed", at=stamp)
        return self

    @property
    def escalation_disclosed(self) -> bool:
        return self.escalation_disclosed_at is not None

    # -- projections -------------------------------------------------------

    def _log(self, event: str, **fields: Any) -> None:
        self.history.append({"event": event, **fields})

    def as_dict(self) -> dict[str, Any]:
        """What the console, the caller's page and the handoff all render."""
        return {
            "display": self.display,
            "storage": self.storage,
            "jurisdiction": self.jurisdiction,
            "requires_affirmative": self.requires_affirmative,
            "decided": self.decided,
            "disclosed": self.disclosed_at is not None,
            "disclosed_at": self.disclosed_at,
            "disclosure_text": self.disclosure_text,
            "disclosed_spoken": self.disclosed_spoken,
            "disclosed_shown": self.disclosed_shown,
            "display_decided_at": self.display_decided_at,
            "storage_decided_at": self.storage_decided_at,
            "display_modality": self.display_modality,
            "storage_modality": self.storage_modality,
            "escalation_disclosed": self.escalation_disclosed,
            "escalation_disclosed_at": self.escalation_disclosed_at,
            "may_display": self.may_display(),
            "may_store": self.may_store(),
            "may_record_audio": self.may_record_audio(),
        }

    def as_handoff_line(self) -> str:
        """§5.2's `recording + consent status` row, in its own words."""
        recorded = "y" if self.may_record_audio() else "n"
        if self.storage == GRANTED:
            status = "obtained"
        elif self.storage == DECLINED:
            status = "declined"
        else:
            status = "not-obtained"
        return f"recorded: {recorded} · consent: {status}"


#: §6.3: "Disclosure happens in `GREET`, before any diagnostic exchange, in one
#: sentence, spoken *and* shown." One sentence, and it names both decisions
#: separately because they are separate decisions.
DEFAULT_DISCLOSURE = (
    "Before we start: this conversation is transcribed live on your screen so "
    "you can read it, and nothing is kept unless you say we may keep it — "
    "either way I can help you just the same."
)

#: §5.3 / §6.3's second surface. Said before the join, never after.
DEFAULT_ESCALATION_DISCLOSURE = (
    "I'm bringing someone in now — stay on the page. They'll be able to hear "
    "you and read what we've said so far."
)
