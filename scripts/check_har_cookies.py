"""Quick HAR cookie diagnostic + direct import."""
import json, sys
from pathlib import Path

HAR = "data/har_files/notebooklm.google.com-complete-new.har"
TARGET = {
    "SAPISID","APISID","SID","SSID","HSID","NID","GAPS","SIDCC","AEC",
    "__Secure-1PSID","__Secure-3PSID","__Secure-1PAPISID","__Secure-3PAPISID",
    "__Secure-1PSIDCC","__Secure-3PSIDCC",
}

with open(HAR, encoding="utf-8", errors="replace") as f:
    data = json.load(f)

entries = data.get("log", {}).get("entries", [])
print(f"Total entries: {len(entries)}")

found: dict[str, str] = {}

for i, entry in enumerate(entries):
    req = entry.get("request", {})
    url = req.get("url", "")

    # From cookie objects
    for c in req.get("cookies", []):
        n, v = c.get("name", ""), c.get("value", "")
        if n in TARGET and n not in found:
            found[n] = v

    # From Cookie header string
    for hdr in req.get("headers", []):
        if hdr.get("name", "").lower() == "cookie":
            for part in hdr.get("value", "").split(";"):
                part = part.strip()
                if "=" in part:
                    k, _, v = part.partition("=")
                    if k.strip() in TARGET and k.strip() not in found:
                        found[k.strip()] = v.strip()

    # Also check response Set-Cookie
    for hdr in entry.get("response", {}).get("headers", []):
        if hdr.get("name", "").lower() == "set-cookie":
            val = hdr.get("value", "")
            if "=" in val:
                k, _, rest = val.partition("=")
                v = rest.split(";")[0]
                if k.strip() in TARGET and k.strip() not in found:
                    found[k.strip()] = v.strip()

print(f"\nFound {len(found)} target cookies:")
for k, v in sorted(found.items()):
    print(f"  {k} = {v[:60]}{'...' if len(v)>60 else ''}")

# Now show first entry's raw cookie names to debug
entry0 = entries[0]
req0 = entry0.get("request", {})
print(f"\nEntry[0] URL: {req0.get('url','')[:80]}")
print(f"Entry[0] cookie objects ({len(req0.get('cookies',[]))}):")
for c in req0.get("cookies", []):
    n, v = c.get("name",""), c.get("value","")
    marker = "[TARGET]" if n in TARGET else "       "
    print(f"  {marker} {n} = {v[:50]}")
