import json
from datetime import datetime, timedelta

import server.app as server_app
from server.app import calculate_machine_uptime, calculate_overall_uptime


def _entry(timestamp, status):
    return {"timestamp": timestamp.isoformat(), "status": status}


def test_unknown_periods_are_excluded_from_uptime():
    start = datetime(2026, 1, 1, 10, 0)
    end = start + timedelta(hours=1)
    entries = [
        _entry(start, "active"),
        _entry(start + timedelta(minutes=30), "unknown"),
    ]

    assert calculate_machine_uptime(entries, start, end) == 100.0


def test_all_unknown_machine_is_excluded_from_overall_uptime():
    now = datetime.now()
    history = {
        "machine_0": {
            "entries": [_entry(now - timedelta(minutes=30), "active")]
        },
        "machine_1": {
            "entries": [_entry(now - timedelta(minutes=30), "unknown")]
        },
    }

    overall, machines = calculate_overall_uptime(history, hours_back=1)

    assert overall == 100.0
    assert machines["machine_1"] is None


def test_first_transition_does_not_backfill_unknown_time():
    start = datetime(2026, 1, 1, 10, 0)
    end = start + timedelta(hours=1)
    entries = [
        _entry(start + timedelta(minutes=30), "active"),
        _entry(start + timedelta(minutes=45), "inactive"),
    ]

    assert calculate_machine_uptime(entries, start, end) == 50.0


def test_stats_defaults_include_unknown_safe_uptime_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "HISTORY_FILE", tmp_path / "missing.json")

    response = server_app.app.test_client().get("/api/stats")
    data = response.get_json()

    assert data["overall_uptime_1h"] is None
    assert data["machine_uptimes_1h"] == {}
    assert data["unknown_machines"] == 0


def test_dashboard_rejects_malformed_detection_boxes(tmp_path, monkeypatch):
    config_path = tmp_path / "web_ui.config.py"
    monkeypatch.setattr(server_app, "WEB_UI_CONFIG_FILE", config_path)

    assert not server_app.save_web_ui_config([[20, 10, 5, 30]])
    assert not config_path.exists()


def test_trusted_active_and_inactive_periods_determine_uptime():
    start = datetime(2026, 1, 1, 10, 0)
    end = start + timedelta(hours=1)
    entries = [
        _entry(start, "active"),
        _entry(start + timedelta(minutes=30), "inactive"),
    ]

    assert calculate_machine_uptime(entries, start, end) == 50.0


def test_hourly_activity_returns_24_buckets_and_preserves_partial_hours():
    now = datetime(2026, 1, 1, 12, 34)
    entries = [
        _entry(datetime(2026, 1, 1, 11, 0), "active"),
        _entry(datetime(2026, 1, 1, 11, 30), "inactive"),
        _entry(datetime(2026, 1, 1, 12, 15), "active"),
    ]

    activity = server_app.generate_hourly_activity(
        {"machine_0": {"entries": entries}}, now=now
    )["machine_0"]

    assert len(activity) == 24
    assert activity[-1]["is_current_hour"] is True
    assert activity[-2]["activity_percentage"] == 50.0
    assert activity[-1]["activity_percentage"] == 55.9


def test_stats_cache_reuses_snapshot_and_invalidates_on_history_change(tmp_path, monkeypatch):
    history_path = tmp_path / "machine_history.json"
    now = datetime.now()
    history_path.write_text(json.dumps({
        "machine_0": {"entries": [_entry(now - timedelta(minutes=5), "active")]}
    }))
    monkeypatch.setattr(server_app, "HISTORY_FILE", history_path)

    calls = []
    original_build_stats = server_app._build_stats

    def tracked_build_stats(history_data, now=None):
        calls.append(history_data)
        return original_build_stats(history_data, now=now)

    monkeypatch.setattr(server_app, "_build_stats", tracked_build_stats)
    client = server_app.app.test_client()

    first = client.get("/api/stats").get_json()
    second = client.get("/api/stats").get_json()
    assert first["active_machines"] == second["active_machines"] == 1
    assert len(calls) == 1

    history_path.write_text(json.dumps({
        "machine_0": {"entries": [_entry(now - timedelta(minutes=5), "inactive")]}
    }))
    changed = client.get("/api/stats").get_json()
    assert changed["inactive_machines"] == 1
    assert changed["active_machines"] == 0
    assert len(calls) == 2


def test_stats_handles_malformed_history_gracefully(tmp_path, monkeypatch):
    history_path = tmp_path / "machine_history.json"
    history_path.write_text("not valid json")
    monkeypatch.setattr(server_app, "HISTORY_FILE", history_path)

    response = server_app.app.test_client().get("/api/stats")
    data = response.get_json()

    assert response.status_code == 200
    assert data["error"].startswith("Unable to load machine history:")
    assert data["hourly_activity"] == {}
