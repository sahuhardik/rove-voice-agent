"""Step 2 of the knowledge pipeline: compile clean text into knowledge packs.

    python -m knowledge.compile_packs            # all packs
    python -m knowledge.compile_packs R3 general # just these

Each pack is a Markdown file the live agent reads in full. Packs are drafts
until a person from support has reviewed them; `factcheck.py` flags any number
in a pack that the sources do not contain.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rove import bedrock, config

HERE = Path(__file__).resolve().parent
CLEAN = HERE / "clean"
PACKS = HERE / "packs"

#: The symptom areas every pack's playbook must consider (from docs/02's taxonomy,
#: written as the customer would say it).
ISSUE_CHECKLIST = """\
Wi-Fi: phone joins camera Wi-Fi then drops / "no internet"; camera Wi-Fi not in the list; password rejected; connection drops repeatedly; playback/download very slow
Firmware: update stalled; won't boot after update (stuck on logo); something stopped working after update; can't do the update (no computer / file confusion)
App: app says no device found; app broke after phone OS update; stuck on permission/setup screen; won't pair with a new phone; sign-in error
Recording: missing footage of a specific incident; on but not recording; loop recording overwrote wanted files; nothing recorded while parked; stops recording after a while
Memory card: card error / camera doesn't see card; card full and stopped instead of looping; corrupt files; card keeps failing / needs reformatting; "memory card too slow"
Power: completely dead; hot / misbehaves in heat; restarts randomly / turns on and off repeatedly; doesn't power down when parked / drains car battery; doesn't keep date and time; frozen screen
Video/audio: blurry video / unreadable number plates; no audio; rear or cabin camera not showing; GPS / speed not showing"""

PACK_SYSTEM = """\
You are a senior support engineer at Rove, the dash cam company. You are turning \
source documents into a knowledge pack that a voice support agent will read in \
full before every conversation about this camera. The agent uses it to diagnose \
problems and to give exact instructions, so it must be precise, practical and \
faithful to the sources.

Absolute rules:
- Use ONLY facts stated in the source text. Never add specs, menu names, button \
names, numbers or procedures from general knowledge. If the sources do not \
cover something, say so in the "Not covered by the sources" section.
- Copy numbers, model names, menu labels and button names exactly as written.
- After every fact or procedure, cite the source in square brackets using its \
short name, e.g. [manual: User Manual For New R2-4K] or [help: memory-card-too-slow].
- Never state a firmware version number. Say "the latest firmware from Rove's \
firmware page" instead.
- Mark every step that erases footage or settings with **DESTRUCTIVE** and say \
what is lost.
- Write for an agent that will speak to a customer: short, concrete steps."""

MODEL_TEMPLATE = """\
Build the knowledge pack for: {display_name} (internal id {model_id}).
{source_note}
Use exactly this structure:

# {display_name} — knowledge pack

## How to recognise this model
Physical and on-screen cues a customer can check (lenses, screen, buttons vs touch, \
power connector, Wi-Fi network name pattern, labels), and how it differs from other \
Rove models where the sources say so.

## Key facts
Power and battery/supercapacitor behaviour, memory card requirements (type, speed \
class, capacity limits, format), video resolutions, Wi-Fi band, GPS, parking mode \
requirements, operating temperature, LED/indicator meanings. One bullet each.

## How-to procedures
Numbered, exact button/menu steps for every procedure the sources describe: power \
on/off, format the card, reset to defaults, set date/time and time zone, connect to \
the phone app over Wi-Fi, download/playback footage, lock/protect a file, parking \
mode, motion detection, G-sensor, loop recording, audio on/off, firmware update, \
and anything else covered.

## Troubleshooting playbook
For each symptom below that the sources give ANY relevant information for, write:
### <symptom in the customer's words>
- Likely causes, most likely first (from the sources)
- Questions or checks that tell the causes apart (cheapest first)
- Fixes, in order, with exact steps or a pointer to the procedure above
- When to escalate to a human
Symptom checklist:
{checklist}

## Safety and data-loss warnings
Heat, power, mounting, driving, and every destructive action.

## Not covered by the sources
Important things a support agent might need that these sources do not state.

SOURCES (each begins with '===== SOURCE: path ====='):
{sources}"""

GENERAL_TEMPLATE = """\
Build the GENERAL knowledge pack from Rove's Help Center and official support pages. \
It applies to all Rove models unless a fact says otherwise; say which models when \
the source names them.

Use exactly this structure:

# Rove general support — knowledge pack

## Support contacts and hours

## Troubleshooting articles
One section per article topic, in the customer's words. For each: what the article \
says the causes are, the checks, the fixes in order (exact steps), and what it says \
to do if the fix fails. Keep every concrete detail (card classes, distances, \
settings names, times).

## Firmware and app guidance
How to update firmware and connect the app, per the sources.

## Safety and data-loss warnings

## Not covered by the sources

Make sure these customer symptoms are covered wherever the sources allow:
{checklist}

SOURCES (each begins with '===== SOURCE: path ====='):
{sources}"""

IDENTIFY_TEMPLATE = """\
Below are the "How to recognise this model" sections of every Rove knowledge pack, \
plus the registry of model names and aliases. Write a short guide (under 700 words) \
the voice agent uses to work out WHICH Rove camera a customer has when they don't \
know the model name.

Structure:
# Identifying the customer's Rove camera
## Ask in this order
The 3-5 cheapest, most discriminating questions (e.g. look at the label, number of \
lenses, screen vs no screen, power connector), and what each answer narrows it to.
## Model-by-model cues
One short bullet list per model.
## If it still can't be pinned down
What to do (proceed with general guidance, state the uncertainty, never guess).

Use only the facts given. Keep the citations they carry.

REGISTRY:
{registry}

SECTIONS:
{sections}"""


def short_name(path: str) -> str:
    p = Path(path)
    kind = "help" if "help-center" in path else "official" if "official" in path else "manual"
    return f"{kind}: {p.stem}"


def label_sources(text: str) -> str:
    return re.sub(
        r"===== SOURCE: (.+?) =====",
        lambda m: f"===== SOURCE: {m.group(1)} (cite as [{short_name(m.group(1))}]) =====",
        text,
    )


def compile_one(name: str, registry: dict) -> tuple[str, int]:
    sources = label_sources((CLEAN / f"{name}.txt").read_text(encoding="utf-8"))
    if name == "general":
        prompt = GENERAL_TEMPLATE.format(checklist=ISSUE_CHECKLIST, sources=sources)
    else:
        info = registry["models"][name]
        note = f"NOTE: {info['source_note']}" if info.get("source_note") else ""
        prompt = MODEL_TEMPLATE.format(
            display_name=info["display_name"], model_id=name, source_note=note,
            checklist=ISSUE_CHECKLIST, sources=sources,
        )
    text = bedrock.ask(config.OFFLINE_MODEL, prompt, system=PACK_SYSTEM, max_tokens=24000)
    (PACKS / f"{name}.md").write_text(text.strip() + "\n", encoding="utf-8")
    return name, len(text)


def compile_identify(registry: dict) -> int:
    sections = []
    for model in registry["models"]:
        pack = (PACKS / f"{model}.md").read_text(encoding="utf-8")
        m = re.search(r"## How to recognise this model\n(.*?)(?=\n## )", pack, re.S)
        sections.append(f"### {model}\n{m.group(1).strip() if m else '(missing)'}")
    reg = {k: {"display_name": v["display_name"], "aliases": v["aliases"]} for k, v in registry["models"].items()}
    prompt = IDENTIFY_TEMPLATE.format(registry=json.dumps(reg, indent=1), sections="\n\n".join(sections))
    text = bedrock.ask(config.OFFLINE_MODEL, prompt, system=PACK_SYSTEM, max_tokens=3000)
    (PACKS / "identify.md").write_text(text.strip() + "\n", encoding="utf-8")
    return len(text)


def main(names: list[str]) -> None:
    registry = json.loads((HERE / "registry.json").read_text(encoding="utf-8"))
    PACKS.mkdir(exist_ok=True)
    wanted = names or list(registry["models"]) + ["general"]
    targets = [n for n in wanted if n != "identify"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, size in pool.map(lambda n: compile_one(n, registry), targets):
            print(f"compiled {name}: {size} chars", flush=True)
    if not names or "identify" in names:
        print(f"compiled identify: {compile_identify(registry)} chars", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
