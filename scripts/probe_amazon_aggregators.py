"""Probe Amazon-review aggregators / APIs for reachability from this host.

Hard rule: do NOT request amazon.com directly. Aggregators and APIs only.
"""
import socket
import urllib.error
import urllib.request

socket.setdefaulttimeout(20)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

TARGETS = [
    # (label, url, what it would give us)
    ("desertcart search R2-4K",
     "https://www.desertcart.com/search?q=rove%20r2-4k%20dash%20cam",
     "Amazon mirror listing -> product ids"),
    ("desertcart product B0F9SX3JB9",
     "https://www.desertcart.com/products/B0F9SX3JB9",
     "Amazon mirror product page + reviews"),
    ("desertcart.in product B0F9SX3JB9",
     "https://www.desertcart.in/products/B0F9SX3JB9",
     "regional mirror"),
    ("Rainforest API (no key)",
     "https://api.rainforestapi.com/request?type=reviews&amazon_domain=amazon.com&asin=B0F9SX3JB9",
     "structured Amazon reviews - needs api_key"),
    ("Amazon PA-API host",
     "https://webservices.amazon.com/paapi5/getitems",
     "official API - needs signed creds"),
    ("ReviewMeta",
     "https://reviewmeta.com/amazon/B0F9SX3JB9",
     "review analysis aggregator"),
    ("Keepa API (no key)",
     "https://api.keepa.com/product?domain=1&asin=B0F9SX3JB9",
     "price/review history - needs key"),
    ("Amazon Scraper via apify store page",
     "https://api.apify.com/v2/acts",
     "scraper platform - needs token"),
]


def probe(label, url, note):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html,application/json,*/*"})
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read(4000).decode("utf-8", "replace")
        print(f"OK   {r.status:3d}  {label}")
        print(f"      {url}")
        print(f"      note: {note}")
        print(f"      head: {body[:220].replace(chr(10), ' ')!r}")
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code:3d}  {label}  -> {exc.reason}")
        print(f"      {url}")
        try:
            print(f"      body: {exc.read(400).decode('utf-8', 'replace')[:260]!r}")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL      {label}  -> {type(exc).__name__}: {exc}")
        print(f"      {url}")
    print()


if __name__ == "__main__":
    for t in TARGETS:
        probe(*t)
