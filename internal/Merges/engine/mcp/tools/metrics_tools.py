import json


def metrics_dashboard_impl(hours: int = 24) -> str:
    try:
        from engine.nexus.meta_metrics import get_meta_metrics

        return get_meta_metrics().dashboard(hours=hours)
    except Exception as e:
        return json.dumps({"error": str(e)})


def metrics_collect_all_impl() -> str:
    try:
        from engine.nexus.meta_metrics import get_meta_metrics

        return json.dumps(get_meta_metrics().collect_all(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def metrics_check_regressions_impl(threshold_pct: float = 10.0) -> str:
    try:
        from engine.nexus.meta_metrics import get_meta_metrics

        alerts = get_meta_metrics().check_regressions(threshold_pct=threshold_pct)
        return json.dumps(
            [
                {
                    "metric": a.metric_name,
                    "type": a.alert_type,
                    "message": a.message,
                    "current": a.current_value,
                    "baseline": a.baseline_value,
                }
                for a in alerts
            ],
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def metrics_snapshot_impl() -> str:
    try:
        from engine.nexus.meta_metrics import get_meta_metrics

        return json.dumps(get_meta_metrics().snapshot(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def reflection_run_impl(
    period: str = "weekly", days: int = 7, use_nlm: bool = False
) -> str:
    try:
        from engine.nexus.system_reflection import get_system_reflection

        report = get_system_reflection().run_reflection(
            period=period, days=days, use_nlm=use_nlm
        )
        return json.dumps(
            {
                "report_id": report.report_id,
                "period": report.period,
                "insight_count": len(report.insights),
                "tasks_created": len(report.tasks_created),
                "insights": [
                    {
                        "title": i.title,
                        "category": i.category,
                        "priority": i.priority,
                        "actionable": i.actionable,
                        "description": i.description[:200],
                    }
                    for i in report.insights
                ],
                "duration_seconds": report.duration_seconds,
            },
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def reflection_history_impl(limit: int = 5) -> str:
    try:
        from engine.nexus.system_reflection import get_system_reflection

        return json.dumps(get_system_reflection().get_history(limit=limit), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def reflection_latest_insights_impl(limit: int = 10) -> str:
    try:
        from engine.nexus.system_reflection import get_system_reflection

        return json.dumps(
            get_system_reflection().latest_insights(limit=limit), default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def experiment_scan_and_propose_impl() -> str:
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer

        proposals = get_experiment_proposer().scan_and_propose()
        return json.dumps(
            [
                {
                    "proposal_id": p.proposal_id,
                    "experiment_name": p.experiment_name,
                    "trigger_metric": p.trigger_metric,
                    "trigger_value": p.trigger_value,
                    "priority": p.priority,
                    "hypothesis": p.hypothesis,
                }
                for p in proposals
            ],
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def experiment_list_proposals_impl(status: str = "") -> str:
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer

        s = status if status else None
        return json.dumps(
            get_experiment_proposer().get_proposals(status=s), default=str
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


def experiment_list_templates_impl() -> str:
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer

        return json.dumps(get_experiment_proposer().list_templates(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
