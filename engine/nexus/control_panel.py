"""
Nexus Control Panel — Advanced Streamlit dashboard for Nexus KMS.

Features:
    - Knowledge browser with namespace filtering
    - Rules editor with scope/type management
    - Memory viewer for agents and Copilot
    - Training data stats and export
    - Research session manager
    - System health monitoring
    - Content generation tools

Run:
    streamlit run engine/nexus/control_panel.py --server.port 8702
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

import requests
import streamlit as st
import logging

logger = logging.getLogger(__name__)


def _get_nexus_url() -> str:
    from engine.port_registry import get_service_url
    return get_service_url("nexus")


# ══════════════════════════════════════════════════════════════════════
#  API Helpers
# ══════════════════════════════════════════════════════════════════════

def api_get(path: str, params: Dict[str, Any] | None = None) -> Any:
    """GET from Nexus API."""
    try:
        r = requests.get(f"{_get_nexus_url()}{path}", params=params or {}, timeout=5)
        if r.ok:
            data = r.json()
            return data.get("data", data) if isinstance(data, dict) else data
        return []
    except Exception as e:
        st.error(f"API error: {e}")
        return []


def api_post(path: str, data: Dict[str, Any]) -> Any:
    """POST to Nexus API."""
    try:
        r = requests.post(f"{_get_nexus_url()}{path}", json=data, timeout=5)
        return r.json() if r.ok else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


def api_delete(path: str) -> bool:
    """DELETE from Nexus API."""
    try:
        r = requests.delete(f"{_get_nexus_url()}{path}", timeout=5)
        return r.ok
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
#  Page Config
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Nexus Control Panel",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: #1a1f2e;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .namespace-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    .ns-system { background: #2563eb; color: white; }
    .ns-scene { background: #16a34a; color: white; }
    .ns-agent { background: #d97706; color: white; }
    .ns-copilot { background: #9333ea; color: white; }
    .ns-training { background: #dc2626; color: white; }
    .ns-research { background: #0891b2; color: white; }
    .ns-content { background: #65a30d; color: white; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
#  Sidebar Navigation
# ══════════════════════════════════════════════════════════════════════

st.sidebar.title("🧠 Nexus Control Panel")
page = st.sidebar.radio(
    "Navigate",
    [
        "📊 Dashboard",
        "📚 Knowledge Browser",
        "⚖️ Rules Engine",
        "🧬 Memory Viewer",
        "🎓 Training Data",
        "🔬 Research",
        "🎭 Content Generator",
        "🔧 Maintenance",
    ],
)


# ══════════════════════════════════════════════════════════════════════
#  Dashboard Page
# ══════════════════════════════════════════════════════════════════════

if page == "📊 Dashboard":
    st.title("📊 Nexus Knowledge System Dashboard")

    entries = api_get("/api/entries", {"limit": 500})
    qa_list = api_get("/api/qa", {"limit": 500})
    rules = api_get("/api/rules")

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📄 Entries", len(entries) if isinstance(entries, list) else 0)
    col2.metric("❓ Q&A Pairs", len(qa_list) if isinstance(qa_list, list) else 0)
    col3.metric("⚖️ Rules", len(rules) if isinstance(rules, list) else 0)

    # Health check
    try:
        health = requests.get(f"{_get_nexus_url()}/api/health", timeout=3)
        col4.metric("💚 Health", "Online" if health.ok else "Offline")
    except Exception:
        col4.metric("💔 Health", "Offline")

    if isinstance(entries, list) and entries:
        st.subheader("📊 Knowledge Distribution")

        col1, col2 = st.columns(2)

        with col1:
            # By namespace (detect from tags)
            ns_counts: Dict[str, int] = Counter()
            for e in entries:
                tags = str(e.get("tags", ""))
                for ns in ["system", "scene", "agent", "copilot", "training", "research", "content"]:
                    if ns in tags:
                        ns_counts[ns] += 1
                        break
                else:
                    ns_counts["untagged"] += 1
            st.bar_chart(dict(ns_counts))
            st.caption("Entries by Namespace")

        with col2:
            # By content type
            type_counts = dict(Counter(
                e.get("content_type", "unknown") for e in entries
            ))
            st.bar_chart(type_counts)
            st.caption("Entries by Content Type")

        # Recent entries
        st.subheader("🕐 Recent Entries")
        sorted_entries = sorted(entries, key=lambda e: e.get("created_at", ""), reverse=True)[:10]
        for e in sorted_entries:
            with st.expander(f"📄 {e.get('title', 'Untitled')}", expanded=False):
                st.text(f"Type: {e.get('content_type', '?')} | Category: {e.get('category', '?')}")
                st.text(f"Tags: {e.get('tags', '')}")
                st.markdown(e.get("content", "")[:500])


# ══════════════════════════════════════════════════════════════════════
#  Knowledge Browser
# ══════════════════════════════════════════════════════════════════════

elif page == "📚 Knowledge Browser":
    st.title("📚 Knowledge Browser")

    col1, col2, col3 = st.columns(3)
    with col1:
        search_query = st.text_input("🔍 Search", placeholder="Search knowledge base...")
    with col2:
        ns_filter = st.selectbox(
            "Namespace",
            ["All", "system", "scene", "agent", "copilot", "training", "research", "content"],
        )
    with col3:
        type_filter = st.selectbox(
            "Content Type",
            ["All", "document", "code", "note", "prompt", "memory", "snippet", "research", "history"],
        )

    if search_query:
        results = api_get("/api/search", {"q": search_query, "limit": 50})
    else:
        results = api_get("/api/entries", {"limit": 100})

    if isinstance(results, list):
        # Apply filters
        filtered = results
        if ns_filter != "All":
            filtered = [e for e in filtered if ns_filter in str(e.get("tags", ""))]
        if type_filter != "All":
            filtered = [e for e in filtered if e.get("content_type") == type_filter]

        st.caption(f"Showing {len(filtered)} entries")

        for e in filtered:
            tags = str(e.get("tags", ""))
            ns_badge = ""
            for ns in ["system", "scene", "agent", "copilot", "training", "research", "content"]:
                if ns in tags:
                    ns_badge = f'<span class="namespace-badge ns-{ns}">{ns}</span>'
                    break

            with st.expander(f"{e.get('title', 'Untitled')} — {e.get('content_type', '?')}"):
                st.markdown(ns_badge, unsafe_allow_html=True)
                st.text(f"ID: {e.get('id', '?')} | Category: {e.get('category', '?')}")
                st.text(f"Tags: {tags}")
                st.markdown(e.get("content", "")[:1000])

                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"🗑️ Delete", key=f"del_{e.get('id')}"):
                        if api_delete(f"/api/entries/{e['id']}"):
                            st.success("Deleted!")
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════
#  Rules Engine
# ══════════════════════════════════════════════════════════════════════

elif page == "⚖️ Rules Engine":
    st.title("⚖️ Rules Engine")

    rules = api_get("/api/rules")
    if isinstance(rules, list):
        st.metric("Total Rules", len(rules))

        # Group by scope
        by_scope: Dict[str, list] = {}
        for r in rules:
            scope = r.get("scope", "global")
            by_scope.setdefault(scope, []).append(r)

        for scope, scope_rules in sorted(by_scope.items()):
            with st.expander(f"📋 Scope: {scope} ({len(scope_rules)} rules)", expanded=False):
                for rule in scope_rules:
                    st.markdown(f"**{rule.get('name', 'Unnamed')}**")
                    st.text(f"Type: {rule.get('rule_type', '?')} | Priority: {rule.get('priority', 50)}")
                    condition = rule.get("condition", {})
                    if isinstance(condition, str):
                        try:
                            condition = json.loads(condition)
                        except Exception:
                            logger.debug("Suppressed exception", exc_info=True)
                    st.json(condition)
                    st.divider()

    # Add new rule
    st.subheader("➕ Add Rule")
    with st.form("add_rule"):
        rule_name = st.text_input("Rule Name")
        rule_scope = st.selectbox(
            "Scope",
            ["global", "namespace:system", "namespace:scene", "namespace:agent",
             "namespace:copilot", "namespace:training", "scene:*", "agent:*"],
        )
        rule_type = st.selectbox("Type", ["validation", "access", "governance", "quality"])
        rule_priority = st.slider("Priority", 1, 200, 50)
        rule_condition = st.text_area("Condition (JSON)", value='{"check": ""}')
        rule_action = st.text_area("Action (JSON)", value='{"type": "warn", "message": ""}')

        if st.form_submit_button("Create Rule"):
            try:
                result = api_post("/api/rules", {
                    "name": rule_name,
                    "scope": rule_scope,
                    "rule_type": rule_type,
                    "priority": rule_priority,
                    "condition": json.loads(rule_condition),
                    "action": json.loads(rule_action),
                })
                st.success(f"Rule created: {result}")
            except json.JSONDecodeError:
                st.error("Invalid JSON in condition or action")


# ══════════════════════════════════════════════════════════════════════
#  Memory Viewer
# ══════════════════════════════════════════════════════════════════════

elif page == "🧬 Memory Viewer":
    st.title("🧬 Memory Viewer")

    agent_id = st.selectbox(
        "Select Agent",
        ["copilot", "lola", "viktor", "aria", "frankie", "mira", "system"],
    )

    memories = api_get("/api/search", {"q": f"agent:{agent_id} memory", "limit": 50})

    if isinstance(memories, list):
        agent_mems = [
            m for m in memories
            if f"agent:{agent_id}" in str(m.get("tags", "")) and "memory" in str(m.get("tags", ""))
        ]
        st.metric(f"Memories for {agent_id}", len(agent_mems))

        for m in agent_mems:
            tags = str(m.get("tags", ""))
            importance = "?"
            mem_type = "?"
            for t in tags.replace('"', "").replace("[", "").replace("]", "").split(","):
                t = t.strip()
                if t.startswith("importance:"):
                    importance = t.split(":")[1]
                elif t.startswith("type:"):
                    mem_type = t.split(":")[1]

            with st.expander(f"🧠 {m.get('title', 'Memory')[:60]} (imp:{importance}, type:{mem_type})"):
                st.markdown(m.get("content", ""))
                if st.button(f"Forget", key=f"forget_{m.get('id')}"):
                    if api_delete(f"/api/entries/{m['id']}"):
                        st.success("Memory forgotten!")
                        st.rerun()

    # Store new memory
    st.subheader("💾 Store Memory")
    with st.form("store_memory"):
        mem_content = st.text_area("Memory content")
        mem_type = st.selectbox("Type", ["observation", "preference", "fact", "emotion", "event", "decision"])
        mem_importance = st.slider("Importance", 0.0, 1.0, 0.5, 0.1)

        if st.form_submit_button("Remember"):
            from engine.nexus.nexus_memory import NexusMemory
            mem = NexusMemory(namespace="agent", agent_id=agent_id)
            entry_id = mem.remember(mem_content, importance=mem_importance, memory_type=mem_type)
            if entry_id:
                st.success(f"Stored! ID: {entry_id}")
            else:
                st.error("Failed to store memory")


# ══════════════════════════════════════════════════════════════════════
#  Training Data
# ══════════════════════════════════════════════════════════════════════

elif page == "🎓 Training Data":
    st.title("🎓 Training Data Pipeline")

    from engine.nexus.training_pipeline import TrainingPipeline
    tp = TrainingPipeline()
    stats = tp.get_stats()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Pairs", stats.get("total", 0))
    col2.metric("High Quality", stats.get("by_quality", {}).get("high", 0))
    col3.metric("Buffer Size", stats.get("buffer_size", 0))

    if stats.get("by_type"):
        st.subheader("📊 By Dataset Type")
        st.bar_chart(stats["by_type"])

    # Generate synthetic data
    st.subheader("🔄 Generate Synthetic Data")
    col1, col2 = st.columns(2)
    with col1:
        gen_type = st.selectbox("Dataset Type", ["tag_extraction", "tool_routing"])
    with col2:
        gen_count = st.number_input("Count", 1, 50, 5)
    if st.button("Generate"):
        examples = tp.generate_synthetic(gen_type, gen_count)
        st.success(f"Generated {len(examples)} examples")

    # Export
    st.subheader("📦 Export Dataset")
    export_type = st.selectbox("Export Type", ["conversation", "tag_extraction", "tool_routing", "response_quality"], key="export")
    min_q = st.slider("Min Quality", 0.0, 1.0, 0.5, 0.1)
    if st.button("Export to JSONL"):
        result = tp.export_dataset(export_type, min_quality=min_q)
        if result.get("count", 0) > 0:
            st.success(f"Exported {result['count']} pairs to {result.get('train_file', '?')}")
        else:
            st.warning("No matching data found")

    # Capture new pair
    st.subheader("📝 Capture Training Pair")
    with st.form("capture"):
        user_msg = st.text_input("User Message")
        agent_resp = st.text_area("Agent Response")
        ds_type = st.selectbox("Type", ["conversation", "tag_extraction", "tool_routing"])
        quality = st.slider("Quality", 0.0, 1.0, 0.7, 0.1)
        char_id = st.text_input("Character ID (optional)")

        if st.form_submit_button("Capture"):
            entry_id = tp.capture_interaction(user_msg, agent_resp, dataset_type=ds_type,
                                               quality_score=quality, character_id=char_id)
            if entry_id:
                st.success(f"Captured! ID: {entry_id}")


# ══════════════════════════════════════════════════════════════════════
#  Research
# ══════════════════════════════════════════════════════════════════════

elif page == "🔬 Research":
    st.title("🔬 Research Sessions")

    from engine.nexus.workflows import ResearchWorkflow, NotebookWorkflow

    # NLM status
    nw = NotebookWorkflow()
    nlm_status = nw.check_nlm_status()
    st.sidebar.markdown(f"**NLM Status:** {'🟢 Online' if nlm_status.get('http') else '🔴 Offline'}")

    # Research
    rw = ResearchWorkflow()
    st.subheader("🔍 Research a Topic")
    question = st.text_input("Research Question", placeholder="How should we implement X?")
    depth = st.selectbox("Depth", ["auto", "shallow", "deep"])

    if st.button("Research") and question:
        with st.spinner("Researching..."):
            result = rw.research(question, depth=depth)
        if result.get("answer"):
            st.markdown("### Answer")
            st.markdown(result["answer"])
            st.caption(f"Sources: {len(result.get('sources', []))} | Stored: {result.get('stored', False)}")
        else:
            st.warning("No answer found")

    # Notebooks
    st.subheader("📓 NotebookLM Notebooks")
    notebooks = api_get("/api/search", {"q": "notebook research", "limit": 20})
    if isinstance(notebooks, list):
        nb_entries = [e for e in notebooks if "notebook" in str(e.get("tags", ""))]
        for nb in nb_entries:
            with st.expander(f"📓 {nb.get('title', 'Notebook')}"):
                content = nb.get("content", "")
                try:
                    parsed = json.loads(content)
                    st.json(parsed)
                except Exception:
                    st.markdown(content[:500])

    if st.button("🌱 Seed All Notebooks"):
        result = nw.seed_notebook_knowledge("all")
        st.success(f"Seeded: {result}")


# ══════════════════════════════════════════════════════════════════════
#  Content Generator
# ══════════════════════════════════════════════════════════════════════

elif page == "🎭 Content Generator":
    st.title("🎭 Content Generator")

    from engine.nexus.workflows import ContentWorkflow
    cw = ContentWorkflow()

    st.subheader("Generate Character Content")
    col1, col2 = st.columns(2)
    with col1:
        char_id = st.selectbox("Character", ["lola", "viktor", "aria", "frankie", "mira"])
    with col2:
        content_type = st.selectbox("Content Type", ["greetings", "reactions", "scene_descriptions"])

    if st.button("Generate"):
        with st.spinner("Generating..."):
            if content_type == "greetings":
                ids = cw.generate_greetings(char_id)
                st.success(f"Generated {len(ids)} greeting sets")
            elif content_type == "reactions":
                ids = cw.generate_reactions(char_id)
                st.success(f"Generated {len(ids)} reaction sets")
            elif content_type == "scene_descriptions":
                scene = st.text_input("Scene ID", value="penthouse")
                ids = cw.generate_scene_descriptions(scene)
                st.success(f"Generated {len(ids)} descriptions")

    # Browse existing content
    st.subheader("📋 Existing Content")
    content_entries = api_get("/api/search", {"q": f"content character:{char_id}", "limit": 20})
    if isinstance(content_entries, list):
        for e in content_entries:
            if "content" in str(e.get("tags", "")):
                with st.expander(f"🎭 {e.get('title', 'Content')}"):
                    content = e.get("content", "")
                    try:
                        parsed = json.loads(content)
                        st.json(parsed)
                    except Exception:
                        st.markdown(content[:500])


# ══════════════════════════════════════════════════════════════════════
#  Maintenance
# ══════════════════════════════════════════════════════════════════════

elif page == "🔧 Maintenance":
    st.title("🔧 Nexus Maintenance")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🏥 Health Check")
        try:
            health = requests.get(f"{_get_nexus_url()}/api/health", timeout=3)
            if health.ok:
                st.json(health.json())
            else:
                st.error("Health check failed")
        except Exception as e:
            st.error(f"Cannot reach Nexus: {e}")

    with col2:
        st.subheader("📊 Statistics")
        try:
            stats = requests.get(f"{_get_nexus_url()}/api/stats", timeout=3)
            if stats.ok:
                st.json(stats.json())
        except Exception:
            st.warning("Stats unavailable")

    st.subheader("🔧 Actions")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🌱 Seed Knowledge"):
            from engine.nexus.nexus_seeder import NexusSeeder
            seeder = NexusSeeder()
            result = seeder.seed("all")
            st.success(f"Seeded: {result}")

    with col2:
        if st.button("🔍 Dedup Entries"):
            entries = api_get("/api/entries", {"limit": 500})
            if isinstance(entries, list):
                seen: Dict[str, str] = {}
                dups = []
                for e in entries:
                    title = e.get("title", "").strip().lower()
                    if title in seen:
                        dups.append(e["id"])
                    else:
                        seen[title] = e["id"]
                removed = sum(1 for d in dups if api_delete(f"/api/entries/{d}"))
                st.success(f"Removed {removed} duplicates")

    with col3:
        if st.button("🏷️ Retag Namespaces"):
            from engine.nexus.nexus_namespaces import detect_namespace
            entries = api_get("/api/entries", {"limit": 500})
            if isinstance(entries, list):
                updated = 0
                for e in entries:
                    tags = json.loads(e.get("tags", "[]")) if isinstance(e.get("tags"), str) else (e.get("tags") or [])
                    ns = detect_namespace(e.get("category", ""), tags)
                    if ns not in tags:
                        tags.append(ns)
                        r = requests.put(f"{_get_nexus_url()}/api/entries/{e['id']}", json={"tags": tags}, timeout=5)
                        if r.ok:
                            updated += 1
                st.success(f"Retagged {updated} entries")

    with col4:
        if st.button("💾 Backup"):
            result = api_post("/api/backup", {})
            st.success(f"Backup: {result}")
