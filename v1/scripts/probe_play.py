"""Probe the Google Play batchexecute reviews RPC (same endpoint google-play-scraper uses)."""
import json
import socket
import urllib.parse
import urllib.request

socket.setdefaulttimeout(30)

APP_ID = "com.rovedashcam.android"
URL = ("https://play.google.com/_/PlayStoreUi/data/batchexecute"
       "?rpcids=UsvDTd&hl=en&gl=us&soc-app=121&soc-platform=1&soc-device=1&_reqid=1")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


def post(inner):
    payload = [[["UsvDTd", inner, None, "generic"]]]
    body = "f.req=" + urllib.parse.quote(json.dumps(payload))
    req = urllib.request.Request(
        URL,
        data=body.encode("utf-8"),
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8", "replace")


def extract(raw):
    """batchexecute returns )]}' then length-prefixed chunks of JSON."""
    lines = raw.split("\n")
    for line in lines:
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


VARIANTS = {
    "sort2_no_score": '[null,null,[2,2,[50,null,null],null,[]],["%s",7]]' % APP_ID,
    "sort2_score1": '[null,null,[2,2,[50,null,null],null,[1]],["%s",7]]' % APP_ID,
    "sort1_no_score": '[null,null,[2,1,[50,null,null],null,[]],["%s",7]]' % APP_ID,
}

for name, inner in VARIANTS.items():
    try:
        raw = post(inner)
    except Exception as exc:  # noqa: BLE001
        print(name, "-> HTTP FAIL", type(exc).__name__, exc)
        continue
    print(name, "-> raw bytes", len(raw))
    data = extract(raw)
    if data is None:
        print("   could not extract payload; head:", raw[:200].replace("\n", "\\n"))
        continue
    reviews = data[0] if data and data[0] else []
    print("   reviews:", len(reviews), "| token:",
          (data[1][1] if len(data) > 1 and data[1] else None))
    if reviews:
        r = reviews[0]
        print("   sample id:", r[0])
        print("   author:", r[1][0] if r[1] else None)
        print("   score:", r[2])
        print("   text:", repr(r[4])[:160])
        print("   ts:", r[5])
        print("   version:", r[10] if len(r) > 10 else None)
    print()
