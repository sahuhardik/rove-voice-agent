# Semantic grounding rubric

One question, asked of every claim in `claims.json`:

> **Does the chunk the line cites support that line _as stated_?**

Nothing else. Not whether the line is good advice, not whether it is a
sensible next step, not whether the agent should have said it — only
whether the cited evidence carries it.

## The three verdicts

- **`supported`** — the cited chunk states the fact the line asserts, or documents the condition/procedure the line asks about.
- **`partial`** — the chunk is on the same topic but does not contain the specific thing asserted or asked. Scores 0: the measurement is whether the chunk supports the claim AS STATED.
- **`unsupported`** — the chunk does not bear on the line at all. Scores 0.

## Edge rules

- Where a line cites several chunks, one supporting chunk is enough; the note says which one carried it.
- A question that offers an option the corpus does not name (a battery pack, an OS version) is still supported if the chunk carries the distinction the question turns on. The option is offered, not asserted.

## Scoring

| verdict | score |
| --- | --- |
| `supported` | 1 |
| `partial` | 0 |
| `unsupported` | 0 |

`partial` scoring 0 is the point of the measurement, not a harsh reading:
a citation attached to a claim it only half-carries scores full marks on
the structural layer, and that is the failure the two-layer split exists
to catch (`eval/grounding.py` module docstring).

## Where this rubric comes from

Carried over verbatim from `eval/grounding_semantic.json`, which is the
rubric the pre-4.4 (65 %) and post-4.4 (70 %) single-grader gradings used.
It is reused unchanged so this grading can be read against those, rather
than against a rubric that moved underneath them.

Pack built at commit `7cd2277`.
