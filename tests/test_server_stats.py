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
