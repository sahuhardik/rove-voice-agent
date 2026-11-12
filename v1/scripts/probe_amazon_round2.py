"""Second diligence round on Amazon-review aggregators. No amazon.com requests."""
import gzip
import io
import json
import re
import socket
import urllib.error
import urllib.request

socket.setdefaulttimeout(20)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


def get(url, accept="text/html,application/json,*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                               "Accept-Encoding": "gzip, identity"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return r.status, raw.decode("utf-8", "replace")


def show(label, url, **kw):
    try:
        status, body = get(url, **kw)
        print(f"OK   {status}  {label}")
        return body
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}  {label}  ({exc.reason})")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL      {label}  {type(exc).__name__}: {exc}")
    return None


print("--- 1. does desertcart search actually surface Rove products? ---")
body = show("desertcart search", "https://www.desertcart.com/search?q=rove+dash+cam")
if body:
    ids = sorted(set(re.findall(r"/products/([A-Z0-9]{10})", body)))
    print("   product ids found:", ids[:20], f"({len(ids)} total)")
    print("   mentions 'rove':", body.lower().count("rove"))
    print("   mentions 'review':", body.lower().count("review"))
print()

print("--- 2. desertcart review-bearing endpoints ---")
for u in ["https://www.desertcart.com/api/products/B0F9SX3JB9",
          "https://api.desertcart.com/v1/products/B0F9SX3JB9",
          "https://www.desertcart.com/products/B0F9SX3JB9/reviews"]:
    show(u, u, accept="application/json")
print()

print("--- 3. other key-free aggregators ---")
for label, u in [
    ("amazoncheck/asinfo", "https://www.amazon-asin.com/asincheck/?product=B0F9SX3JB9"),
    ("Octoparse-free n/a", "https://openlibrary.org/"),  # control: is general egress fine?
    ("Walmart-style mirror ubuy", "https://www.ubuy.co.in/product/B0F9SX3JB9"),
    ("Trustpilot rovedashcam", "https://www.trustpilot.com/review/rovedashcam.com"),
    ("Judge.me / Shopify reviews on rovedashcam.com",
     "https://www.rovedashcam.com/products.json?limit=5"),
]:
    b = show(label, u)
    if b and "trustpilot" in u:
        m = re.findall(r'"reviewCount"\s*:\s*(\d+)', b)
        print("   reviewCount hits:", m[:5])
    if b and "products.json" in u:
        try:
            d = json.loads(b)
            print("   shopify products:", [p.get("title") for p in d.get("products", [])][:5])
        except Exception as exc:  # noqa: BLE001
            print("   not json:", exc)
print()

print("--- 4. PA-API credential availability ---")
import os
has = [k for k in ("AWS_ACCESS_KEY_ID", "AMAZON_PAAPI_KEY", "PAAPI_ACCESS_KEY",
                   "RAINFOREST_API_KEY", "KEEPA_KEY", "APIFY_TOKEN",
                   "SCRAPERAPI_KEY") if os.environ.get(k)]
print("   relevant API keys present in env:", has or "none")
