"""One tracked object, three levels: the nine tools the model sees."""

import json
from pathlib import Path

ROUTES = {
    "get_variable": "get_variable_foci",
    "list_research_events": "list_research_events_foci",
    "list_upcoming_triggers": "list_upcoming_triggers_cpo",
    "check_thesis_harness": "check_harness_first",
    "list_registry": "list_registry_empty",
    "create_research_follow": "create_follow_pack",
}
FOCI = "v:3363.two.revenue.monthly"
HARNESS = json.loads((Path(__file__).parent / "harness_demo.json").read_text())["harness"]


def call(tool, args=None):
    return json.loads(tool(args or {}))


def test_track_readings_then_check_seen_and_list(make_service):
    service, _, _ = make_service(ROUTES)
    saved = call(service.el_track, {"title": "CPO curated readings", "variables": [FOCI], "theme": "optical_cpo"})
    assert saved["ok"] and saved["level"] == "readings" and saved["item_id"] == "cpo-curated-readings"
    first = call(service.el_check)
    assert first["report_total"] == 1 and first["awaiting_read"] == ["cpo-curated-readings"]
    assert call(service.el_seen, {"item_id": "cpo-curated-readings"})["ok"]
    assert call(service.el_check)["report_total"] == 0
    listed = call(service.el_list)
    assert [(i["id"], i["level"]) for i in listed["items"]] == [("cpo-curated-readings", "readings")]


def test_adding_a_thesis_upgrades_the_same_item(make_service, tmp_path):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI], "theme": "optical_cpo"})
    upgraded = call(service.el_track, {"item_id": "cpo-readings", "harness": HARNESS})
    assert upgraded["ok"] and upgraded["item_id"] == "cpo-readings" and upgraded["level"] == "your thesis"
    assert upgraded["upgraded_from"] == "readings" and "now carry your thesis" in upgraded["markdown"]
    assert not (tmp_path / "watchlists" / "cpo-readings.json").exists()
    assert (tmp_path / "harnesses" / "cpo-readings.json").exists()
    assert [i["level"] for i in call(service.el_list)["items"]] == ["your thesis"]


def test_ids_never_clash_across_levels(make_service):
    service, _, _ = make_service(ROUTES)
    a = call(service.el_track, {"title": HARNESS["title"], "variables": [FOCI]})
    b = call(service.el_track, {"harness": HARNESS})
    assert a["item_id"] != b["item_id"] and b["item_id"].startswith(a["item_id"])


def test_one_check_covers_every_level(make_service):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI]})
    call(service.el_track, {"harness": HARNESS})
    result = call(service.el_check)
    assert result["report_total"] == 2 and len(result["awaiting_read"]) == 2
    assert "Watchlist: CPO readings" in result["markdown"] and "---" in result["markdown"]


def test_unknown_ids_and_missing_input_are_explained(make_service):
    service, _, _ = make_service(ROUTES)
    assert call(service.el_seen, {"item_id": "nope"})["error"] == "unknown_item"
    assert call(service.el_check, {"item_id": "nope"})["error"] == "unknown_item"
    assert call(service.el_track, {"item_id": "nope", "variables": [FOCI]})["error"] == "unknown_item"
    assert call(service.el_track, {})["error"] == "missing_argument"
    assert "don't track anything yet" in call(service.el_check)["markdown"]


def test_scheduled_runs_never_mark_read(make_service):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI]})
    cron, _, _ = make_service(ROUTES, in_cron=True)
    assert call(cron.el_seen, {"item_id": "cpo-readings"})["ok"] is False


def test_profile_and_research_pack_and_follow(make_service):
    service, transport, _ = make_service(ROUTES)
    assert call(service.el_profile)["profile"] is None
    assert call(service.el_profile, {"sectors": ["optical_cpo"]})["profile"]["sectors"] == ["optical_cpo"]
    assert "No Research Pack is published" in call(service.el_research_pack, {"action": "list"})["markdown"]
    assert call(service.el_research_pack, {"action": "buy"})["error"] == "invalid_argument"
    followed = call(service.el_track, {"pack_id": "ai-compute-pcb-ccl-value-capture"})
    assert followed["ok"] and followed["level"] == "EquityLayer thesis" and followed["item_id"].startswith("follow_")
    assert "EquityLayer thesis" in [i["level"] for i in call(service.el_list)["items"]]
