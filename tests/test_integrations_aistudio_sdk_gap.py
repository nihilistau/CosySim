"""Tests for SDK gap methods added to engine.integrations.aistudio_client.

Covers all new MakerSuiteService methods (HAR 2026-03-05 + bulk implementation).
All network calls are mocked — no real HTTP traffic.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.integrations.aistudio_client import AIStudioClient, get_aistudio_client


# ──── Fixtures ────────────────────────────────────────────────────────────────

FAKE_COOKIES = {"SAPISID": "test_sapisid", "SID": "test_sid"}


@pytest.fixture
def client() -> AIStudioClient:
    """AIStudioClient with fake cookies — no real HTTP."""
    return AIStudioClient(cookies=FAKE_COOKIES)


def _mock_post(client: AIStudioClient, response: dict) -> MagicMock:
    """Patch _post_safe to return a fixed response dict."""
    m = MagicMock(return_value=response)
    client._post_safe = m  # type: ignore[method-assign]
    return m


# ──── Code Assistant ──────────────────────────────────────────────────────────

def test_code_assistant_offline_calls_correct_method(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"result": "ok"})
    req = {"prompt": "def foo():", "language": "python"}
    result = client.code_assistant_offline(req)
    assert result == {"result": "ok"}
    mock.assert_called_once_with("CodeAssistantOffline", req)


def test_stream_code_assistant_offline_upload(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"ack": True})
    result = client.stream_code_assistant_offline_upload("gen-123", b"\x00\x01\x02")
    assert result["ack"] is True
    call_args = mock.call_args[0]
    assert call_args[0] == "StreamCodeAssistantOfflineGenerationUpload"
    assert call_args[1]["generationId"] == "gen-123"
    assert call_args[1]["chunk"] == "000102"  # hex of b"\x00\x01\x02"


def test_get_code_assistant_snapshot(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"snapshotId": "snap-456", "data": {}})
    result = client.get_code_assistant_snapshot("snap-456")
    assert result["snapshotId"] == "snap-456"
    mock.assert_called_once_with("GetCodeAssistantSnapshot", {"snapshotId": "snap-456"})


def test_load_code_assistant_interaction_history(client: AIStudioClient) -> None:
    interactions = [{"id": "i1"}, {"id": "i2"}]
    _mock_post(client, {"interactions": interactions})
    result = client.load_code_assistant_interaction_history("sess-99")
    assert result == {"interactions": interactions}


def test_list_code_assistant_configurations(client: AIStudioClient) -> None:
    configs = [{"id": "cfg-1", "name": "default"}]
    _mock_post(client, {"configurations": configs})
    result = client.list_code_assistant_configurations()
    assert result == configs


def test_list_code_assistant_features(client: AIStudioClient) -> None:
    features = [{"name": "inline_complete", "enabled": True}]
    _mock_post(client, {"features": features})
    result = client.list_code_assistant_features()
    assert result == features


def test_list_code_assistant_offline_generations(client: AIStudioClient) -> None:
    gens = [{"id": "g1"}, {"id": "g2"}]
    _mock_post(client, {"generations": gens})
    result = client.list_code_assistant_offline_generations(page_size=10)
    assert result == gens


def test_list_code_gen_suggestion_cards(client: AIStudioClient) -> None:
    cards = [{"title": "Fix bug", "prompt": "Fix the error in this code"}]
    _mock_post(client, {"cards": cards})
    result = client.list_code_gen_suggestion_cards(context="bugfix")
    assert result == cards


def test_generate_code_assistant_suggestion_chips(client: AIStudioClient) -> None:
    chips = ["Explain this", "Refactor", "Add tests"]
    _mock_post(client, {"chips": chips})
    result = client.generate_code_assistant_suggestion_chips("write a sort function")
    assert result == chips


# ──── Applet management ────────────────────────────────────────────────────────

def test_list_recent_applets(client: AIStudioClient) -> None:
    applets = [{"name": "applets/abc"}, {"name": "applets/def"}]
    _mock_post(client, {"applets": applets})
    result = client.list_recent_applets(limit=5)
    assert result == applets


def test_store_recent_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"stored": True})
    result = client.store_recent_applet("applets/xyz")
    assert result["stored"] is True
    mock.assert_called_once_with("StoreRecentApplet", {"appletName": "applets/xyz"})


def test_save_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "applets/xyz", "version": 2})
    result = client.save_applet("applets/xyz", {"displayName": "My App"})
    assert result["version"] == 2
    mock.assert_called_once_with(
        "SaveApplet",
        {"appletName": "applets/xyz", "updates": {"displayName": "My App"}},
    )


def test_list_unset_applet_secrets(client: AIStudioClient) -> None:
    _mock_post(client, {"secretKeys": ["API_KEY", "DB_PASS"]})
    result = client.list_unset_applet_secrets("applets/xyz")
    assert result == ["API_KEY", "DB_PASS"]


def test_provision_and_initialize_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"status": "PROVISIONED"})
    config = {"displayName": "test app", "template": "blank"}
    result = client.provision_and_initialize_applet(config)
    assert result["status"] == "PROVISIONED"
    mock.assert_called_once_with("ProvisionAndInitializeApplet", config)


# ──── Projects & billing ──────────────────────────────────────────────────────

def test_list_imported_projects(client: AIStudioClient) -> None:
    projects = [{"projectId": "proj-123", "displayName": "My Project"}]
    _mock_post(client, {"projects": projects})
    result = client.list_imported_projects()
    assert result == projects


def test_list_promos(client: AIStudioClient) -> None:
    promos = [{"promoId": "TRIAL", "credits": 300}]
    _mock_post(client, {"promos": promos})
    result = client.list_promos()
    assert result == promos


# ──── Logging / metrics ───────────────────────────────────────────────────────

def test_log_event_calls_correct_method(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.log_event("page_view", {"page": "/home"})
    mock.assert_called_once_with("Log", {"eventType": "page_view", "payload": {"page": "/home"}})


def test_log_event_without_payload(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.log_event("session_start")
    call_body = mock.call_args[0][1]
    assert "payload" not in call_body
    assert call_body["eventType"] == "session_start"


def test_fetch_metric_time_series(client: AIStudioClient) -> None:
    data_points = [{"timestamp": "2026-03-05T00:00:00Z", "value": 42}]
    mock = _mock_post(client, {"dataPoints": data_points})
    result = client.fetch_metric_time_series(
        "token_count",
        start_time="2026-03-04T00:00:00Z",
        granularity="DAY",
    )
    assert result == data_points
    call_body = mock.call_args[0][1]
    assert call_body["metricName"] == "token_count"
    assert call_body["granularity"] == "DAY"
    assert call_body["startTime"] == "2026-03-04T00:00:00Z"


def test_fetch_metric_time_series_defaults(client: AIStudioClient) -> None:
    _mock_post(client, {"dataPoints": []})
    result = client.fetch_metric_time_series("request_count")
    assert result == []


# ──── Singleton ───────────────────────────────────────────────────────────────

def test_get_aistudio_client_returns_instance() -> None:
    import engine.integrations.aistudio_client as _mod
    _mod._client = None
    with patch(
        "engine.integrations.google_account_pool.get_account_pool",
        side_effect=ImportError,
    ):
        c = get_aistudio_client(cookies=FAKE_COOKIES)
    _mod._client = None  # reset singleton
    assert isinstance(c, AIStudioClient)


# ──── Bulk methods (89 SDK gap fill) ─────────────────────────────────────────

def test_log_alias_delegates_to_log_event(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.log("test_event", {"k": "v"})
    mock.assert_called_once_with("Log", {"eventType": "test_event", "payload": {"k": "v"}})


def test_stream_code_assistant_offline_generation_upload_alias(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"ack": True})
    result = client.stream_code_assistant_offline_generation_upload("gen-1", b"\xff")
    assert result["ack"] is True
    assert mock.call_args[0][0] == "StreamCodeAssistantOfflineGenerationUpload"


# ── Applets (extended) ──

def test_update_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"appletId": "a1", "displayName": "new"})
    result = client.update_applet("a1", {"displayName": "new"})
    assert result["displayName"] == "new"
    assert mock.call_args[0][0] == "UpdateApplet"


def test_delete_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.delete_applet("a1")
    mock.assert_called_once_with("DeleteApplet", {"appletId": "a1"})


def test_clone_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"appletId": "a2"})
    client.clone_applet("a1", "Clone")
    assert mock.call_args[0][1]["displayName"] == "Clone"


def test_undeploy_applet(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.undeploy_applet("a1")
    mock.assert_called_once_with("UndeployApplet", {"appletId": "a1"})


# ── Apps ──

def test_create_app(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "apps/x"})
    client.create_app("MyApp", {"model": "gemini-2.5-flash"})
    assert mock.call_args[0][0] == "CreateApp"


def test_get_app(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "apps/x"})
    client.get_app("apps/x")
    mock.assert_called_once_with("GetApp", {"appName": "apps/x"})


def test_list_apps(client: AIStudioClient) -> None:
    _mock_post(client, {"apps": [{"name": "apps/x"}]})
    result = client.list_apps()
    assert result == [{"name": "apps/x"}]


def test_update_app(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.update_app("apps/x", {"displayName": "Updated"})
    assert mock.call_args[0][0] == "UpdateApp"


def test_delete_app(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.delete_app("apps/x")
    mock.assert_called_once_with("DeleteApp", {"appName": "apps/x"})


# ── Batch jobs ──

def test_create_batch_job(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "jobs/j1", "state": "PENDING"})
    result = client.create_batch_job("gemini-2.5-flash", "gs://bucket/input.jsonl")
    assert result["state"] == "PENDING"
    assert mock.call_args[0][0] == "CreateBatchJob"


def test_get_batch_job(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "jobs/j1", "state": "SUCCEEDED"})
    result = client.get_batch_job("jobs/j1")
    assert result["state"] == "SUCCEEDED"
    mock.assert_called_once_with("GetBatchJob", {"jobName": "jobs/j1"})


def test_list_batch_jobs(client: AIStudioClient) -> None:
    _mock_post(client, {"jobs": [{"name": "jobs/j1"}]})
    assert client.list_batch_jobs() == [{"name": "jobs/j1"}]


def test_cancel_batch_job(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.cancel_batch_job("jobs/j1")
    mock.assert_called_once_with("CancelBatchJob", {"jobName": "jobs/j1"})


# ── Safety ──

def test_check_safety(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"blocked": False, "safetyRatings": []})
    result = client.check_safety("Hello world")
    assert result["blocked"] is False
    assert mock.call_args[0][1]["text"] == "Hello world"


def test_get_safety_settings(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"categories": []})
    client.get_safety_settings()
    mock.assert_called_once_with("GetSafetySettings", {})


def test_update_safety_settings(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.update_safety_settings({"HARM_CATEGORY_HATE_SPEECH": "BLOCK_LOW_AND_ABOVE"})
    assert mock.call_args[0][0] == "UpdateSafetySettings"


# ── Notifications ──

def test_list_notifications(client: AIStudioClient) -> None:
    _mock_post(client, {"notifications": [{"id": "n1", "title": "Update"}]})
    result = client.list_notifications()
    assert result[0]["title"] == "Update"


def test_mark_notification_read(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.mark_notification_read("n1")
    mock.assert_called_once_with("MarkNotificationRead", {"notificationId": "n1"})


def test_dismiss_notification(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.dismiss_notification("n1")
    mock.assert_called_once_with("DismissNotification", {"notificationId": "n1"})


# ── Prompts (extended) ──

def test_get_prompt(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "prompts/p1", "text": "Hello"})
    result = client.get_prompt("prompts/p1")
    assert result["text"] == "Hello"
    mock.assert_called_once_with("GetPrompt", {"promptName": "prompts/p1"})


def test_update_prompt(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "prompts/p1"})
    client.update_prompt("prompts/p1", {"displayName": "Updated"})
    assert mock.call_args[0][0] == "UpdatePrompt"


def test_delete_prompt(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.delete_prompt("prompts/p1")
    mock.assert_called_once_with("DeletePrompt", {"promptName": "prompts/p1"})


# ── Sharing ──

def test_share_prompt(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"sharedWith": ["bob@example.com"]})
    client.share_prompt("prompts/p1", ["bob@example.com"])
    assert mock.call_args[0][1]["shareWith"] == ["bob@example.com"]


def test_get_shared_prompt(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"shareId": "abc123"})
    client.get_shared_prompt("abc123")
    mock.assert_called_once_with("GetSharedPrompt", {"shareId": "abc123"})


def test_list_shared_prompts(client: AIStudioClient) -> None:
    _mock_post(client, {"sharedPrompts": [{"shareId": "s1"}]})
    result = client.list_shared_prompts()
    assert result == [{"shareId": "s1"}]


# ── User settings ──

def test_get_user_settings(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"theme": "dark"})
    result = client.get_user_settings()
    assert result["theme"] == "dark"
    mock.assert_called_once_with("GetUserSettings", {})


def test_update_user_settings(client: AIStudioClient) -> None:
    mock = _mock_post(client, {})
    client.update_user_settings({"theme": "light"})
    assert mock.call_args[0][1]["theme"] == "light"


def test_get_usage_metadata(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"tokenUsage": 1000})
    result = client.get_usage_metadata()
    assert result["tokenUsage"] == 1000
    mock.assert_called_once_with("GetUsageMetadata", {})


# ── Infrastructure ──

def test_check_quota(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"available": True})
    result = client.check_quota("gemini-2.5-flash")
    assert result["available"] is True
    assert mock.call_args[0][1]["model"] == "gemini-2.5-flash"


def test_check_quota_global(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"available": True})
    client.check_quota()
    assert mock.call_args[0][1] == {}


def test_get_billing_info(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"credits": 300})
    result = client.get_billing_info()
    assert result["credits"] == 300
    mock.assert_called_once_with("GetBillingInfo", {})


def test_create_cloud_project(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"projectId": "proj-abc"})
    result = client.create_cloud_project("Test Project")
    assert result["projectId"] == "proj-abc"
    assert mock.call_args[0][0] == "CreateCloudProject"


# ── GitHub integration ──

def test_create_git_hub_repository(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"repoUrl": "https://github.com/user/repo"})
    result = client.create_git_hub_repository("app-1", "my-repo")
    assert "repoUrl" in result
    assert mock.call_args[0][1]["repoName"] == "my-repo"


def test_get_git_hub_repository(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"repoUrl": "https://github.com/user/repo"})
    client.get_git_hub_repository("app-1")
    mock.assert_called_once_with("GetGitHubRepository", {"appletId": "app-1"})


def test_sync_git_hub_repository(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"status": "SYNCED"})
    result = client.sync_git_hub_repository("app-1")
    assert result["status"] == "SYNCED"


# ── Model cards ──

def test_get_model_card(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"model": "gemini-2.5-flash", "description": "..."})
    client.get_model_card("gemini-2.5-flash")
    mock.assert_called_once_with("GetModelCard", {"model": "gemini-2.5-flash"})


def test_list_model_cards(client: AIStudioClient) -> None:
    _mock_post(client, {"modelCards": [{"model": "gemini-2.5-flash"}]})
    result = client.list_model_cards()
    assert result == [{"model": "gemini-2.5-flash"}]


def test_get_model_capabilities(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"supportsStreaming": True})
    result = client.get_model_capabilities("gemini-2.5-flash")
    assert result["supportsStreaming"] is True


# ── Datasets ──

def test_create_dataset(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"name": "datasets/d1"})
    client.create_dataset("My Dataset", "test data")
    assert mock.call_args[0][0] == "CreateDataset"


def test_list_datasets(client: AIStudioClient) -> None:
    _mock_post(client, {"datasets": [{"name": "datasets/d1"}]})
    assert client.list_datasets() == [{"name": "datasets/d1"}]


def test_import_dataset_items(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"imported": 5})
    client.import_dataset_items("datasets/d1", [{"input": "x", "output": "y"}])
    assert mock.call_args[0][0] == "ImportDatasetItems"
    assert mock.call_args[0][1]["datasetName"] == "datasets/d1"


def test_annotate_dataset(client: AIStudioClient) -> None:
    mock = _mock_post(client, {"operationName": "ops/1"})
    client.annotate_dataset("datasets/d1", {"annotationType": "CLASSIFICATION"})
    assert mock.call_args[0][0] == "AnnotateDataset"


# ── Tuned models ──

def test_get_model_card_returns_dict(client: AIStudioClient) -> None:
    _mock_post(client, {"model": "gemini-2.5-flash"})
    result = client.get_model_card("gemini-2.5-flash")
    assert isinstance(result, dict)


def test_speech_to_text_returns_string(client: AIStudioClient) -> None:
    _mock_post(client, {"transcript": "Hello world"})
    result = client.gemini_speech_to_text(b"audio-bytes", "en-US")
    assert result == "Hello world"


def test_speech_to_text_empty_on_error(client: AIStudioClient) -> None:
    _mock_post(client, {})
    result = client.gemini_speech_to_text(b"bad-audio")
    assert result == ""
