"""Debug HARExtractor and directly fix pool import."""
from engine.integrations.har_extractor import HARExtractor, COOKIE_NAMES
from engine.integrations.google_account_pool import get_account_pool
import json

HAR = "data/har_files/notebooklm.google.com-complete-new.har"

h = HARExtractor(HAR)
print("entries:", len(h._entries))

# Check first entry
entry0 = h._entries[0]
req0 = entry0.get("request", {})
url0 = req0.get("url", "")
print("url0:", url0[:80])
print("google.com in url0:", "google.com" in url0)
print("cookies in req0:", len(req0.get("cookies", [])))

# Run extract_cookies
result = h.extract_cookies("google.com")
print("extract_cookies result:", len(result), result)

# ── Direct pool import using our working raw extractor ──
TARGET = {
    "SAPISID","APISID","SID","SSID","HSID","NID","GAPS","SIDCC","AEC",
    "__Secure-1PSID","__Secure-3PSID","__Secure-1PAPISID","__Secure-3PAPISID",
    "__Secure-1PSIDCC","__Secure-3PSIDCC",
}

with open(HAR, encoding="utf-8", errors="replace") as f:
    data = json.load(f)

entries = data.get("log", {}).get("entries", [])
found: dict = {}
authuser = "0"

for entry in entries:
    req = entry.get("request", {})
    url = req.get("url", "")
    if "google.com" not in url:
        continue
    for c in req.get("cookies", []):
        n, v = c.get("name",""), c.get("value","")
        if n in TARGET and n not in found:
            found[n] = v
    for hdr in req.get("headers", []):
        if hdr.get("name","").lower() == "cookie":
            for part in hdr.get("value","").split(";"):
                part = part.strip()
                if "=" in part:
                    k, _, v = part.partition("=")
                    if k.strip() in TARGET and k.strip() not in found:
                        found[k.strip()] = v.strip()
        if hdr.get("name","").lower() == "x-goog-authuser":
            authuser = hdr.get("value","0")
    # Also check response headers for at_token
    for hdr in entry.get("response",{}).get("headers",[]):
        if hdr.get("name","").lower() == "set-cookie":
            val = hdr.get("value","")
            k, _, rest = val.partition("=")
            v = rest.split(";")[0]
            if k.strip() in TARGET and k.strip() not in found:
                found[k.strip()] = v.strip()

print(f"\nRaw extraction: {len(found)} cookies")
for k,v in sorted(found.items()):
    print(f"  {k} = {v[:60]}{'...' if len(v)>60 else ''}")

# Directly write into pool
pool = get_account_pool()
pool_data = pool._accounts.get("knack112358", {})

# Patch the account dict directly
from engine.integrations.google_account_pool import GoogleAccount
import dataclasses

# Update via internal structure
if hasattr(pool_data, 'cookies'):
    # It's a dataclass/object
    pool._accounts["knack112358"] = GoogleAccount(
        name="knack112358",
        cookies=found,
        authuser=authuser,
        services=["notebooklm","google","colab"],
    )
else:
    pool._accounts["knack112358"] = {
        "name": "knack112358",
        "cookies": found,
        "authuser": authuser,
        "services": ["notebooklm","google","colab"],
    }

pool.save()
print(f"\nPool saved. Account knack112358: {len(found)} cookies")

# Also import as nlm_newest
pool._accounts["notebooklm_newest"] = pool._accounts["knack112358"]
pool.save()
print("Also saved as notebooklm_newest")
