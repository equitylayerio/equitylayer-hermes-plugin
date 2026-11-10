import json

import pytest

from equitylayer_plugin import commands
from equitylayer_plugin.follows import build_record

VIEW = "el-ai-compute-tw-materials-continuation"
PACK = "tw-monthly-revenue"


def call(handler, args=None, **kwargs):
    raw = handler(args, **kwargs)
    assert isinstance(raw, str)
    return json.loads(raw)


def test_registry_marks_non_public_rows_locked_without_fetching(make_service):
    service, transport, _ = make_service({"list_registry": "list_registry"})
    result = call(service.el_list_registry)
    assert result["ok"]
    assert all(e["locked"] is False for e in result["entries"])
    assert "tw-monthly-revenue" in result["markdown"]
    assert transport.names() == ["list_registry"]


def test_locked_registry_entry_is_refused_without_a_network_call(make_service):
    service, transport, _ = make_service({"get_research_pack": "get_research_pack"})
    service._locked_ids = {"gated-pack"}
    result = call(service.el_get_pack, {"pack_id": "gated-pack"})
    assert result["error"] == "entitlement_or_payment_required"
    assert transport.calls == []


def test_get_pack_markdown_and_json(make_service):
    service, _, _ = make_service({"get_research_pack": "get_research_pack"})
    markdown = call(service.el_get_pack, {"pack_id": PACK})
    assert "Taiwan Stock Exchange" in markdown["markdown"]
    assert "Taiwan Stock Exchange" in markdown["source_attribution"]
    raw = call(service.el_get_pack, {"pack_id": PACK, "format": "json"})
    assert raw["pack"]["records"][0]["symbol"] == "2383.TW"


@pytest.mark.parametrize(
    "handler,args,argument",
    [("el_get_pack", {}, "pack_id"), ("el_scorecard", {}, "id"), ("el_get_pack", {"pack_id": "  "}, "pack_id")],
)
def test_missing_argument_is_a_json_error(make_service, handler, args, argument):
    service, transport, _ = make_service()
    result = call(getattr(service, handler), args)
    assert result == {
        "ok": False,
        "error": "missing_argument",
        "argument": argument,
        "message": f"Provide {argument}.",
    }
    assert transport.calls == []


def test_handlers_never_raise_on_bad_input(make_service):
    service, _, _ = make_service()
    assert call(service.el_get_pack, None)["ok"] is False
    assert call(service.el_follow_check, {"follow_id": "../../x"})["error"] == "invalid_argument"
    assert call(service.el_harness_check, {"harness_id": "../../x"})["error"] == "invalid_argument"


def test_entitlement_error_shape(make_service):
    service, _, _ = make_service({"get_research_pack": "entitlement_brief_shape"})
    result = call(service.el_get_pack, {"pack_id": "ai-compute-pcb-ccl-value-capture"})
    assert result == {
        "ok": False,
        "error": "entitlement_or_payment_required",
        "upstream_error": "agent_authentication_required",
        "hint": "This plugin holds no credential and never pays. Use public research or your own thesis harness.",
        "pricing_url": "https://equitylayer.io/pricing",
        "pack_id": "ai-compute-pcb-ccl-value-capture",
    }


def test_http_402_never_pays(make_service):
    service, transport, _ = make_service({"get_research_pack": 402})
    result = call(service.el_get_pack, {"pack_id": PACK})
    assert result["error"] == "entitlement_or_payment_required"
    assert "never pays" in result["hint"]
    assert len(transport.calls) == 1


def test_live_unavailable_error_gets_a_registry_hint(make_service):
    service, _, _ = make_service({"get_research_pack": "get_research_pack_unavailable"})
    result = call(service.el_get_pack, {"pack_id": "ai-compute-pcb-ccl-value-capture"})
    assert result["error"] == "research_pack_unavailable"
    assert "el_research_pack" in result["hint"]


def test_other_hosts_are_refused_without_a_call(make_service):
    service, transport, _ = make_service({}, {"mcp_url": "https://evil.example/mcp"})
    assert call(service.el_list_registry)["error"] == "invalid_mcp_url"
    assert transport.calls == []


def test_scorecard(make_service):
    service, transport, _ = make_service({"get_pack_scorecard": "get_pack_scorecard_view"})
    result = call(service.el_scorecard, {"id": VIEW})
    assert result["scorecard"]["resolution"]["total"] == 2
    assert transport.calls == [("get_pack_scorecard", {"id": VIEW})]


def test_follow_create_persists_card_and_reports_next_check(make_service):
    service, _, store = make_service({"create_research_follow": "create_follow_pack"})
    result = call(service.el_follow_create, {"pack_id": PACK})
    assert result["ok"] and result["next_check_at"] == "2026-11-10"
    assert "/el check follow_" in result["schedule_hint"]
    assert "/blueprint equitylayer:daily-check" in result["schedule_hint"]
    assert store.get(result["follow_id"])["follow_card"]["pack_id"] == PACK


def test_follow_create_twice_keeps_the_original_baseline(make_service):
    service, transport, store = make_service({"create_research_follow": "create_follow_pack"})
    first = call(service.el_follow_create, {"pack_id": PACK})
    second = call(service.el_follow_create, {"pack_id": PACK})
    assert second["already_following"] is True and second["follow_id"] == first["follow_id"]
    assert transport.names() == ["create_research_follow", "get_research_pack"]  # the Pack is read once
    assert len(store.all()[0]) == 1


@pytest.mark.parametrize("args", [{}, {"pack_id": PACK, "thesis_id": VIEW}])
def test_follow_create_needs_exactly_one_target(make_service, args):
    service, _, _ = make_service()
    assert call(service.el_follow_create, args)["error"] == "invalid_argument"


def _stored_follow(service):
    return call(service.el_follow_create, {"pack_id": PACK})["follow_id"]


def test_check_current_refreshes_card_and_keeps_following(make_service):
    routes = {"create_research_follow": "create_follow_pack", "check_research_follow": "check_follow_current"}
    service, transport, store = make_service(routes)
    follow_id = _stored_follow(service)
    result = call(service.el_follow_check, {"follow_id": follow_id})
    assert result["checked"][0]["status"] == "current" and result["needs_review"] == 0
    assert "No tracked variable moved" in result["markdown"]
    assert transport.calls[-1][1]["follow_card"]["follow_id"] == follow_id
    assert store.get(follow_id)["pending_review"] is None


def test_review_required_does_not_overwrite_card_until_accepted(make_service):
    routes = {"create_research_follow": "create_follow_pack", "check_research_follow": "check_follow_review_required"}
    service, transport, store = make_service(routes)
    follow_id = _stored_follow(service)
    card_before = store.get(follow_id)["follow_card"]

    result = call(service.el_follow_check, {"follow_id": follow_id})
    assert result["needs_review"] == 1
    assert "/el seen follow_" in result["markdown"]
    assert "Elite Material (2383) monthly revenue" in result["markdown"]
    stored = store.get(follow_id)
    assert stored["follow_card"] == card_before
    assert stored["pending_review"]["new_version"] == "2026-09"

    # Pack cards move on through create_research_follow, as caller_action.next_tool says.
    accepted = call(service.el_follow_check, {"follow_id": follow_id, "accept_next": True})
    assert accepted["accepted"] is True and accepted["previous_follow_id"] == follow_id
    assert transport.calls[-2] == ("create_research_follow", {"pack_id": PACK})
    assert transport.calls[-1][0] == "get_research_pack"  # the new version may change the hypotheses
    assert store.get(accepted["follow_id"])["pending_review"] is None


def test_accept_uses_next_card_when_server_provides_one(make_service):
    service, transport, store = make_service()
    old_id, new_id = "follow_" + "a" * 32, "follow_" + "b" * 32
    record = build_record({"follow_id": old_id, "thesis_id": VIEW})
    record["pending_review"] = {"status": "review_required", "next_card": {"follow_id": new_id, "thesis_id": VIEW}}
    store.save(record)
    result = call(service.el_follow_check, {"follow_id": old_id, "accept_next": True})
    assert result["follow_id"] == new_id
    assert store.get(old_id) is None and store.get(new_id)["follow_card"]["thesis_id"] == VIEW
    assert transport.calls == []


def test_unattended_run_never_accepts(make_service):
    service, _, store = make_service(in_cron=True)
    follow_id = "follow_" + "a" * 32
    record = build_record({"follow_id": follow_id, "pack_id": PACK})
    record["pending_review"] = {"status": "review_required"}
    store.save(record)
    assert call(service.el_follow_check, {"follow_id": follow_id, "accept_next": True})["error"] == (
        "accept_requires_user"
    )
    assert store.get(follow_id)["pending_review"]


def test_accept_with_nothing_pending(make_service):
    routes = {"create_research_follow": "create_follow_pack"}
    service, _, _ = make_service(routes)
    follow_id = _stored_follow(service)
    assert call(service.el_follow_check, {"follow_id": follow_id, "accept_next": True})["error"] == "nothing_to_accept"


def test_due_run_checks_due_cards_only_and_does_not_repeat_reviews(make_service):
    service, transport, store = make_service({"check_research_follow": "check_follow_current"})
    due, waiting, review = ("follow_" + c * 32 for c in "abc")
    store.save(build_record({"follow_id": due, "pack_id": "p1"}, {"next_check_at": "2000-01-01"}))
    store.save(build_record({"follow_id": waiting, "pack_id": "p2"}, {"next_check_at": "2999-01-01"}))
    pending = build_record({"follow_id": review, "pack_id": "p3"}, {"next_check_at": "2000-01-01"})
    pending["pending_review"] = {"status": "review_required"}
    store.save(pending)

    result = call(service.el_follow_check)
    assert result["mode"] == "due"
    assert [c["follow_id"] for c in result["checked"]] == [due]
    assert result["awaiting_review"][0]["follow_id"] == review
    assert transport.names() == ["check_research_follow"]


def test_due_run_with_nothing_due_makes_no_network_call(make_service):
    service, transport, _ = make_service()
    result = call(service.el_follow_check)
    assert result["ok"] and result["checked"] == [] and "No local follows are due" in result["markdown"]
    assert transport.calls == []


def test_partial_failure_keeps_going_and_keeps_the_card(make_service):
    service, _, store = make_service({"check_research_follow": 500})
    follow_id = "follow_" + "a" * 32
    store.save(build_record({"follow_id": follow_id, "pack_id": "p"}, {"next_check_at": "2000-01-01"}))
    result = call(service.el_follow_check)
    assert result["ok"] and result["errors"] == 1
    assert store.get(follow_id)["follow_card"]["pack_id"] == "p"


def test_supplied_card_is_checked_without_being_saved(make_service):
    service, _, store = make_service({"check_research_follow": "check_follow_current"})
    card = {"follow_id": "follow_" + "a" * 32, "pack_id": PACK}
    assert call(service.el_follow_check, {"follow_card": card})["checked"][0]["status"] == "current"
    assert store.all()[0] == []


def test_follow_list_is_local_only_and_reports_state(make_service):
    service, transport, store = make_service()
    store.save(build_record({"follow_id": "follow_" + "a" * 32, "pack_id": "p1"}, {"next_check_at": "2999-01-01"}))
    store.save(build_record({"follow_id": "follow_" + "b" * 32, "pack_id": "p2"}, {"next_check_at": "2000-01-01"}))
    result = call(service.el_follow_list)
    assert sorted(f["state"] for f in result["follows"]) == ["due", "waiting"]
    assert [f["state"] for f in call(service.el_follow_list, {"due_only": True})["follows"]] == ["due"]
    assert transport.calls == []


# -- slash commands and scheduling -----------------------------------------------------------------


def test_slash_flow_end_to_end(make_service):
    routes = {
        "list_registry": "list_registry",
        "get_research_pack": "get_research_pack",
        "get_pack_scorecard": "get_pack_scorecard_view",
        "create_research_follow": "create_follow_view",
        "check_research_follow": "check_follow_current",
    }
    service, transport, store = make_service(routes)
    el = commands.make_slash_handler(service)
    assert "/el check" in el("") and "/el list" in el("help")
    assert "tw-monthly-revenue" in el("registry")
    assert "Taiwan Stock Exchange" in el("pack tw-monthly-revenue")
    assert "Scorecard" in el(f"scorecard {VIEW}")
    assert "Now following" in el(f"follow {VIEW}")
    # The registry's own follow arguments decide thesis_id versus pack_id.
    assert transport.calls[-1] == ("create_research_follow", {"thesis_id": VIEW})
    follow_id = store.all()[0][0]["follow_id"]
    assert follow_id in el("follows", session_id="s", platform="cli")
    assert "current" in el(f"follow-check {follow_id}")
    assert "Removed" in el(f"unfollow {follow_id}")
    assert "You don't track anything yet" in el("follows")


def test_slash_errors_are_readable(make_service):
    service, _, _ = make_service({"list_registry": "list_registry"})
    el = commands.make_slash_handler(service)
    assert "missing_argument" in el("pack")
    assert "unknown_registry_entry" in el("follow nope")
    assert "Usage" in el("follow")
    assert "/el check" in el("nonsense")


def test_schedule_snippet_is_shell_safe_and_never_accepts():
    text = commands.schedule_text("08:30", "Asia/Taipei")
    assert "hermes cron create '30 8 * * *'" in text
    assert "--skill equitylayer:equitylayer-thesis-harness" in text
    assert "--timezone Asia/Taipei" in text
    assert "/blueprint equitylayer:daily-check" in text
    assert "never call el_seen" in commands.THESIS_CRON_PROMPT and "Call el_check with no arguments" in commands.THESIS_CRON_PROMPT
    assert "If report_total is 0" in commands.THESIS_CRON_PROMPT
    assert "[SILENT]" in commands.THESIS_CRON_PROMPT
    with pytest.raises(ValueError):
        commands.schedule_text("25:00")
