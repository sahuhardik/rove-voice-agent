"""Chunking the Tier-1 corpus on disk.

Two parsers, one packer, one rule that beats all of them.

**The overriding rule: a procedure is atomic** (`docs/06` §4.2). The card-side
firmware update is format-in-camera -> copy unzipped files -> camera powered
and OFF -> insert card -> press Power once -> red LED -> *do not disconnect
power* -> it restarts -> format again. A boundary anywhere inside that
sequence can surface "insert the card and press power" without "the camera
must be off". `docs/02` calls FW-01 "High-risk entry: the wrong advice here
destroys the device." So a numbered run is never split, and if a run exceeds
the chunk budget, the chunk exceeds the budget.

Budget: 300-800 token-equivalents (`estimate_tokens`). Adjacent material is
merged up to 800 and a chunk is closed as soon as it reaches 300 and the next
piece starts a new top-level section, so section boundaries are respected
wherever the budget allows it.

Overlap: one sentence, carried forward from the previous chunk, but only when
the text actually continues -- never across a top-level section boundary.
Section headings are kept as `section_path` and restated in `context_header`,
which is `docs/06` §4.2's "rolling header ... so a retrieved chunk is
self-describing when read in isolation".
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from . import metadata as md

# Budget, in token-equivalents.
TARGET_MIN = 300
TARGET_MAX = 800

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

HEADING = "heading"
PARA = "para"
STEP = "step"
BULLET = "bullet"


@dataclass
class Block:
    kind: str
    text: str
    level: int = 0  # headings only: 1 = top
    page: int | None = None


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "head",
    "nav",
    "footer",
    "form",
    "select",
    "option",
    "iframe",
    "template",
    "aside",
}

_BLOCK_TAGS = {
    "p",
    "li",
    "div",
    "section",
    "article",
    "main",
    "tr",
    "td",
    "th",
    "blockquote",
    "figcaption",
    "br",
    "hr",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

#: Once one of these headings is reached, the article body is over and the
#: page's sidebar/footer furniture begins.
_STOP_HEADINGS = re.compile(
    r"^(categories|recent post|instagram|get in touch|information|useful links"
    r"|newsletter signup|confirm your age|come back when you'?re older"
    r"|get your rove r4 before official launch|related articles"
    r"|you may also like|follow us|customer service|leave a comment"
    r"|share this|subscribe)\b",
    re.I,
)

#: Furniture that appears inline rather than as a heading.
_BOILERPLATE = re.compile(
    r"^(all articles|search|home|menu|cart|skip to content|previous|next"
    r"|share|tweet|pin it|log ?in|sign ?up|powered by|privacy policy|terms"
    r"|refund policy|shipping policy|contact us|back to top|read more"
    r"|updated \d+ \w+ ago|was this (article )?helpful.*|\d+ of \d+|©.*"
    r"|copyright.*|email us|text us|📩.*|📲.*|\[email.*|watch how.?to videos?"
    r"|scan the qr code.*|just scan the qr code.*)$",
    re.I,
)

_UPDATED_SUFFIX_RE = re.compile(
    r"\s*Updated\s+(a|an|\d+)\s+\w+\s+ago\s*$", re.I
)

_NUMBERED_RE = re.compile(r"^\(?(\d{1,2})[.):]?\s+(?=\S)")
_STEP_WORD_RE = re.compile(r"^step\s*\d{1,2}\b", re.I)


class _HtmlBlocks(HTMLParser):
    """Collect block-level text runs, keeping heading levels and list type.

    A table row is assembled into a **single** block, with each cell labelled
    by its column heading. `docs/06` §4.2 wants `O2`'s per-model Wi-Fi table
    chunked one row per model, and §4.6 calls model filtering a safety
    control: a boundary between "ROVE R2-4K DUAL" and the network name in the
    next cell would hand the agent an SSID with no model attached to it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._buf: list[str] = []
        self._skip = 0
        self._heading: int | None = None
        self._list_stack: list[str] = []
        self._in_row = False
        self._row_cells: list[str] = []
        self._row_is_header = False
        self._columns: list[str] = []

    # -- buffer -----------------------------------------------------------
    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf.clear()
        if not text:
            return
        if self._in_row:
            self._row_cells.append(text)
            return
        if self._heading is not None:
            self.blocks.append(Block(HEADING, text, level=self._heading))
            return
        kind = PARA
        if self._list_stack and self._list_stack[-1] == "ol":
            kind = STEP
        elif self._list_stack:
            kind = BULLET
        elif _NUMBERED_RE.match(text) or _STEP_WORD_RE.match(text):
            kind = STEP
        self.blocks.append(Block(kind, text))

    def _end_row(self) -> None:
        self._flush()
        cells = [c for c in self._row_cells if c]
        self._in_row = False
        self._row_cells = []
        if not cells:
            self._row_is_header = False
            return
        if self._row_is_header:
            self._columns = cells
            self._row_is_header = False
            return
        if self._columns and len(cells) <= len(self._columns):
            labelled = [
                f"{self._columns[i]}: {cell}" for i, cell in enumerate(cells)
            ]
        else:
            labelled = cells
        self.blocks.append(Block(PARA, " | ".join(labelled)))

    # -- parser hooks -----------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            self._flush()
            self._columns = []
            return
        if tag == "tr":
            self._flush()
            self._in_row = True
            self._row_cells = []
            self._row_is_header = False
            return
        if tag == "th":
            self._flush()
            self._row_is_header = True
            return
        if tag in ("ol", "ul"):
            self._flush()
            self._list_stack.append(tag)
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
                self._heading = int(tag[1])

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "tr":
            self._end_row()
            return
        if tag == "table":
            if self._in_row:
                self._end_row()
            self._columns = []
            return
        if tag in ("ol", "ul"):
            self._flush()
            if self._list_stack:
                self._list_stack.pop()
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
                self._heading = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._buf.append(data)

    def close(self) -> None:  # noqa: D102
        super().close()
        if self._in_row:
            self._end_row()
        self._flush()


def _content_region(raw: str) -> str:
    """The article body. `<main>` on all 21 saved pages; fall back politely."""
    for tag in ("main", "article", "body"):
        match = re.search(rf"(?is)<{tag}[^>]*>(.*)</{tag}>", raw)
        if match:
            return match.group(1)
    return raw


def parse_html(path: Path) -> list[Block]:
    """Blocks from a saved page, with sidebar and footer furniture removed."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser = _HtmlBlocks()
    parser.feed(_content_region(raw))
    parser.close()

    out: list[Block] = []
    previous = ""
    for block in parser.blocks:
        text = html.unescape(block.text).strip()
        if block.kind == HEADING:
            # The Help Center renders "<title>Updated 9 months ago" as one h1.
            text = _UPDATED_SUFFIX_RE.sub("", text).strip()
        if block.kind == HEADING and _STOP_HEADINGS.match(text):
            break
        if _STOP_HEADINGS.match(text) and len(text) < 40:
            break
        if _BOILERPLATE.match(text):
            continue
        if len(text) < 3:
            continue
        if text == previous:  # the saved pages repeat nav text verbatim
            continue
        previous = text
        out.append(Block(block.kind, text, level=block.level))
    return _dedupe_runs(out)


def _dedupe_runs(blocks: list[Block]) -> list[Block]:
    """Drop a block whose text already appeared, keeping the first.

    The Gorgias pages render the same article twice (once for mobile), and
    the Shopify pages repeat menu entries. Deduplicating on exact text is
    enough and never touches genuinely repeated instructions, which differ in
    wording between models.
    """
    seen: set[str] = set()
    out: list[Block] = []
    for block in blocks:
        key = block.text.casefold()
        if block.kind != HEADING and key in seen:
            continue
        seen.add(key)
        out.append(block)
    return out


# ---------------------------------------------------------------------------
# Manuals (plain text extracted from the PDFs, one form feed per page)
# ---------------------------------------------------------------------------

#: Running headers, footers and extractor noise. Matched against a whole line.
_MANUAL_NOISE = re.compile(
    r"^(user manual(\s+www\.rovedashcam\.com)?|www\.rovedashcam\.com"
    r"|copyright \(c\).*|\d{1,3}"
    r"|manuals\+|manuals\.plus\s*/?|›?\s*rove\s*/?|☰|image:.*"
    r"|›\s*.*instruction manual|brand:\s*rove|model:\s*.*"
    r"|scan to join.*|\d+(\.\d+)?k|•|•"
    r"|customer service|email us|text us|help@rovedashcam\.com"
    r"|\d-844-[\w-]+|7 days a week.*|response in just.*"
    r"|scan the qr code.*|just scan the qr code.*"
    r"|watch\s+how\s*-?\s*to\s+videos?|visit our website)$",
    re.I,
)

#: Printed furniture that Rove puts on the cover, the inside-cover contact
#: page and the back cover of its *own* manuals: the Facebook community
#: invite, the "contact us before returning the item" page, the HOW-TO-VIDEOS
#: page and the back-cover contact block. None of it is manual content, all of
#: it is speakable-looking prose, and every Rove-printed manual in the corpus
#: (`M1`, `M2`, `M3`, `M7`) carries some of it. Milestone 4.3 added this
#: because `M7`'s first chunk was otherwise cover art, a Facebook invite, a
#: returns notice and the table of contents -- and it came out *speakable*.
#:
#: The table of contents goes with it: a heading, dot leaders and a page
#: number is a pointer, not a fact, and 36 of those lines were most of what
#: that first chunk contained.
#:
#: Matched against a whole line, and against an assembled paragraph, in the
#: same two places `_MANUAL_NOISE` is. Each alternative was checked against
#: every manual on disk before being added, by grepping for it as a whole line
#: (`grep -r -h -i -x -E` over `data/text/manuals/`) and reading the hits. The
#: bare single words here are the ones that needed that check, and they survive
#: it: as whole lines, `CPL` and `PROBLEMS` occur once each and `HOURS` twice,
#: all four on `M7`'s cover or back-cover contact block, and `WATCH` never
#: occurs alone at all -- it is carried only for the `WATCH HOW TO VIDEOS`
#: page, whose own alternative is below. `FREE` and `STOP` are deliberately
#: **not** in this list, because they also occur as "feel free to contact"
#: broken across lines, and as the `Stop` control of the GPS player.
_MANUAL_FURNITURE = re.compile(
    r"^(wanna meet"
    r"|[?!]"
    r"|other rovers \(rove owners\)"
    r"|join the (vibrant )?rove dash cam community.*"
    r"|community on facebook"
    r"|smart & beautiful"
    r"|please read"
    r"|watch|hours|cpl|128gb|ultra-?hd|2160p recording|experiencing|problems"
    r"|filter\(included\)"
    r"|rove pro microsd card \(included\)"
    r"|with 128gb rove pro microsd card & cpl filter"
    r"|rove app for ios & android"
    r"|how\s*-?\s*to\s+videos?"
    r"|(item not as described|damaged or defective|missing items"
    r"|any issues what ?so ?ever)\?.*"
    r"|contact us before returning the item"
    # One table-of-contents line in `M7` ran past its dot leaders and so has
    # none; every other TOC line in the corpus is caught by the rule below.
    r"|pairing your r2-4k dual pro with your smart phone using wifi \d{1,3}"
    r"|we will help you resolve any issues asap\.?"
    r"|customer service:?"
    r"|got questions:?"
    r"|for faster response,? text us"
    r"|camera to get in touch with us\.?"
    r"|www\.rovedashcam\.com/pages/videos"
    r"|license plates\. smallest details\. captured like never before\."
    r"|scan to visit the link"
    r"|scan to (email|text) us:?"
    r"|understanding (your )?rove[^.]{0,30}watch how-?to videos to learn.*"
    r"|.*\.{4,}\s*\d{0,3})$",
    re.I,
)


def _is_manual_noise(line: str) -> bool:
    """Running headers, extractor noise and printed furniture, in one check."""
    return bool(_MANUAL_NOISE.match(line) or _MANUAL_FURNITURE.match(line))


#: Non-manual text that survives *inside* a line rather than on one of its own,
#: so the whole-line `_MANUAL_NOISE` rule never sees it.
#:
#: M6 is the R3 manual as published on the Rove storefront, and the PDF was
#: printed from that page: the extraction therefore opens with the shop's age
#: gate and shipping banner, carries the firmware/downloads page's lead-in
#: sentence, and has the store's community/contact furniture spliced into the
#: middle of the manual text. None of it is manual content and all of it is
#: speakable-looking prose, so it is removed here rather than left for
#: retrieval to rank down. The surrounding manual text -- including the
#: magnetic-mount steps on page 3 -- is untouched.
_MANUAL_INLINE_NOISE = (
    # Storefront age gate.
    re.compile(
        r"Are you at least 18 years old\?.*?Come back when you'?re older\.\s*",
        re.I | re.S,
    ),
    # Storefront shipping banner.
    re.compile(r"FREE \d+ DAY SHIPPING ON ALL DASH CAMS\s*", re.I),
    # Lead-in of the firmware/downloads page the R3 PDF was printed from.
    re.compile(
        r"Below,?\s*you'?ll find all the latest firmware.*?for your Dash Cam\.\s*",
        re.I | re.S,
    ),
    # Store navigation and contact furniture, in the order it appears.
    re.compile(r"Join our ROVE Dash Cam Community[^.]*\.\s*", re.I),
    re.compile(r"Limited Time Launch Offer\.{0,3}\s*", re.I),
    re.compile(r"EMAIL US\s+help@rovedashcam\.com\s*", re.I),
    re.compile(r"For faster response,?\s*text us\s*TEXT US[^.]*\.\s*", re.I),
    re.compile(r"Scan the QR Code to Email or Text Us\.\s*", re.I),
    re.compile(
        r"WATCH HOW TO VIDEOS\s*Visit our website\s*"
        r"www\.rovedashcam\.com/pages/videos\s*to learn[^.]*\.\s*",
        re.I,
    ),
    # "Page 17 USER MANUAL" running header, folded into the body text.
    re.compile(r"\s*\bPage \d{1,3}\s+USER MANUAL\b\s*", re.I),
)


def _is_seo_keyword_run(text: str) -> bool:
    """The storefront's SEO keyword list, printed as a paragraph.

    The R3 PDF ends with "Rove dash cam update. Rove r2-4k dash cam setup.
    ..." -- search keywords, not sentences. Recognised structurally (three or
    more short fragments, every one of them naming both the brand and the
    product) rather than by listing the keywords, and kept narrow enough that
    no paragraph of manual prose can match it.
    """
    fragments = [f.strip() for f in text.split(".") if f.strip()]
    if len(fragments) < 3:
        return False
    return all(
        len(fragment) <= 60
        and "rove" in fragment.casefold()
        and "dash cam" in fragment.casefold()
        for fragment in fragments
    )

#: A line that is a heading: short, no terminal full stop, and either written
#: in capitals (the manuals' own section style) or one of the explicit
#: sub-heading markers.
_MANUAL_MARKER_RE = re.compile(r"^(IMPORTANT|CAUTION|NOTE|WARNING|TIP|NOTICE)\b[:.]?",
                               re.I)
_NUMBERED_SECTION_RE = re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Z \-/&']{3,})$")

#: Opening words of the troubleshooting-table rows, which are written in
#: sentence case and so are invisible to the capitals rule. Used only as a
#: *split point*: a miss merges two rows, it never splits one.
_TROUBLE_OPENERS = (
    "camera",
    "my",
    "video",
    "audio",
    "error",
    "memory",
    "microsd",
    "micro sd",
    "dash",
    "gps",
    "wifi",
    "wi-fi",
    "parking",
    "battery",
    "app",
    "date",
    "time",
    "screen",
    "recording",
    "loop",
    "firmware",
    "charger",
    "mount",
    "no ",
    "cannot",
    "can't",
    "unable",
    "why",
    "how",
    "rear",
    "front",
    "the camera",
    "there is",
)


def _is_caps_heading(line: str) -> bool:
    if len(line) > 70:
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 3:
        return False
    upper = sum(1 for c in letters if c.isupper())
    if upper / len(letters) < 0.85:
        return False
    return not line.endswith((".", ",", ";"))


def _is_trouble_row(line: str, in_troubleshooting: bool) -> bool:
    if not in_troubleshooting or len(line) > 80:
        return False
    low = line.casefold()
    if not low.startswith(_TROUBLE_OPENERS):
        return False
    if _NUMBERED_RE.match(line):
        return False
    return line[:1].isupper() or low.startswith(("microsd", "micro sd"))


def parse_manual(path: Path) -> list[Block]:
    """Blocks from an extracted manual, with page numbers attached.

    Pages come from the form feeds the PDF text extraction left behind: the
    counts match `data/README.md` exactly (72 / 79 / 80 / 14 / 12 / 3 / 91).
    Page
    numbers matter because `docs/05` cites by page and `docs/06` §4.2 asks the
    audit trail to do the same.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    pages = text.split("\f")
    blocks: list[Block] = []
    in_troubleshooting = False
    para: list[str] = []
    para_page = 1

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        joined = " ".join(" ".join(para).split())
        para = []
        for pattern in _MANUAL_INLINE_NOISE:
            joined = pattern.sub(" ", joined)
        joined = " ".join(joined.split())
        if not joined or _is_manual_noise(joined) or _is_seo_keyword_run(joined):
            return
        kind = STEP if (_NUMBERED_RE.match(joined) or _STEP_WORD_RE.match(joined)) else PARA
        blocks.append(Block(kind, joined, page=para_page))

    for page_index, page in enumerate(pages, start=1):
        for raw_line in page.split("\n"):
            line = " ".join(raw_line.split())
            if not line:
                flush_para()
                continue
            if _is_manual_noise(line):
                flush_para()
                continue

            numbered_section = _NUMBERED_SECTION_RE.match(line)
            if numbered_section:
                flush_para()
                heading = numbered_section.group(2).strip()
                in_troubleshooting = "TROUBLESHOOT" in heading.upper()
                blocks.append(Block(HEADING, heading, level=1, page=page_index))
                continue
            if _is_caps_heading(line):
                flush_para()
                in_troubleshooting = "TROUBLESHOOT" in line.upper()
                blocks.append(Block(HEADING, line, level=1, page=page_index))
                continue
            if _MANUAL_MARKER_RE.match(line) and len(line) <= 30:
                flush_para()
                blocks.append(Block(HEADING, line.rstrip(":"), level=3, page=page_index))
                continue
            if _is_trouble_row(line, in_troubleshooting):
                flush_para()
                blocks.append(Block(HEADING, line, level=2, page=page_index))
                continue
            if _NUMBERED_RE.match(line) or _STEP_WORD_RE.match(line):
                flush_para()
                para_page = page_index
                para.append(line)
                continue
            if not para:
                para_page = page_index
            para.append(line)
        flush_para()
    return blocks


# ---------------------------------------------------------------------------
# Units and atomic pieces
# ---------------------------------------------------------------------------


@dataclass
class Piece:
    """The smallest thing the packer may move. An atomic piece is never split."""

    blocks: list[Block]
    atomic: bool
    starts_section: bool
    level: int
    section_path: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    @property
    def tokens(self) -> int:
        return md.estimate_tokens(self.text)

    @property
    def pages(self) -> list[int]:
        return [b.page for b in self.blocks if b.page]


_LEAD_IN_RE = re.compile(r":\s*$")
_NOTE_RE = re.compile(r"^(note|important|caution|warning|tip)\b", re.I)


def _group_atomic(blocks: list[Block]) -> list[list[Block]]:
    """Group a unit's content blocks, holding procedures together.

    A run is: an optional lead-in paragraph ending in a colon, two or more
    numbered steps (or one `ol`), and any immediately following NOTE /
    IMPORTANT / CAUTION paragraph. The trailing note is included deliberately
    -- "do not disconnect the power" is a note attached to the firmware
    procedure, and `docs/06` §4.2 exists because separating the two is how an
    agent bricks a camera.
    """
    groups: list[list[Block]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind in (STEP, BULLET):
            run_kind = block.kind
            run = [block]
            index += 1
            while index < len(blocks) and blocks[index].kind == run_kind:
                run.append(blocks[index])
                index += 1
            while index < len(blocks) and _NOTE_RE.match(blocks[index].text):
                run.append(blocks[index])
                index += 1
            if (
                groups
                and len(groups[-1]) == 1
                and groups[-1][0].kind == PARA
                and _LEAD_IN_RE.search(groups[-1][0].text)
            ):
                run = groups.pop() + run
            groups.append(run)
            continue
        groups.append([block])
        index += 1
    return groups


def _is_atomic(group: list[Block]) -> bool:
    return sum(1 for b in group if b.kind == STEP) >= 2 or (
        len(group) > 1 and any(b.kind in (STEP, BULLET) for b in group)
    )


def build_pieces(blocks: list[Block]) -> list[Piece]:
    """Blocks -> pieces, carrying the heading path each piece sits under."""
    pieces: list[Piece] = []
    path: list[str] = []
    pending: list[Block] = []
    current_level = 1
    starts_section = True

    def flush_pending() -> None:
        nonlocal pending, starts_section
        if not pending:
            return
        for position, group in enumerate(_group_atomic(pending)):
            pieces.append(
                Piece(
                    blocks=group,
                    atomic=_is_atomic(group),
                    starts_section=starts_section and position == 0,
                    level=current_level,
                    section_path=tuple(path),
                )
            )
        pending = []
        starts_section = False

    for block in blocks:
        if block.kind == HEADING:
            flush_pending()
            level = max(1, min(block.level or 1, 6))
            del path[level - 1 :]
            while len(path) < level - 1:
                path.append("")
            path.append(block.text)
            current_level = level
            starts_section = True
            # The heading travels with the first piece of its section.
            pending.append(block)
            continue
        pending.append(block)
    flush_pending()
    return [p for p in pieces if p.text.strip()]


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _last_sentence(text: str) -> str:
    parts = [p.strip() for p in _SENTENCE_RE.split(text.replace("\n", " ")) if p.strip()]
    if not parts:
        return ""
    tail = parts[-1]
    return tail if len(tail) <= 400 else ""


def _split_oversized(piece: Piece) -> list[Piece]:
    """Split a non-atomic piece that is on its own larger than the budget.

    Atomic pieces are returned whole: `docs/06` §4.2 -- "if a procedure
    exceeds the chunk budget, the chunk exceeds the budget".
    """
    if piece.atomic or piece.tokens <= TARGET_MAX:
        return [piece]
    out: list[Piece] = []
    for block in piece.blocks:
        if md.estimate_tokens(block.text) <= TARGET_MAX:
            out.append(
                Piece([block], False, piece.starts_section and not out,
                      piece.level, piece.section_path)
            )
            continue
        sentences = _SENTENCE_RE.split(block.text)
        buf: list[str] = []
        for sentence in sentences:
            buf.append(sentence)
            if md.estimate_tokens(" ".join(buf)) >= TARGET_MAX:
                out.append(
                    Piece(
                        [Block(block.kind, " ".join(buf), page=block.page)],
                        False,
                        piece.starts_section and not out,
                        piece.level,
                        piece.section_path,
                    )
                )
                buf = []
        if buf:
            out.append(
                Piece(
                    [Block(block.kind, " ".join(buf), page=block.page)],
                    False,
                    piece.starts_section and not out,
                    piece.level,
                    piece.section_path,
                )
            )
    return out or [piece]


@dataclass
class PackedChunk:
    pieces: list[Piece] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(p.tokens for p in self.pieces)

    @property
    def section_path(self) -> list[str]:
        for piece in self.pieces:
            if piece.section_path:
                return [s for s in piece.section_path if s]
        return []

    @property
    def pages(self) -> list[int]:
        pages: list[int] = []
        for piece in self.pieces:
            pages.extend(piece.pages)
        return pages


def pack(pieces: list[Piece]) -> list[PackedChunk]:
    """Fill chunks to the budget without ever splitting an atomic piece."""
    chunks: list[PackedChunk] = []
    current = PackedChunk()
    for piece in pieces:
        for part in _split_oversized(piece):
            closes = current.pieces and (
                current.tokens + part.tokens > TARGET_MAX
                or (
                    part.starts_section
                    and part.level <= 1
                    and current.tokens >= TARGET_MIN
                )
            )
            if closes:
                chunks.append(current)
                current = PackedChunk()
            current.pieces.append(part)
    if current.pieces:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return (slug[:40] or "SECTION").rstrip("_")


#: Last-resort `section_path` entry, for a document whose text carries no
#: heading at all and whose registry title is somehow empty too.
UNSECTIONED = "UNSECTIONED"


def _section_path_for(chunk: PackedChunk, source: md.Source) -> list[str]:
    """The chunk's heading path, which is never empty.

    `section_path` is a required field (`docs/06` §4.3), and a required field
    that is present but empty is a breach of the same rule as a missing one.
    Most documents supply a path from their own headings, but M6 -- the R3
    manual printed from the storefront -- extracts as one unbroken run of
    prose with no heading on page 3, so the heading path is genuinely empty
    there. Rather than emit an empty required field, fall back to the
    document's registry title: it is true, it is what a reader needs in order
    to place the chunk, and `context_header` already restates it.
    """
    path = [section for section in chunk.section_path if section]
    if path:
        return path
    return [source.title.strip() or UNSECTIONED]


def _page_range(pages: list[int]) -> str | None:
    if not pages:
        return None
    low, high = min(pages), max(pages)
    return f"p{low}" if low == high else f"p{low}-{high}"


def chunk_source(source: md.Source, root: Path | None = None) -> list[md.Chunk]:
    """Chunk one registry entry into finished, fully-tagged chunks."""
    root = root or REPO_ROOT
    path = root / source.path
    blocks = (
        parse_manual(path)
        if source.kind == "manual_text"
        else parse_html(path)
    )
    packed = pack(build_pieces(blocks))

    out: list[md.Chunk] = []
    used_ids: set[str] = set()
    previous_top: str | None = None
    previous_text = ""

    for ordinal, chunk in enumerate(packed, start=1):
        # Redact once, over the assembled body: the proximity window of
        # `docs/06` §4.6 has to see the text the way a reader will, not the
        # way the packer happened to cut it.
        body, redactions = md.redact_firmware_versions(
            "\n\n".join(p.text for p in chunk.pieces)
        )

        section_path = _section_path_for(chunk, source)
        top = section_path[0]
        overlap = _last_sentence(previous_text) if top == previous_top else ""
        text = f"{overlap}\n\n{body}".strip() if overlap else body

        page_range = _page_range(chunk.pages)
        base = f"{source.doc_code}#{_slug(section_path[-1])}"
        chunk_id = f"{base}#{page_range or f'c{ordinal}'}"
        if chunk_id in used_ids:
            chunk_id = f"{chunk_id}-{ordinal}"
        used_ids.add(chunk_id)

        record = md.build_metadata(
            source=source,
            text=text,
            section_path=section_path,
            page_range=page_range,
            chunk_id=chunk_id,
            context_header="",
            overlap_sentence=overlap,
        )
        record.redactions = redactions
        models = ", ".join(record.model_applicability)
        record.context_header = (
            f"{source.doc_code} · {source.title}"
            + (f" · {' > '.join(section_path)}" if section_path else "")
            + (f" · {page_range}" if page_range else "")
            + f" · models: {models}"
            + (" (cross-model)" if record.cross_model else "")
        )
        out.append(record)
        previous_top = top
        previous_text = body
    return out


def chunk_corpus(root: Path | None = None) -> list[md.Chunk]:
    """Every Tier-1 document in the registry, in registry order."""
    chunks: list[md.Chunk] = []
    for source in md.SOURCES.values():
        chunks.extend(chunk_source(source, root=root))
    return chunks
