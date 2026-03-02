# Phase 6 Hand-off: Nexus & NotebookLM Refactoring Plan

## Background
In Phases 1-5, we successfully extracted all inline `try...except` tools from the MCP server interfaces (`cosysim_server.py` and `devtools_server.py`) into pure, typed logic domains in `engine/mcp/tools/`. 

During this process, we identified severe structural issues in the `engine/nexus/` subsystem. Nexus acts as a monolithic "store all" database for wildly different domains (agent memory, youtube transcripts, hardware benchmarks, and code rules). 

Because `NexusClient` (`engine/nexus/client.py`) lacked domain models, it fell into the anti-pattern of using massive, unstructured, untyped nested dictionaries `Dict[str, Any]` everywhere. This caused complex serialization quirks at the MCP boundary where un-serializable objects leaked out.

## The Goal
The goal of Phase 6 is to fix the underlying data flow by introducing **Pydantic Models** and breaking up the "God Object" `NexusClient`.

## Artifacts Prepared
1. **`engine/nexus/models.py`**: A new file has been seeded with foundational Pydantic models (`NexusEntry`, `AgentMemory`, `NexusRule`, `SessionLog`). This is your starting point.

## Action Plan for the Next Agent

### Step 1: Integrate Pydantic into `NexusClient`
- Modify `engine/nexus/client.py`.
- Change generic return types (`List[Dict]`) to typed Pydantic responses (e.g., `List[NexusEntry]`).
- Validate incoming data in `add_entry` using `NexusEntryCreate`.
- **Note:** Ensure JSON serialization/deserialization over the HTTP boundary `_get()`, `_post()` seamlessly maps to these Pydantic models.

### Step 2: Break Up the "God Object" Client
`client.py` currently contains ~450 lines mixing up Rules, Sessions, Benchmarks, Youtube Imports, and basic Q&A. 
- Create **domain-specific facades or sub-clients**:
  - `NexusRulesClient` (handles `add_rule`, `get_rules`)
  - `NexusSessionClient` (handles `log_session`)
  - `NexusMemoryClient` (handles `agent_submit`, `agent_recall`)
- The base `NexusClient` should become a simpler HTTP wrapper or a facade holding instances of these sub-clients.

### Step 3: Refactor NotebookLM Bridge (`nlm_engine.py`)
- NotebookLM (NLM) currently returns highly complex, nested, arbitrary Google internal JSON structures (from `batchexecute`). 
- Look at `nlm_engine.py` and `nlm_notebook_manager.py`. Create explicit Pydantic models representing an `NLMNotebook`, `NLMSource`, and `NLMAnswer`. 
- Ensure that the NLM bridge only returns these strictly typed models back to the MCP tool layer, rather than raw Google payload dictionaries.

### Testing Constraint
Keep all modifications local. Run `pytest tests/test_pipeline_smoke.py` frequently to ensure you haven't broken the pipeline routing.
