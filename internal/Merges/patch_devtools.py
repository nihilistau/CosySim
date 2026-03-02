import re

with open("engine/mcp/devtools_server.py", "r", encoding="utf-8") as f:
    content = f.read()

imports = """
from engine.mcp.tools.training_tools import (
    capture_training_data_impl, generate_content_impl, training_stats_impl,
    training_export_impl, training_sync_nexus_impl, finetune_submit_impl,
    finetune_run_next_impl, finetune_list_jobs_impl, finetune_build_dataset_impl,
    finetune_dataset_status_impl, model_registry_list_impl, model_benchmark_run_impl,
    model_benchmark_leaderboard_impl, model_promote_impl, teacher_generate_dataset_impl,
    finetuned_router_status_impl, finetuned_router_load_registry_impl
)

from engine.mcp.tools.metrics_tools import (
    metrics_dashboard_impl, metrics_collect_all_impl, metrics_check_regressions_impl,
    metrics_snapshot_impl, reflection_run_impl, reflection_history_impl,
    reflection_latest_insights_impl, experiment_scan_and_propose_impl,
    experiment_list_proposals_impl, experiment_list_templates_impl
)
"""

if "engine.mcp.tools.training_tools" not in content:
    # insert after from engine.mcp.tools.ha_tools import ... )
    content = re.sub(r'(from engine\.mcp\.tools\.ha_tools import \([^\)]+\)\n)', r'\1\n' + imports.strip() + '\n', content)


replacements = {
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def capture_training_data\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef capture_training_data(\1) -> str:\n    return capture_training_data_impl(\n        user_message=user_message, agent_response=agent_response, dataset_type=dataset_type, quality_score=quality_score, character_id=character_id\n    )',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def generate_content\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef generate_content(\1) -> str:\n    return generate_content_impl(character_id=character_id, content_type=content_type)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def training_stats\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef training_stats() -> str:\n    return training_stats_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def training_export\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef training_export(\1) -> str:\n    return training_export_impl(format=format, min_quality=min_quality)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def training_sync_nexus\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef training_sync_nexus() -> str:\n    return training_sync_nexus_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetune_submit\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetune_submit(\1) -> str:\n    return finetune_submit_impl(model_type=model_type, base_model=base_model)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetune_run_next\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetune_run_next() -> str:\n    return finetune_run_next_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetune_list_jobs\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetune_list_jobs(\1) -> str:\n    return finetune_list_jobs_impl(status=status)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetune_build_dataset\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetune_build_dataset(\1) -> str:\n    return finetune_build_dataset_impl(model_type=model_type, count=count)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetune_dataset_status\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetune_dataset_status() -> str:\n    return finetune_dataset_status_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def model_registry_list\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def model_registry_list(\1) -> str:\n    return model_registry_list_impl(model_type=model_type)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def model_benchmark_run\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def model_benchmark_run(\1) -> str:\n    return model_benchmark_run_impl(model_type=model_type)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def model_benchmark_leaderboard\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def model_benchmark_leaderboard() -> str:\n    return model_benchmark_leaderboard_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def model_promote\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def model_promote(\1) -> str:\n    return model_promote_impl(model_id=model_id, model_type=model_type)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def teacher_generate_dataset\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def teacher_generate_dataset(\1) -> str:\n    return teacher_generate_dataset_impl(model_type=model_type, count=count)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetuned_router_status\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetuned_router_status() -> str:\n    return finetuned_router_status_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def finetuned_router_load_registry\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\nasync def finetuned_router_load_registry() -> str:\n    return finetuned_router_load_registry_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def metrics_dashboard\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef metrics_dashboard(\1) -> str:\n    return metrics_dashboard_impl(hours=hours)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def metrics_collect_all\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef metrics_collect_all() -> str:\n    return metrics_collect_all_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def metrics_check_regressions\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef metrics_check_regressions(\1) -> str:\n    return metrics_check_regressions_impl(threshold_pct=threshold_pct)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def metrics_snapshot\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef metrics_snapshot() -> str:\n    return metrics_snapshot_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def reflection_run\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef reflection_run(\1) -> str:\n    return reflection_run_impl(period=period, days=days, use_nlm=use_nlm)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def reflection_history\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef reflection_history(\1) -> str:\n    return reflection_history_impl(limit=limit)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def reflection_latest_insights\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef reflection_latest_insights(\1) -> str:\n    return reflection_latest_insights_impl(limit=limit)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def experiment_scan_and_propose\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef experiment_scan_and_propose() -> str:\n    return experiment_scan_and_propose_impl()',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def experiment_list_proposals\((.*?)\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef experiment_list_proposals(\1) -> str:\n    return experiment_list_proposals_impl(status=status)',
    r'(?sm)@mcp\.tool\(\)\n(?:async )?def experiment_list_templates\(\) -> str:.*?(?=\n\n@|\Z)': 
        r'@mcp.tool()\ndef experiment_list_templates() -> str:\n    return experiment_list_templates_impl()',
}

for pattern, replacement in replacements.items():
    content = re.sub(pattern, replacement, content)

with open("engine/mcp/devtools_server.py", "w", encoding="utf-8") as f:
    f.write(content)

