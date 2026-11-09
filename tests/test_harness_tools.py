import copy
import json
from pathlib import Path

import pytest

from equitylayer_plugin import commands
from equitylayer_plugin.harness_tools import lint_harness

HARNESS = json.loads((Path(__file__).parent / "harness_demo.json").read_text())["harness"]
THESIS = "Co-packaged optics reaches volume by end-2027 and suppliers show it first."


def call(handler, args=None, **kwargs):
    raw = handler(args, **kwargs)
    assert isinstance(raw, str)
    return json.loads(raw)


def harness_store(service):
    return service._harness_store_factory()


def test_plan_sends_only_the_thesis_and_stores_nothing(make_service, tmp_path):
    service, transport, _ = make_service({"plan_thesis_tracking": "plan_cpo"})
    result = call(service.el_plan_thesis, {"thesis_text": THESIS, "theme_id": "optical_cpo",
                                           "keywords": "revenue, laser"})
    assert result["ok"] and result["stored"] is False
    assert transport.calls == [("plan_thesis_tracking", {"thesis_text": THESIS, "theme_id": "optical_cpo",
                                                         "keywords": ["revenue", "laser"]})]
    assert len(result["candidates"]) == 24
    assert not (tmp_path / "harnesses").exists()


def test_plan_needs_a_real_sentence(make_service):
    service, transport, _ = make_service()
    assert call(service.el_plan_thesis, {"thesis_text": "CPO"})["error"] == "missing_argument"
    assert transport.calls == []


def test_get_variable_uses_the_full_route_of_the_configured_server(make_service):
    service, transport, _ = make_service({"get_variable": "get_variable_foci"},
                                         {"mcp_url": "http://localhost:3420/mcp"})
    result = call(service.el_get_variable, {"variable": "v:3363.two.revenue.monthly"})
    assert result["ok"] and result["unit"] == "TWD thousand"
    assert transport.paths == ["/mcp/full"]
    assert call(service.el_get_variable, {"variable": "3363"})["error"] == "missing_argument"


def test_save_validates_with_equitylayer_then_stores_locally(make_service):
    service, transport, _ = make_service({"check_thesis_harness": "check_harness_first"})
    result = call(service.el_harness_save, {"harness": HARNESS})
    assert result["ok"] and result["validated"] and result["created"]
    assert result["harness_id"] == "cpo-reaches-volume-by-end-2027"
    assert transport.calls == [("check_thesis_harness", {"harness": HARNESS})]
    assert harness_store(service).get(result["harness_id"])["harness"] == HARNESS


def test_save_refuses_a_harness_equitylayer_cannot_read(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_invalid"})
    result = call(service.el_harness_save, {"harness": HARNESS})
    assert result["error"] == "invalid_harness"
    assert "harness.why" in result["problems"][0]
    assert harness_store(service).all() == ([], [])


def test_save_keeps_the_harness_when_offline_but_says_so(make_service):
    service, _, _ = make_service({"check_thesis_harness": 503})
    result = call(service.el_harness_save, {"harness": HARNESS})
    assert result["ok"] and result["validated"] is False
    assert any("could not be reached" in w for w in result["warnings"])


def test_save_missing_parts_never_calls_the_network(make_service):
    service, transport, _ = make_service()
    broken = {k: v for k, v in HARNESS.items() if k != "wrong_if"}
    result = call(service.el_harness_save, {"harness": broken})
    assert result["error"] == "invalid_harness" and "`wrong_if` is missing." in result["problems"]
    assert call(service.el_harness_save, {"harness": "text"})["error"] == "invalid_harness"
    assert transport.calls == []


def test_update_requires_an_existing_id(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_first"})
    assert call(service.el_harness_save, {"harness": HARNESS, "harness_id": "nope"})["error"] == "unknown_harness"
    first = call(service.el_harness_save, {"harness": HARNESS})
    edited = {**HARNESS, "why": "New reasoning."}
    second = call(service.el_harness_save, {"harness": edited, "harness_id": first["harness_id"]})
    assert second["ok"] and second["created"] is False
    assert len(harness_store(service).all()[0]) == 1


def test_lint_warnings():
    risky = copy.deepcopy(HARNESS)
    risky["hypothesis"] = "Should I buy CPO suppliers?"
    risky["tracking"][0]["rules"] = []
    risky["wrong_if"] = []
    errors, warnings = lint_harness(risky, known_ids={"v:3363.two.revenue.monthly"})
    assert errors == []
    text = " ".join(warnings)
    assert "is a question" in text
    assert "never computed here" in text
    assert "Link `foci-ramp` has no rules" in text
    assert "not in the last plan" in text and "v:cohr.us" in text
    assert "nothing could show the thesis is wrong" in text
    assert lint_harness(HARNESS) == ([], [])


def test_model_check_keeps_baseline_pending_until_the_person_reads_it(make_service):
    routes = {"check_thesis_harness": ["check_harness_first", "check_harness_first", "check_harness_changed"]}
    service, transport, _ = make_service(routes)
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    result = call(service.el_harness_check, {"harness_id": hid})
    assert result["checked"][0]["baseline_saved"] is False
    assert result["needs_human_total"] == 1
    assert "Not saved as your baseline yet" in result["markdown"]
    record = harness_store(service).get(hid)
    assert record["baseline"] is None and record["pending_baseline"]
    seen = call(service.el_harness_seen, {"harness_id": hid})
    assert seen["ok"] and seen["baseline_taken_at"] == "2026-11-09"
    # The next check sends the baseline the person accepted.
    call(service.el_harness_check, {"harness_id": hid})
    assert transport.calls[-1][1]["baseline"]["taken_at"] == "2026-11-09"
    # The changed check is pending again until read.
    assert harness_store(service).get(hid)["pending_baseline"]["taken_at"] == "2026-11-09"


def test_seen_is_refused_in_scheduled_runs(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_first"}, in_cron=True)
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    call(service.el_harness_check, {"harness_id": hid})
    assert call(service.el_harness_seen, {"harness_id": hid})["error"] == "person_required"
    assert harness_store(service).get(hid)["baseline"] is None


def test_due_run_skips_unread_and_not_due_harnesses(make_service):
    service, transport, _ = make_service({"check_thesis_harness": "check_harness_first"}, in_cron=True)
    store = harness_store(service)
    store.save_harness("never-checked", HARNESS)
    store.save_harness("unread", HARNESS)
    store.record_check("unread", {"links": [], "next_baseline": {"taken_at": "2026-11-09"}}, seen=False)
    store.save_harness("later", HARNESS)
    later = store.get("later")
    later["last_check"] = {"next_due": "2099-01-01"}
    store._write(store._path("later"), later)
    result = call(service.el_harness_check, {})
    assert [c["harness_id"] for c in result["checked"]] == ["never-checked"]
    assert result["awaiting_read"] == ["unread"]
    assert "Still waiting for you to read" in result["markdown"]
    assert len(transport.calls) == 1


def test_due_run_with_nothing_due_is_silent_and_offline(make_service):
    service, transport, _ = make_service()
    result = call(service.el_harness_check, {})
    assert result["checked"] == [] and result["needs_human_total"] == 0 and result["errors"] == 0
    assert transport.calls == []


def test_failed_check_changes_nothing_locally(make_service):
    service, _, _ = make_service({"check_thesis_harness": ["check_harness_first", 503, 503]})
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    result = call(service.el_harness_check, {"harness_id": hid})
    assert result["errors"] == 1 and "Nothing was changed locally" in result["markdown"]
    assert harness_store(service).get(hid)["last_check"] is None


def test_draft_check_is_not_stored(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_problems"})
    result = call(service.el_harness_check, {"harness": HARNESS})
    assert result["stored"] is False and result["problems"]
    assert harness_store(service).all() == ([], [])


def test_list_and_open_one(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_first"})
    assert "No thesis harness saved yet" in call(service.el_harness_list)["markdown"]
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    listing = call(service.el_harness_list)
    assert listing["count"] == 1 and listing["harnesses"][0]["state"] == "due"
    one = call(service.el_harness_list, {"harness_id": hid})
    assert one["record"]["harness"] == HARNESS and "**Hypothesis:**" in one["markdown"]
    assert call(service.el_harness_list, {"harness_id": "nope"})["error"] == "unknown_harness"


def test_slash_flow_for_your_own_thesis(make_service):
    routes = {
        "list_registry": "list_registry_empty",
        "plan_thesis_tracking": "plan_cpo",
        "get_variable": "get_variable_foci",
        "check_thesis_harness": ["check_harness_first", "check_harness_first", "check_harness_changed"],
    }
    service, transport, _ = make_service(routes)
    el = commands.make_slash_handler(service)
    assert "No Research Pack is published right now" in el("registry")
    plan = el(f"plan --theme optical_cpo --company 3363.TWO {THESIS}")
    assert "Variables you could track" in plan
    assert transport.calls[-1] == ("plan_thesis_tracking", {"thesis_text": THESIS, "theme_id": "optical_cpo",
                                                            "entities": ["3363.TWO"]})
    assert "Usage" in el("plan --theme optical_cpo")
    assert "224,257" in el("var v:3363.two.revenue.monthly")
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    assert hid in el("theses")
    # A slash check is read by the person directly, so it becomes the baseline.
    first = el(f"check {hid}")
    assert "Baseline saved locally" in first
    assert harness_store(service).get(hid)["baseline"]["taken_at"] == "2026-11-09"
    changed = el(f"check {hid}")
    assert "+9.67%" in changed
    assert "nothing_pending" in el(f"seen {hid}")
    assert "**Hypothesis:**" in el(f"show {hid}")
    assert "Removed" in el(f"remove {hid}")
    assert "unknown_harness" in el(f"show {hid}")
    assert "thesis-check" in el("schedule 07:15 Asia/Taipei")
    assert "Usage" in el("schedule 99:99")


def test_slash_check_in_a_scheduled_context_does_not_mark_read(make_service):
    service, _, _ = make_service({"check_thesis_harness": "check_harness_first"}, in_cron=True)
    el = commands.make_slash_handler(service)
    hid = call(service.el_harness_save, {"harness": HARNESS})["harness_id"]
    el(f"check {hid}")
    assert harness_store(service).get(hid)["baseline"] is None
