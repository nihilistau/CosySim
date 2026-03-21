"""Service pillar skill packs — nexus, lmstudio, monitoring, recovery, etc.

These skill files live in ``engine/skills/builtin/`` (parent directory) and
are re-exported here for pillar-aware imports.
"""
from engine.skills.builtin import (
    agent_state_skills,
    anythingllm_skills,
    argus_skills,
    autonomy_skills,
    cdp_skills,
    coder_skills,
    codespace_skills,
    copilot_skills,
    debugger_skills,
    evaluation_skills,
    google_account_skills,
    health_skills,
    homeassistant_skills,
    inference_skills,
    lifecycle_mgmt_skills,
    lifecycle_skills,
    lmstudio_server_skills,
    monitoring_skills,
    news_skills,
    nexus_skills,
    nlm_forge_skills,
    notebooklm_skills,
    observability_skills,
    orchestration_skills,
    process_monitor_skills,
    process_skills,
    recovery_skills,
    resilience_skills,
    security_skills,
    self_improvement_skills,
    system_management_skills,
    testing_skills,
    training_skills,
    workspace_skills,
)

PILLAR = "service"
