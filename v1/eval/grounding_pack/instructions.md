# How to grade this pack

You are one of **two** people grading the same twenty claims. The point of
grading them twice is to find out whether two humans reading the same evidence
reach the same verdict. If you and the other grader talk first, that number is
worthless — it measures the conversation, not the rubric.

So: **grade alone, grade everything, then send the sheet back.**

## Who grades

| | |
| --- | --- |
| Grader 1 | **Hardik** |
| Grader 2 | **TBD — one more human** |

Grader 2 is a placeholder on purpose. Choosing the second grader is a human
decision and the run that built this pack did not make it. Anyone who can read
a support article and a sentence can do it; they do not need to have worked on
the agent, and there is an argument that it is better if they have not.

## What you are deciding

One question, per claim:

> **Does the chunk the line cites support that line _as stated_?**

Not whether the line is good advice. Not whether it is the right next step. Not
whether you would have said it that way. Only whether the evidence the agent
pointed at carries the thing the agent said.

The three verdicts and the edge rules are in **`rubric.md`**. Read it first and
keep it open — it is the same rubric the earlier single-grader gradings used,
so your verdicts can be read against theirs.

## The steps

1. **Read `rubric.md`.** All of it, once, before claim 1.
2. **Open `claims.json`.** Each entry has the claim, the full text of every
   chunk it cites, the scenario and turn it was spoken at, and how many times
   the agent said it across the run.

   If you would rather read it as text than as JSON:

   ```bash
   .venv/bin/python - <<'PY'
   import json, pathlib, textwrap
   pack = json.loads(pathlib.Path("eval/grounding_pack/claims.json").read_text())
   for c in pack["claims"]:
       where = c["first_spoken_at"] or {}
       print(f"\n=== {c['claim_id']} ({c['instances']} instance(s), first at "
             f"{where.get('harness')}:{where.get('scenario_id')} turn {where.get('turn')}) ===")
       print("CLAIM: " + c["claim"])
       for chunk in c["cited_chunks"]:
           print(f"\n  [{chunk['chunk_id']}] {chunk['section']}")
           print(textwrap.indent(textwrap.fill(chunk["text"], 88), "    "))
   PY
   ```

3. **Copy `sheet.csv`** to a file with your name in it, e.g.
   `sheet_hardik.csv`. Do not edit the shared `sheet.csv`.
4. **Fill in one column pair — yours, and only yours.** Grader 1 fills
   `grader_1_verdict` and `grader_1_note`; grader 2 fills `grader_2_verdict`
   and `grader_2_note`. Leave the other pair empty. The scorer works out which
   pair you used; it refuses a sheet with both pairs filled.
5. **Grade every one of the twenty.** A blank verdict is rejected, not treated
   as a zero — a denominator that is not 20 is not comparable to the earlier
   gradings.
6. **Write a note on every row**, including the ones you mark `supported`. One
   sentence is enough, but it has to name the part of the chunk that carried
   the claim, or the thing the chunk never says. The scorer rejects a graded
   row with an empty note: an ungrounded grade is not a grade.
7. **Send the file back** to whoever handed you the pack. Do not commit it over
   the blank `sheet.csv`.

## The independence rule, stated plainly

Before you have sent your sheet back:

* **Do not discuss any claim with the other grader.** Not "what did you put for
  C07", not "most of these look fine to me", not a face.
* **Do not read the other grader's sheet**, in progress or finished.
* **Do not read `eval/grounding_semantic.json`.** It holds an earlier
  single-grader grading of an overlapping set of claims, with that grader's
  verdicts and reasoning. Reading it first makes you a reviewer of their
  answers rather than an independent grader, and it will show up as agreement
  that was never earned.
* **Do not ask a model what it thinks of a claim.** `docs/06` §7.4 is explicit
  that an LLM judge ships only after it is validated against human labels.
  These are the labels. A model in the loop here contaminates the thing the
  judge would later be validated against.

Afterwards, discuss as much as you like. Disagreements are a finding, and the
scorer prints every one of them with both notes — that list is the most useful
thing this pack produces, because a claim two careful readers score differently
is usually a claim the rubric or the corpus is unclear about.

## What happens to your sheet

Both sheets go to:

```bash
.venv/bin/python -m eval.score_grading \
    eval/grounding_pack/sheet_hardik.csv \
    eval/grounding_pack/sheet_<second>.csv
```

which prints Cohen's κ between you, each grader's semantic grounding rate, the
per-harness split, and the verdict against the 100 % bar in `docs/06` §9.1.

κ is **reported, not passed or failed**: §7.4 says a judge ships "only above an
agreed κ" and names no number, so agreeing that number is a decision for the
people reading the output, not something this pack decides for them.
