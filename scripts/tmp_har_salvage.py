import re, json
from pathlib import Path

# Try streaming parse of broken HAR - extract what we can before the truncation
path = Path("data/har_files/aistudio.google.com.har")
print(f"Scanning {path.stat().st_size//1024//1024}MB HAR for gems...")

found = {"api_keys": set(), "methods": set(), "models": set(), "responses": []}
buf = ""
for chunk in iter(lambda: path.read_bytes()[len(buf.encode()):len(buf.encode())+65536].decode("utf-8","replace"), ""):
    break

# Read file in text chunks
with open(path, encoding="utf-8", errors="replace") as f:
    content = f.read()

print(f"Read {len(content)//1024}KB")

# Extract API keys
for key in re.findall(r'"key"\s*:\s*"(AIza[A-Za-z0-9_\-]{30,})"', content):
    found["api_keys"].add(key)
for key in re.findall(r'[?&]key=(AIza[A-Za-z0-9_\-]{30,})', content):
    found["api_keys"].add(key)

# Extract MakerSuiteService methods  
for m in re.findall(r"MakerSuiteService/(\w+)", content):
    found["methods"].add(m)

# Extract model names
for m in re.findall(r'"(models/gemini[-\w.]+)"', content):
    found["models"].add(m)

# Extract batchexecute rpcids
rpcids = re.findall(r'rpcids=([A-Za-z0-9]+)', content)

# Extract thought signatures
thoughts = re.findall(r'"thoughtSignature":"([A-Za-z0-9+/=]{20,})"', content)

# Extract access tokens
tokens = re.findall(r'"(ya29\.[A-Za-z0-9_\-]{20,})"', content)

print(f"\nAPI Keys: {list(found['api_keys'])}")
print(f"Methods: {sorted(found['methods'])[:30]}")
print(f"Models: {sorted(found['models'])[:20]}")
print(f"rpcids: {list(set(rpcids))[:20]}")
print(f"Thought signatures: {len(thoughts)}")
print(f"Access tokens: {len(tokens)} found")
if tokens:
    print(f"  Token: {tokens[0][:80]}...")
