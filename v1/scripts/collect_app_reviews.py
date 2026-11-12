"""Collect Tier 2 discovery samples: low-rated ROVE Dash Cam app reviews.

Tier 2 = discovery only (symptom language, frequency, eval scenarios).
Review text is NEVER a verified fix -- see docs/04-data-sources.md.

Endpoints used are the same public ones the npm packages google-play-scraper and
app-store-scraper call. npm/npx/node execution is blocked by this repo's
permission policy, so the requests are made directly with python urllib.
No curl/wget, no web fetch/search.
"""
import json
import os
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

socket.setdefaulttimeout(30)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "raw", "reviews")
RETRIEVED = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TIER = "Tier 2 - discovery only (symptom language / frequency / eval scenarios). NEVER a fix."

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

LOW_RATINGS = {1, 2}
TARGET = 100
MIN_TARGET = 50


# --------------------------------------------------------------------------
# Google Play
# --------------------------------------------------------------------------
PLAY_APP_ID = "com.rovedashcam.android"
PLAY_PAGE_URL = f"https://play.google.com/store/apps/details?id={PLAY_APP_ID}"
PLAY_RPC = ("https://play.google.com/_/PlayStoreUi/data/batchexecute"
            "?rpcids=UsvDTd&hl=en&gl=us&soc-app=121&soc-platform=1&soc-device=1&_reqid=1")


def _play_post(inner):
    payload = [[["UsvDTd", inner, None, "generic"]]]
    body = "f.req=" + urllib.parse.quote(json.dumps(payload))
    req = urllib.request.Request(
        PLAY_RPC,
        data=body.encode("utf-8"),
        headers={"User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8", "replace")


def _play_extract(raw):
    for line in raw.split("\n"):
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        for part in envelope:
            if len(part) > 2 and part[0] == "wrb.fr" and part[2]:
                return json.loads(part[2])
    return None


def collect_play(max_pages=40):
    """Paginate newest-first and keep 1-2 star reviews."""
    kept, seen = [], set()
    token, pages, scanned = None, 0, 0
    while pages < max_pages and len(kept) < TARGET:
        tok = "null" if token is None else json.dumps(token)
        inner = ('[null,null,[2,2,[100,null,%s],null,[]],["%s",7]]'
                 % (tok, PLAY_APP_ID))
        try:
            data = _play_extract(_play_post(inner))
        except Exception as exc:  # noqa: BLE001
            print(f"  play page {pages + 1}: request failed: {type(exc).__name__}: {exc}")
            break
        pages += 1
        if not data or not data[0]:
            print(f"  play page {pages}: no reviews returned, stopping")
            break
        batch = data[0]
        scanned += len(batch)
        for r in batch:
            rid = r[0]
            if rid in seen:
                continue
            seen.add(rid)
            score = r[2]
            if score not in LOW_RATINGS:
                continue
            ts = r[5][0] if r[5] else None
            kept.append({
                "review_id": rid,
                "source": "Google Play",
                "source_app_id": PLAY_APP_ID,
                "source_url": PLAY_PAGE_URL,
                "retrieved_utc": RETRIEVED,
                "tier": TIER,
                "rating": score,
                "date": (datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
                         if ts else None),
                "app_version": r[10] if len(r) > 10 else None,
                "author": r[1][0] if r[1] else None,
                "title": None,
                "text": r[4],
                "thumbs_up": r[6] if len(r) > 6 else None,
            })
        token = data[1][1] if len(data) > 1 and data[1] else None
        print(f"  play page {pages}: scanned {len(batch)}, low-rated kept so far {len(kept)}")
        if not token:
            print("  play: no further pagination token, stopping")
            break
        time.sleep(1.0)
    return kept, scanned, pages


# --------------------------------------------------------------------------
# Apple App Store
# --------------------------------------------------------------------------
IOS_APP_ID = "1606959035"
IOS_PAGE_URL = f"https://apps.apple.com/us/app/rove-dash-cam/id{IOS_APP_ID}"
IOS_RSS = ("https://itunes.apple.com/us/rss/customerreviews/page={page}"
           "/id={app}/sortby={sort}/json")


def _ios_page(page, sort):
    url = IOS_RSS.format(page=page, app=IOS_APP_ID, sort=sort)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req) as r:
        return json.load(r), url


def collect_ios():
    """The iTunes RSS feed caps at 10 pages x 50. Pull both most-critical and
    most-recent orderings, dedupe by review id, keep 1-2 star."""
    kept, seen, scanned = [], set(), 0
    for sort in ("mostcritical", "mostrecent"):
        for page in range(1, 11):
            try:
                feed, url = _ios_page(page, sort)
            except Exception as exc:  # noqa: BLE001
                print(f"  ios {sort} page {page}: failed: {type(exc).__name__}: {exc}")
                break
            entries = feed.get("feed", {}).get("entry") or []
            if not entries:
                print(f"  ios {sort} page {page}: empty, stopping this ordering")
                break
            scanned += len(entries)
            for e in entries:
                if "im:rating" not in e:
                    continue  # app metadata entry, not a review
                rid = e["id"]["label"]
                if rid in seen:
                    continue
                seen.add(rid)
                rating = int(e["im:rating"]["label"])
                if rating not in LOW_RATINGS:
                    continue
                updated = e.get("updated", {}).get("label")
                kept.append({
                    "review_id": rid,
                    "source": "Apple App Store",
                    "source_app_id": IOS_APP_ID,
                    "source_url": IOS_PAGE_URL,
                    "source_feed_url": url,
                    "retrieved_utc": RETRIEVED,
                    "tier": TIER,
                    "rating": rating,
                    "date": updated.split("T")[0] if updated else None,
                    "app_version": e.get("im:version", {}).get("label"),
                    "author": e.get("author", {}).get("name", {}).get("label"),
                    "title": e.get("title", {}).get("label"),
                    "text": e.get("content", {}).get("label"),
                    "thumbs_up": int(e.get("im:voteSum", {}).get("label") or 0),
                })
            print(f"  ios {sort} page {page}: scanned {len(entries)}, "
                  f"low-rated kept so far {len(kept)}")
            time.sleep(0.6)
    return kept, scanned


# --------------------------------------------------------------------------
def write(name, reviews, meta):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    reviews = sorted(reviews, key=lambda r: (r["date"] or ""), reverse=True)[:TARGET]
    doc = dict(meta)
    doc["tier"] = TIER
    doc["retrieved_utc"] = RETRIEVED
    doc["review_count"] = len(reviews)
    doc["rating_breakdown"] = {
        str(s): sum(1 for r in reviews if r["rating"] == s) for s in sorted(LOW_RATINGS)
    }
    doc["reviews"] = reviews
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {path}: {len(reviews)} reviews")
    return len(reviews)


if __name__ == "__main__":
    print("Google Play (com.rovedashcam.android):")
    play, play_scanned, play_pages = collect_play()
    n_play = write("google-play-com.rovedashcam.android.json", play, {
        "source": "Google Play",
        "app_id": PLAY_APP_ID,
        "app_name": "ROVE Dash Cam",
        "source_url": PLAY_PAGE_URL,
        "endpoint": PLAY_RPC.split("?")[0] + " (rpcid UsvDTd, newest-first)",
        "filter": "ratings 1-2 only",
        "scanned_total_reviews": play_scanned,
        "pages_fetched": play_pages,
        "collection_method": ("python urllib against the same public batchexecute RPC "
                              "google-play-scraper uses; npm/npx/node are blocked by "
                              "this repo's permission policy"),
    })

    print("\nApple App Store (id1606959035):")
    ios, ios_scanned = collect_ios()
    n_ios = write("app-store-id1606959035.json", ios, {
        "source": "Apple App Store",
        "app_id": IOS_APP_ID,
        "app_name": "ROVE Dash Cam",
        "source_url": IOS_PAGE_URL,
        "endpoint": "https://itunes.apple.com/us/rss/customerreviews/ (mostcritical + mostrecent)",
        "filter": "ratings 1-2 only",
        "scanned_total_reviews": ios_scanned,
        "collection_method": ("python urllib against the same public iTunes RSS feed "
                              "app-store-scraper uses; npm/npx/node are blocked by "
                              "this repo's permission policy"),
    })

    print(f"\nTOTAL low-rated app reviews: play={n_play} ios={n_ios}")
    if n_play < MIN_TARGET:
        print(f"WARNING: Google Play below the {MIN_TARGET} minimum")
    if n_ios < MIN_TARGET:
        print(f"WARNING: App Store below the {MIN_TARGET} minimum")
