import json

import pytest

from equitylayer_plugin.commands import START_TEXT, make_slash_handler
from equitylayer_plugin.profile_store import ProfileStore, describe, validate_fields


def test_save_merges_and_reads_back(tmp_path):
    store = ProfileStore(tmp_path)
    store.save({"sectors": ["optical_cpo"], "has_view": False})
    profile = store.save({"check": "weekly", "check_time": "08:30", "timezone": "Asia/Taipei"})
    assert profile["sectors"] == ["optical_cpo"] and profile["has_view"] is False
    assert store.get()["check_time"] == "08:30"
    assert describe(store.get()) == "researches CPO and optical networking; checks every Monday at 08:30 Asia/Taipei"


@pytest.mark.parametrize("fields", [
    {"sectors": ["semiconductors"]}, {"sectors": []}, {"has_view": "yes"}, {"check": "hourly"},
    {"check_time": "9am"}, {"check_time": "24:00"}, {"timezone": "Taipei; rm -rf"}, {"language": "English please"},
])
def test_rejects_anything_outside_the_shape(fields):
    with pytest.raises(ValueError):
        validate_fields(fields)


def test_damaged_file_reads_as_no_profile(tmp_path):
    (tmp_path / "profile.json").write_text("{not json")
    assert ProfileStore(tmp_path).get() is None
    (tmp_path / "profile.json").write_text(json.dumps({"check": "daily", "check_time": "late"}))
    assert ProfileStore(tmp_path).get() is None


def test_profile_tools(make_service):
    service, transport, _ = make_service()
    first = json.loads(service.el_profile_get({}))
    assert first["ok"] and first["profile"] is None and first["returning"] is False
    assert [s["id"] for s in first["sectors"]][0] == "optical_cpo"
    saved = json.loads(service.el_profile_save({"sectors": ["space_infrastructure"], "language": "zh-Hant"}))
    assert saved["ok"] and saved["profile"]["language"] == "zh-Hant"
    again = json.loads(service.el_profile_get({}))
    assert again["returning"] is True and "Space infrastructure" in again["markdown"]
    bad = json.loads(service.el_profile_save({"check": "hourly"}))
    assert bad["ok"] is False and bad["error"] == "invalid_argument"
    empty = json.loads(service.el_profile_save({}))
    assert empty["error"] == "missing_argument"
    assert transport.calls == []  # nothing goes to EquityLayer


def test_profile_save_is_refused_in_scheduled_runs(make_service):
    service, _, _ = make_service(in_cron=True)
    result = json.loads(service.el_profile_save({"sectors": ["optical_cpo"]}))
    assert result["ok"] is False and result["error"] == "not_in_scheduled_run"


def test_slash_start_and_profile(make_service):
    service, _, _ = make_service()
    handle = make_slash_handler(service)
    assert handle("start") == START_TEXT
    assert "/equitylayer:start" in handle("start")
    assert "Not set up yet" in handle("profile")
    assert "/equitylayer:start" in handle("")
