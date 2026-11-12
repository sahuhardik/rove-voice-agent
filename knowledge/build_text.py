"""Step 1 of the knowledge pipeline: turn the raw sources into clean text.

    python -m knowledge.build_text

Writes v2/knowledge/clean/<MODEL>.txt (every source for that model, joined)
and v2/knowledge/clean/general.txt (Help Center + official pages).

What "clean" means here:
* Ligature damage from the PDF extraction is repaired ("Se�ngs" -> "Settings").
  The replacement character stood for a ligature (ti, tt, tti, fi, ft ...); we pick
  the candidate that turns the token into a word seen elsewhere in the corpus.
* Scraper boilerplate (ManualsLib / manuals.plus headers, store banners) is dropped.
* HTML pages are reduced to their article text, with the right text encoding.
"""

from __future__ import annotations

import glob
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "clean"
REPLACEMENT = "�"
LIGATURES = ["ti", "tt", "tti", "fi", "ff", "ffi", "fl", "ft", "th"]

#: Line-level boilerplate. `.` never crosses a newline here, so each pattern
#: removes one line at most.
BOILERPLATE_LINES = [
    r"^Manualslib\.com.*$",
    r"^Manuals / Brands /.*$",
    r"^Saved from manuals\.plus.*$",
    r"^Open the live page for links.*$",
    r"^Quick Links .*$",
    r"^Related Manuals for .*$",
    r"^Download this manual.*$",
]
#: The R3 page opens with a store age-gate and shipping banner before the content.
STORE_BANNER = r"Are you at least 18 years old\?.*?(?=Below, you)"


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def decode_cfemail(hexstr: str) -> str:
    """Cloudflare's email obfuscation: first byte is an XOR key for the rest."""
    key = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def reveal_emails(soup) -> int:
    """Replace Cloudflare's "[email protected]" placeholders with the real address.

    Without this the agent never sees the support address and, as the audit found,
    makes one up. Returns how many placeholders were decoded.
    """
    n = 0
    for tag in soup.find_all(attrs={"data-cfemail": True}):
        tag.replace_with(decode_cfemail(tag["data-cfemail"]))
        n += 1
    for a in soup.find_all("a", href=re.compile(r"/cdn-cgi/l/email-protection#")):
        a.replace_with(decode_cfemail(a["href"].split("#", 1)[1]))
        n += 1
    return n


def html_text(path: Path) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read_text(path), "html.parser")
    reveal_emails(soup)
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else path.stem
    # The article is the block holding the most paragraph/list text.
    best, best_len = soup.body or soup, 0
    for cand in soup.find_all(["article", "main", "section", "div"]):
        n = sum(len(p.get_text(" ", strip=True)) for p in cand.find_all(["p", "li"], recursive=True))
        own = len(cand.get_text(" ", strip=True))
        if n > best_len and own < n * 2.5:  # mostly article text, not the whole page
            best, best_len = cand, n
    lines: list[str] = []
    for el in best.find_all(["h1", "h2", "h3", "h4", "p", "li", "td"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text or (lines and lines[-1].endswith(text)):
            continue
        if el.name.startswith("h"):
            lines.append(f"\n## {text}")
        elif el.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return f"# {title}\n" + "\n".join(lines)


def build_vocab(texts: list[str]) -> Counter:
    vocab: Counter = Counter()
    for t in texts:
        for w in re.findall(r"[A-Za-z]+", t):
            if REPLACEMENT not in w:
                vocab[w.lower()] += 1
    return vocab


def repair_ligatures(text: str, vocab: Counter) -> tuple[str, int, int]:
    fixed = unfixed = 0

    def fix(m: re.Match) -> str:
        nonlocal fixed, unfixed
        word = m.group(0)
        best, best_score = None, 0
        for lig in LIGATURES:
            cand = word.replace(REPLACEMENT, lig).replace("ﬁ", "fi").replace("ﬂ", "fl")
            score = vocab.get(cand.lower(), 0)
            if score > best_score:
                best, best_score = cand, score
        if best is None:
            # Fall back to the commonest ligature; "ti" covers most of this corpus.
            unfixed += 1
            return word.replace(REPLACEMENT, "ti")
        fixed += 1
        if word[:1].isupper() and best[1:] != best[1:].lower() and not word.isupper():
            best = best[0] + best[1:].lower()  # "Connec�Ng" -> "Connecting"
        return best

    out = re.sub(r"[A-Za-zﬁﬂ]*�[A-Za-zﬁﬂ�]*", fix, text)
    out = out.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return out, fixed, unfixed


def strip_boilerplate(text: str) -> str:
    for pat in BOILERPLATE_LINES:
        text = re.sub(pat, "", text, flags=re.M)
    text = re.sub(STORE_BANNER, "", text, count=1, flags=re.S)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def load_source(rel: str) -> str:
    path = ROOT / rel
    if path.suffix.lower() == ".pdf":
        return pdf_text(path)
    if path.suffix.lower() in (".html", ".htm"):
        return html_text(path)
    return read_text(path)


def main() -> dict:
    registry = json.loads((HERE / "registry.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    docs: dict[str, list[tuple[str, str]]] = {}
    for model, info in registry["models"].items():
        docs[model] = [(rel, load_source(rel)) for rel in info["sources"]]
    general = []
    for pattern in registry["general_sources"]:
        for p in sorted(glob.glob(str(ROOT / pattern))):
            rel = Path(p).relative_to(ROOT).as_posix()
            general.append((rel, load_source(rel)))
    docs["general"] = general

    vocab = build_vocab([t for items in docs.values() for _, t in items])
    report = {}
    for name, items in docs.items():
        parts, fixed, unfixed = [], 0, 0
        for rel, text in items:
            text, f, u = repair_ligatures(text, vocab)
            fixed, unfixed = fixed + f, unfixed + u
            parts.append(f"===== SOURCE: {rel} =====\n{strip_boilerplate(text)}")
        body = "\n\n".join(parts)
        (OUT / f"{name}.txt").write_text(body, encoding="utf-8")
        report[name] = {"sources": len(items), "chars": len(body), "ligatures_fixed": fixed, "ligatures_guessed": unfixed}
    (OUT / "_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    for k, v in main().items():
        print(f"{k:16} {v}")
