import re

with open("engine/mcp/devtools_server.py", "r", encoding="utf-8") as f:
    content = f.read()

funcs = {
    "capture_training_data": "    return capture_training_data_impl(\n        user_message=user_message, agent_response=agent_response, dataset_type=dataset_type, quality_score=quality_score, character_id=character_id\n    )",
    "generate_content": "    return generate_content_impl(character_id=character_id, content_type=content_type)",
    "training_stats": "    return training_stats_impl()",
    "training_export": "    return training_export_impl(format=format, min_quality=min_quality)",
    "training_sync_nexus": "    return training_sync_nexus_impl()",
    "finetune_submit": "    return finetune_submit_impl(model_type=model_type, base_model=base_model)",
    "finetune_run_next": "    return finetune_run_next_impl()",
    "finetune_list_jobs": "    return finetune_list_jobs_impl(status=status)",
    "finetune_build_dataset": "    return finetune_build_dataset_impl(model_type=model_type, count=count)",
    "finetune_dataset_status": "    return finetune_dataset_status_impl()",
    "model_registry_list": "    return model_registry_list_impl(model_type=model_type)",
    "model_benchmark_run": "    return model_benchmark_run_impl(model_type=model_type)",
    "model_benchmark_leaderboard": "    return model_benchmark_leaderboard_impl()",
    "model_promote": "    return model_promote_impl(model_id=model_id, model_type=model_type)",
    "teacher_generate_dataset": "    return teacher_generate_dataset_impl(model_type=model_type, count=count)",
    "finetuned_router_status": "    return finetuned_router_status_impl()",
    "finetuned_router_load_registry": "    return finetuned_router_load_registry_impl()",
    "metrics_dashboard": "    return metrics_dashboard_impl(hours=hours)",
    "metrics_collect_all": "    return metrics_collect_all_impl()",
    "metrics_check_regressions": "    return metrics_check_regressions_impl(threshold_pct=threshold_pct)",
    "metrics_snapshot": "    return metrics_snapshot_impl()",
    "reflection_run": "    return reflection_run_impl(period=period, days=days, use_nlm=use_nlm)",
    "reflection_history": "    return reflection_history_impl(limit=limit)",
    "reflection_latest_insights": "    return reflection_latest_insights_impl(limit=limit)",
    "experiment_scan_and_propose": "    return experiment_scan_and_propose_impl()",
    "experiment_list_proposals": "    return experiment_list_proposals_impl(status=status)",
    "experiment_list_templates": "    return experiment_list_templates_impl()"
}

import ast

class BodyReplacer(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        if node.name in funcs:
            pass # we'll use text manipulation based on line numbers
        return node
    
    def visit_AsyncFunctionDef(self, node):
        if node.name in funcs:
            pass
        return node

# AST based string replacement
lines = content.split('\n')
tree = ast.parse(content)

changes = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in funcs:
            start_lineno = node.body[0].lineno - 1
            end_lineno = node.body[-1].end_lineno
            # Retain the docstring if it exists
            if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                start_lineno = node.body[1].lineno - 1 if len(node.body) > 1 else node.body[0].end_lineno
            changes.append((start_lineno, end_lineno, funcs[node.name]))

changes.sort(key=lambda x: x[0], reverse=True)

for start, end, new_body in changes:
    lines[start:end] = [new_body]

with open("engine/mcp/devtools_server.py", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

