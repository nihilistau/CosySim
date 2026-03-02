import json
from typing import Optional


def local_agent_get_tasks_impl(
    model_size: str = "worker", limit: int = 10, tags: str = ""
) -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    tasks = get_local_agent_bridge().get_ready_tasks(
        model_size=model_size, limit=limit, tags=tag_list
    )
    return json.dumps({"tasks": tasks, "count": len(tasks)})


def local_agent_claim_task_impl(task_id: str, agent_id: str) -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    result = get_local_agent_bridge().claim_task(task_id=task_id, agent_id=agent_id)
    return json.dumps(result)


def local_agent_task_context_impl(task_id: str) -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    ctx = get_local_agent_bridge().get_task_context(task_id=task_id)
    return json.dumps(ctx)


def local_agent_complete_task_impl(
    task_id: str, result: str, files_changed: str = ""
) -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    file_list = (
        [f.strip() for f in files_changed.split(",") if f.strip()]
        if files_changed
        else []
    )
    out = get_local_agent_bridge().complete_task(
        task_id=task_id, result=result, files_changed=file_list
    )
    return json.dumps(out)


def local_agent_fail_task_impl(task_id: str, reason: str, retry: bool = False) -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    out = get_local_agent_bridge().fail_task(
        task_id=task_id, reason=reason, retry=retry
    )
    return json.dumps(out)


def local_agent_manifest_impl(model_size: str = "worker") -> str:
    from engine.nexus.local_agent_bridge import get_local_agent_bridge

    return get_local_agent_bridge().get_agent_manifest(model_size=model_size)
