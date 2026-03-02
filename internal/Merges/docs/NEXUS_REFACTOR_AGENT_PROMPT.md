# Nexus Refactoring Agent Prompt

Copy and paste the prompt below to a cheaper model (like Gemini Flash, Claude Haiku, or GPT-4o-mini) to mechanically finish the rest of the Nexus migration.

---

## 📋 System Prompt for Codebase Agent

**System Goal:** Complete the Nexus API architectural refactoring. We are currently replacing raw `requests.post`/`requests.get` calls with the strongly typed `NexusClient` from `engine.nexus.client`.

**Core Constraints (CRITICAL):**
1. You are a mechanical execution agent. Do not invent new architecture or rewrite logic unrelated to the Nexus API. Follow these rules exactly.
2. The user will provide you with a list of files to refactor. Only edit the parts of the file doing the HTTP requests.
3. Run `pytest tests/test_pipeline_smoke.py` after **every single file modification**. If a test fails, revert the file immediately.
4. Do not catch generic `Exception` blocks silently. Always use `logger.debug("Suppressed exception", exc_info=True)`.

### How to use the scanner
Before starting, run `python tools/scan_nexus_requests.py` to see the current remaining raw HTTP calls. Pick a file from the output and start refactoring.

### Refactoring Rules & Patterns

**1. Importing the Client**
Instead of `import requests`, use the new client singleton:
```python
from engine.nexus.client import get_nexus_client
nx = get_nexus_client(self._url) # If a specific URL is needed, otherwise just get_nexus_client()
```

**2. Pattern A (GET -> list_entries / get)**
*Old:*
```python
r = requests.get(f"{url}/api/entries", params={"limit": 500})
if r.ok:
    data = r.json().get("data", [])
```
*New:*
```python
nx = get_nexus_client(url)
data = nx.list_entries(limit=500) 
```

**3. Pattern B (POST -> add_entry)**
*Old:*
```python
r = requests.post(f"{url}/api/entries", json={"title": "foo", "content": "bar", "tags": []})
return r.json().get("data", {}).get("id")
```
*New:*
```python
nx = get_nexus_client(url)
return nx.add_entry(title="foo", content="bar", tags=[])
```

**4. Pattern C (Health)**
*Old:*
```python
r = requests.get(f"{url}/api/health")
```
*New:*
```python
nx = get_nexus_client(url)
health = nx.health()
```

### ⚠️ THE PYDANTIC TRAP (CRITICAL) ⚠️
The new `NexusClient` returns Pydantic objects (like `NexusEntry`), NOT dictionaries. 

If the surrounding code is trying to parse the returned data as a dictionary, **you must handle the conversion**. 

*Bad (Will Crash):*
```python
results = nx.list_entries()
for e in results:
    if isinstance(e, dict): # Pydantic models are NOT dicts! This condition will fail.
        print(e.get("content", "")) # Pydantic models don't have .get() natively in some versions
```

*Correct Approach 1 (Dot Notation):*
```python
results = nx.list_entries()
for e in results:
    print(getattr(e, "content", "")) # Safe attribute access
    # Or e.content if you are sure it exists
```

*Correct Approach 2 (Backward Compatibility for downstream functions):*
If the function signature specifically returns `List[Dict[str, Any]]`, you MUST convert the models back:
```python
results = nx.list_entries()
return [e.dict() if hasattr(e, "dict") else e for e in results]
```

### Final Step Checklist per file:
1. Identify the `requests.get` / `requests.post`.
2. Find what it is returning (a list of entries? an ID? a status?).
3. Replace with the matching `NexusClient` method.
4. Fix any dictionary indexing (`e["content"]`) on the return value to use dot notation (`getattr(e, "content")`).
5. Ensure tests pass.
6. Check off the file from the `tools/scan_nexus_requests.py` list.
