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


def test_adding_a_thesis_keeps_the_readings_as_evidence(make_service, tmp_path):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI], "theme": "optical_cpo"})
    call(service.el_check)
    upgraded = call(service.el_track, {"item_id": "cpo-readings", "harness": HARNESS})
    assert upgraded["ok"] and upgraded["item_id"] == "cpo-readings" and upgraded["level"] == "your thesis"
    assert upgraded["readings_kept"] and "sits on top of your readings" in upgraded["markdown"]
    assert (tmp_path / "watchlists" / "cpo-readings.json").exists()  # nothing is lost
    harness = json.loads((tmp_path / "harnesses" / "cpo-readings.json").read_text())
    assert harness["theme"] == "optical_cpo"
    assert [i["level"] for i in call(service.el_list)["items"]] == ["your thesis + readings"]
    page = open(call(service.el_dashboard_render)["artifact_file"], encoding="utf-8").read()
    glance = page[page.index("At a glance"):page.index("Evidence")]
    assert "Your thesis" in glance and "CPO and optical networking" in page and "All readings" in page


def test_one_id_checks_and_marks_both_parts(make_service):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI], "theme": "optical_cpo"})
    call(service.el_track, {"item_id": "cpo-readings", "harness": HARNESS})
    checked = call(service.el_check, {"item_id": "cpo-readings"})
    assert checked["report_total"] == 2 and checked["awaiting_read"] == ["cpo-readings"]
    assert call(service.el_seen, {"item_id": "cpo-readings"})["ok"]
    listed = call(service.el_list)["items"][0]
    assert listed["state"] != "unread"


def test_changing_a_thesis_updates_it_instead_of_duplicating(make_service, tmp_path):
    service, _, _ = make_service(ROUTES)
    saved = call(service.el_track, {"harness": HARNESS})
    changed = {**HARNESS, "why": "Updated reasoning."}
    for key in ("item_id", "harness_id"):
        result = call(service.el_track, {key: saved["item_id"], "harness": changed})
        assert result["ok"] and result["item_id"] == saved["item_id"]
    assert len(list((tmp_path / "harnesses").glob("*.json"))) == 1


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


def test_check_reports_errors_instead_of_going_silent(make_service, monkeypatch):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI]})
    call(service.el_check)
    call(service.el_seen, {"item_id": "cpo-readings"})

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(type(service), "_watch_check", boom)
    result = call(service.el_check)
    assert result["ok"] and result["report_total"] == 1 and "Could not check your readings" in result["markdown"]


def test_pending_pack_update_keeps_reporting(make_service):
    routes = {**ROUTES, "check_research_follow": "check_follow_review_required"}
    service, _, store = make_service(routes)
    followed = call(service.el_track, {"pack_id": "ai-compute-pcb-ccl-value-capture"})
    record = store.get(followed["item_id"])
    record["follow_card"]["version"] = "2026-08"  # the card the review fixture moves on from
    store.save(record)
    first = call(service.el_check)
    assert first["report_total"] >= 1
    again = call(service.el_check)
    assert again["report_total"] >= 1 and followed["item_id"] in again["awaiting_read"]
    refused = call(service.el_seen, {"item_id": followed["item_id"]})
    assert refused["error"] == "accept_needs_confirmation"


def test_ids_and_levels_are_checked(make_service):
    service, _, _ = make_service(ROUTES)
    thesis = call(service.el_track, {"harness": HARNESS})["item_id"]
    follow = call(service.el_track, {"pack_id": "ai-compute-pcb-ccl-value-capture"})["item_id"]
    assert call(service.el_track, {"item_id": follow, "harness": HARNESS})["error"] == "invalid_argument"
    assert call(service.el_track, {"item_id": follow, "variables": [FOCI]})["error"] == "invalid_argument"
    assert call(service.el_check, {"item_id": 123})["error"] == "invalid_argument"
    added = call(service.el_track, {"item_id": thesis, "variables": [FOCI]})
    assert added["ok"] and added["item_id"] == thesis and added["level"] == "your thesis"


def test_updating_readings_keeps_title_and_cron_cannot_change_items(make_service):
    service, _, _ = make_service(ROUTES)
    call(service.el_track, {"title": "CPO readings", "variables": [FOCI], "theme": "optical_cpo"})
    updated = call(service.el_track, {"item_id": "cpo-readings", "variables": [FOCI]})
    assert updated["ok"] and "CPO readings" in updated["markdown"]
    cron, _, _ = make_service(ROUTES, in_cron=True)
    assert call(cron.el_track, {"title": "x", "variables": [FOCI]})["error"] == "not_in_scheduled_run"


PACK_ID = "taiwan-optical-revenue-vs-cpo-guidance"
PACK_ROUTES = {**ROUTES, "get_research_pack": "get_research_pack_cpo_v1", "check_research_follow": "check_follow_current",
               "list_registry": "list_registry_cpo", "create_research_follow": "create_follow_pack_cpo"}


def test_following_a_pack_keeps_its_thesis_and_follows_its_readings(make_service, tmp_path):
    from equitylayer_plugin.commands import _remove_item

    service, _, store = make_service(PACK_ROUTES)
    followed = call(service.el_track, {"pack_id": PACK_ID})
    fid = followed["item_id"]
    assert followed["ok"] and followed["level"] == "EquityLayer thesis"
    assert "Now following EquityLayer's Research Pack:** What Taiwan" in followed["markdown"]
    record = store.get(fid)
    assert len(record["pack"]["hypotheses"]) == 3 and record["pack"]["theme_id"] == "optical_cpo"
    assert record["pack"]["variables"] == ["v:3081.two.revenue.monthly", "v:3163.two.revenue.monthly",
                                           "v:3363.two.revenue.monthly"]
    readings_id = record["readings_id"]
    watch = json.loads((tmp_path / "watchlists" / f"{readings_id}.json").read_text())
    assert watch["follow_id"] == fid and watch["theme"] == "optical_cpo"
    assert watch["title"] == "CPO Pack readings: What Taiwan's optical suppliers report, and what they only…"
    assert [(i["id"], i["level"]) for i in call(service.el_list)["items"]] == [(fid, "EquityLayer thesis + readings")]

    check = call(service.el_check, {"item_id": fid})
    text = check["markdown"]
    assert text.startswith("## EquityLayer thesis: What Taiwan") and "Would be wrong if:" in text
    assert "current. None of the readings it watches has moved" in text and "Follow Card" not in text
    assert check["awaiting_read"] == [readings_id] and check["level"] == "EquityLayer thesis"
    assert call(service.el_seen, {"item_id": fid})["ok"]
    assert json.loads((tmp_path / "watchlists" / f"{readings_id}.json").read_text())["pending"] is None

    page = open(call(service.el_dashboard_render)["artifact_file"], encoding="utf-8").read()
    glance = page[page.index("At a glance"):page.index("Evidence")]
    assert '<p class="eyebrow">Thesis Pack · CPO</p>' in glance
    assert "Wrong if" in glance and "LandMark, a laser epi supplier" in glance
    assert "Follow this Pack" not in page and "has not published" not in page
    assert "Readings for: What Taiwan&#x27;s optical" in page[page.index("Evidence"):]

    assert _remove_item(service, {"item_id": fid})["ok"]
    assert store.get(fid) is None and not (tmp_path / "watchlists" / f"{readings_id}.json").exists()


def test_the_pack_readings_id_reaches_the_whole_item(make_service):
    service, _, store = make_service(PACK_ROUTES)
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    readings_id = store.get(fid)["readings_id"]
    check = call(service.el_check, {"item_id": readings_id})
    assert check["markdown"].startswith("## EquityLayer thesis:") and check["level"] == "EquityLayer thesis"
    refused = call(service.el_track, {"item_id": readings_id, "variables": [FOCI]})
    assert refused["error"] == "invalid_argument" and "followed Research Pack" in refused["message"]


def test_a_pack_that_cannot_be_read_is_still_followed(make_service):
    service, _, store = make_service({**ROUTES, "get_research_pack": 503})
    followed = call(service.el_track, {"pack_id": PACK_ID})
    assert followed["ok"] and "pack" not in store.get(followed["item_id"])
    assert "readings_id" not in store.get(followed["item_id"])


def test_preview_puts_a_published_pack_first(make_service):
    service, _, _ = make_service(PACK_ROUTES)
    page = open(call(service.el_dashboard_render, {"preview_variables": [FOCI], "preview_theme": "optical_cpo"})
                ["artifact_file"], encoding="utf-8").read()
    actions = page[page.index('<div class="actions">'):]
    assert actions.index("Follow EquityLayer&#x27;s Research Pack<") < actions.index("Follow these readings")
    assert 'class="ghost" data-hermes-send="I\'d like to follow these curated readings. Show me the card first."' in actions



def test_new_data_for_a_pack_is_read_with_its_readings_and_a_new_revision_is_not(make_service, tmp_path):
    service, _, store = make_service({**PACK_ROUTES, "check_research_follow": "check_follow_cpo_new_data"})
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    check = call(service.el_check, {"item_id": fid})
    assert "a reading it watches has new data" in check["markdown"] and "Hypotheses are unchanged" not in check["markdown"]
    assert "A new version is published" not in check["markdown"]
    assert store.get(fid)["pending_review"]["revision_changed"] is False
    page = open(call(service.el_dashboard_render)["artifact_file"], encoding="utf-8").read()
    assert "new data to read" in page and "tell Hermes you've read it" in page
    seen = call(service.el_seen, {"item_id": fid})
    assert seen["ok"] and "baseline moved to the new data" in seen["markdown"]
    new_id = [f for f in (tmp_path / "follows").iterdir()][0].stem
    assert store.get(new_id)["pending_review"] is None and store.get(new_id)["readings_id"]

    # A new revision still needs the person's explicit yes.
    record = store.get(new_id)
    record["pack"]["revision"] = "R1"
    record["follow_card"]["version"] = "R1"
    store.save(record)
    call(service.el_check, {"item_id": new_id})
    assert store.get(new_id)["pending_review"]["revision_changed"] is True
    seen = call(service.el_seen, {"item_id": new_id})
    assert "new revision to review" in seen["markdown"] and store.get(new_id)["pending_review"]


def test_refollowing_completes_a_pack_followed_before_it_could_be_read(make_service):
    service, _, store = make_service({**PACK_ROUTES, "get_research_pack": 503})
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    assert "pack" not in store.get(fid)
    service, _, _ = make_service(PACK_ROUTES)  # same local files, the Pack readable now
    again = call(service.el_track, {"pack_id": PACK_ID})
    assert again["already_following"] and store.get(fid)["readings_id"] and store.get(fid)["pack"]["hypotheses"]


def test_a_follow_with_nothing_waiting_is_not_an_error(make_service):
    service, _, store = make_service({**ROUTES, "get_research_pack": 503})
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    seen = call(service.el_seen, {"item_id": fid})
    assert seen["ok"] and "no update waiting" in seen["markdown"]



def test_several_packs_in_one_sector(make_service):
    from equitylayer_plugin.dashboard import render

    def summary(pid, title):
        return {"pack_id": pid, "title": title, "view": f"View of {title}.", "theme_id": "optical_cpo",
                "url": f"https://equitylayer.io/research/packs/{pid}",
                "hypotheses": [{"statement": f"{title} H{n}", "confidence": "low", "falsifier": "x", "due": "2027-01-10"}
                               for n in (1, 2)]}

    packs = [{"id": pid, "kind": "pack", "title": pid, "theme_id": "optical_cpo", "status": "verified",
              "access": "public"} for pid in ("cpo-timing-and-form", "cpo-laser-inp-test-bottleneck", "taiwan-x")]
    preview = {"title": "CPO live readings", "as_of": "2026-11-11", "rows": [], "theme": "optical_cpo"}
    page = render(None, [], [], preview=preview, packs=packs, followed={})
    assert "Follow EquityLayer&#x27;s Research Packs (3)" in page
    # The button answers decision 2 only: the card and the person's yes still come before anything is followed.
    assert 'data-hermes-send="I&#x27;d like to follow EquityLayer&#x27;s Research Packs. Show me their card first."' in page
    assert "Yes, follow EquityLayer" not in page
    assert page.count("Research Pack · CPO and optical networking · published") == 3

    followed = {pid: {"follow_id": "follow_" + str(n) * 32, "target_id": pid, "pack": summary(pid, f"Pack {n}"),
                      "next_check_at": "2026-11-12"}
                for n, pid in enumerate(("cpo-timing-and-form", "cpo-laser-inp-test-bottleneck"), 1)}
    page = render(None, [], [], packs=packs, followed=followed)
    glance = page[page.index("At a glance"):]
    assert glance.count('<p class="eyebrow">Thesis Pack · CPO</p>') == 2
    assert glance.count('<details open><summary class="tc-row">') == 1  # only the first hypothesis starts open
    assert glance.count('<details><summary class="tc-row">') == 3
    assert page.count("Follow this Pack") == 1  # only the Pack they don't follow is offered



def test_a_pack_that_is_no_longer_published_is_reported_once_and_not_shown_as_current(make_service, tmp_path):
    service, _, store = make_service({**PACK_ROUTES, "check_research_follow": "check_follow_cpo_unavailable"})
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    record = store.get(fid)
    record["next_check_at"] = "2026-01-01"  # due
    store.save(record)
    first = call(service.el_check)
    assert first["report_total"] >= 1 and "not published right now" in first["markdown"]
    record = store.get(fid)
    assert record["unavailable_since"] and record["next_check_at"] > "2026-01-01"
    record["next_check_at"] = "2026-01-02"  # due again, still unavailable: no new notice for the Pack
    store.save(record)
    again = call(service.el_check)
    assert "not published right now" not in again["markdown"]
    assert [i["state"] for i in call(service.el_list)["items"]] == ["not published"]
    single = call(service.el_check, {"item_id": fid})
    assert "## EquityLayer thesis" not in single["markdown"] and "not published right now" in single["markdown"]
    page = open(call(service.el_dashboard_render)["artifact_file"], encoding="utf-8").read()
    assert "you follow it" not in page and "not EquityLayer's current view" in page
    assert "Follow this Pack" not in page


def test_dashboard_caps_pack_heroes_at_four():
    from equitylayer_plugin.dashboard import render

    followed = {f"pack-{n}": {"follow_id": "follow_" + str(n) * 32, "target_id": f"pack-{n}",
                              "pack": {"title": f"Pack {n}", "theme_id": "optical_cpo",
                                       "hypotheses": [{"statement": "h", "confidence": "low"}]}}
                for n in range(1, 6)}
    page = render(None, [], [], followed=followed)
    assert page.count('<p class="eyebrow">Thesis Pack · CPO</p>') == 4
    assert page.count("Research Pack · you follow it") == 1  # the fifth still shows, as a card


def test_pack_readings_titles_fit():
    from equitylayer_plugin.tools import EquityLayerTools  # noqa: F401 - the title logic lives in _attach_pack
    import inspect
    from equitylayer_plugin import tools

    assert "room = 80 - len(prefix)" in inspect.getsource(tools.EquityLayerTools._attach_pack)



def test_followed_packs_keep_the_registry_order():
    from equitylayer_plugin.dashboard import render

    packs = [{"id": pid, "kind": "pack", "title": pid, "theme_id": "optical_cpo", "status": "verified", "access": "public"}
             for pid in ("cpo-laser-inp-test-bottleneck", "cpo-timing-and-form", "taiwan-optical-revenue-vs-cpo-guidance")]
    # Local files sort by next check, so the Taiwan Pack would come first without the registry's order.
    followed = {pid: {"follow_id": "follow_" + str(n) * 32, "target_id": pid, "next_check_at": f"2026-11-1{n}",
                      "pack": {"title": f"Title {pid}", "theme_id": "optical_cpo", "hypotheses": []}}
                for n, pid in ((3, "cpo-laser-inp-test-bottleneck"), (4, "cpo-timing-and-form"),
                               (1, "taiwan-optical-revenue-vs-cpo-guidance"))}
    followed = dict(sorted(followed.items(), key=lambda kv: kv[1]["next_check_at"]))
    page = render(None, [], [], packs=packs, followed=followed)
    order = [page.index(f"Title {pid}") for pid in ("cpo-laser-inp-test-bottleneck", "cpo-timing-and-form",
                                                    "taiwan-optical-revenue-vs-cpo-guidance")]
    assert order == sorted(order)



def test_pack_categories_label_cards_and_put_thesis_packs_first():
    from equitylayer_plugin.dashboard import render

    packs = [{"id": pid, "kind": "pack", "title": pid, "theme_id": "optical_cpo", "status": "verified",
              "access": "public", "category": cat}
             for pid, cat in (("cpo-laser-inp-test-bottleneck", "thesis"), ("cpo-timing-and-form", "thesis"),
                              ("taiwan-optical-revenue-vs-cpo-guidance", "tracking"))]
    preview = {"title": "CPO live readings", "as_of": "2026-11-11", "rows": [], "theme": "optical_cpo"}
    page = render(None, [], [], preview=preview, packs=packs, followed={})
    assert "Follow EquityLayer&#x27;s thesis Packs (2)" in page
    assert page.count("Thesis Pack · CPO") == 2
    assert page.count("Tracking Pack · CPO") == 1
    assert page.index("cpo-laser-inp-test-bottleneck") < page.index("taiwan-optical-revenue-vs-cpo-guidance")
    for p in packs:
        p.pop("category")
    page = render(None, [], [], preview=preview, packs=packs, followed={})  # before the field ships: no label
    assert "Thesis Pack" not in page and "Tracking Pack" not in page
    assert "Follow EquityLayer&#x27;s Research Packs (3)" in page



def test_preview_puts_the_theses_before_the_live_readings():
    from equitylayer_plugin.dashboard import render

    packs = [{"id": "cpo-timing-and-form", "kind": "pack", "title": "Timing", "theme_id": "optical_cpo",
              "status": "verified", "access": "public", "category": "thesis"}]
    preview = {"title": "CPO live readings", "as_of": "2026-11-11", "rows": [], "theme": "optical_cpo"}
    page = render(None, [], [], preview=preview, packs=packs, followed={})
    assert page.index("Thesis Pack · CPO and optical networking") < page.index('<h2 id="live">')
    assert page.index("EquityLayer's research for this sector") < page.index('<h2 id="live">')
    assert "Your thesis" not in page  # a thesis Pack is EquityLayer's, never shown as the person's own



def test_registry_list_shows_the_pack_type(make_service):
    service, _, _ = make_service({**PACK_ROUTES})
    import json as _json, pathlib as _pl
    listed = call(service.el_research_pack, {"action": "list"})
    assert "| type |" in listed["markdown"] or "type" in listed["markdown"].splitlines()[2]



def test_dashboard_is_plain_a_packs_readings_sit_on_its_card(make_service):
    service, _, store = make_service(PACK_ROUTES)
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    call(service.el_check, {"item_id": fid})
    page = open(call(service.el_dashboard_render)["artifact_file"], encoding="utf-8").read()
    glance = page[page.index('id="glance"'):page.index('id="evidence"')]
    assert 'class="chip' in glance and "Wrong if" in glance
    assert "What your readings show" not in page  # no second card for the same Pack's readings
    assert "Discover → Follow" not in page and "Watchlist <b>" not in page
    assert "new reading" in page and "I&#x27;ve read it" not in page and "I've read it" in page
    assert '<details class="row-more"><summary>About this reading</summary>' in page



def test_pack_card_is_a_checklist():
    from equitylayer_plugin.dashboard import render

    record = {"follow_id": "follow_" + "1" * 32, "target_id": "p", "next_check_at": "2026-11-12", "readings_id": "r",
              "pack": {"title": "Lasers are the bottleneck", "view": "Short view.", "theme_id": "optical_cpo",
                       "category": "thesis", "hypotheses": [
                           {"statement": "Laser supply is rationed: long explanation", "confidence": "low",
                            "due": "2027-02-10", "falsifier": "A filing says supply caught up.",
                            "variables": ["v:3081.two.revenue.monthly"]}]}}
    watch = {"id": "r", "title": "CPO Pack readings: Lasers", "follow_id": record["follow_id"], "theme": "optical_cpo",
             "last_check": {"as_of": "2026-11-11", "rows": [
                 {"variable": "v:3081.two.revenue.monthly", "name": "LandMark monthly revenue", "unit": "TWD thousand",
                  "latest": {"period": "2026-09", "value": 540492}, "change": "+3.8% vs 2026-08",
                  "next_reading": "2026-01-01", "entity": "3081.TWO"}]}}
    page = render(None, [], [watch], followed={"p": record})
    card = page[page.index("thesis-card"):page.index("</section>", page.index("thesis-card"))]
    for part in ("Thesis Pack · CPO", "Lasers are the bottleneck", "H1", "Laser supply is rationed<", "low",
                 "tested by 2027-02-10", ">Wrong if<", "A filing says supply caught up.", ">Tracks<", 'class="chip', "540,492",
                 "+3.8%", ">Next<", "late: ", "Pack check"):
        assert part in card, part
    assert "EquityLayer Research Pack" not in page



def test_dashboard_json_has_the_same_facts_for_agents(make_service, tmp_path):
    service, _, store = make_service(PACK_ROUTES)
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    call(service.el_check, {"item_id": fid})
    rendered = call(service.el_dashboard_render)
    assert "dashboard.json" in rendered["markdown"]
    data = json.loads((tmp_path / "dashboard.json").read_text())
    assert data["format"] == "equitylayer-hermes-dashboard/1"
    pack = data["equitylayer_packs"][0]
    assert pack["item_id"] == fid and pack["pack_id"] == PACK_ID and len(pack["hypotheses"]) == 3
    h1 = pack["hypotheses"][0]
    assert h1["id"] == "H1" and h1["wrong_if"] and h1["test_by"] and h1["tracks"][0]["variable"].startswith("v:")
    assert data["readings"] == []  # a Pack's readings live under the Pack, not twice
    assert "Not investment advice." in data["note"]



def test_chain_diagram_lights_thresholds_and_calendar(make_service, tmp_path):
    from equitylayer_plugin.dashboard import _band, _cond, calendar_events, calendar_ics, render

    rules = [{"if": ">= 540492", "means": "strengthens", "say": "Above the bar."},
             {"if": "501212..540492", "means": "insufficient_evidence", "say": "Inside the range."},
             {"if": "< 501212", "means": "weakens", "say": "Below the bar."}]
    assert _band(rules, 560000)["means"] == "strengthens" and _band(rules, 400000)["means"] == "weakens"
    assert _band(rules, "a statement") is None and _cond(">= 540492") == "≥ 540,492"

    def page_for(period, value):
        record = {"follow_id": "follow_" + "1" * 32, "target_id": "p", "next_check_at": "2026-11-12", "readings_id": "r",
                  "pack": {"title": "Lasers", "theme_id": "optical_cpo", "category": "thesis", "stage": "network",
                           "hypotheses": [{"statement": "Laser supply is rationed", "confidence": "low", "due": "2027-02-10",
                                           "falsifier": "x", "variables": ["v:3081.two.revenue.monthly"],
                                           "reads": {"v:3081.two.revenue.monthly": {"baseline": "2026-09", "rules": rules}}}]}}
        watch = {"id": "r", "title": "CPO Pack readings: Lasers", "follow_id": record["follow_id"], "theme": "optical_cpo",
                 "last_check": {"rows": [{"variable": "v:3081.two.revenue.monthly", "name": "LandMark (3081) monthly revenue",
                                          "latest": {"period": period, "value": value}, "next_reading": "2026-12-10",
                                          "company": {"step": "Epitaxy wafers", "step_order": 1, "role": "Makes epi wafers."}}]}}
        return render(None, [], [watch], followed={"p": record}), record, watch

    page, record, watch = page_for("2026-09", 540492)      # the baseline reading judges nothing
    assert 'class="light flat"' in page and 'class="light up"' not in page
    page, _, _ = page_for("2026-10", 480000)               # a later reading below the bar
    assert 'class="light down"' in page and ">Weakens if<" in page and "LandMark below the bar (&lt; 501,212)" in page and "LandMark above the bar (≥ 540,492)" in page
    assert "The CPO supply chain · where the theses sit" in page and "A · H1" in page and "not tracked yet" in page
    assert "Part of AI compute, in the network layer." in page and "https://equitylayer.io/themes/ai-compute" in page
    assert "<script" not in page
    events = calendar_events([], [watch], {"p": record})
    assert [e["date"] for e in events] == ["2026-11-12", "2026-12-10", "2027-02-10"]
    ics = calendar_ics(events)
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == 3 and "DTSTART;VALUE=DATE:20261210" in ics

    service, _, _ = make_service(PACK_ROUTES)
    fid = call(service.el_track, {"pack_id": PACK_ID})["item_id"]
    call(service.el_check, {"item_id": fid})
    rendered = call(service.el_dashboard_render)
    assert (tmp_path / "calendar.ics").exists() and "calendar.ics" in rendered["markdown"]
    assert json.loads((tmp_path / "dashboard.json").read_text())["calendar"]



def test_card_shows_sources_and_what_moves_if_a_hypothesis_holds():
    from equitylayer_plugin.dashboard import render
    from equitylayer_plugin.formatters import pack_summary

    summary = pack_summary({"pack_id": "p", "title": "T", "theme_id": "optical_cpo", "hypotheses": [
        {"assertion": {"statement": "Pluggables keep growing"}, "confidence": "medium", "test": {"falsifier": "x", "due": "2027-05-15"},
         "where_value_moves": [{"node": "network.optical_module", "effect": "gains"}, {"node": "x", "effect": "moon"}],
         "watches": [{"variable": "v:cohr.us.revenue.quarterly", "baseline": {"period": "FY2027-Q1"}, "how_to_read": []}]}]})
    assert summary["hypotheses"][0]["moves"] == [{"node": "network.optical_module", "effect": "gains"}]
    record = {"follow_id": "follow_" + "1" * 32, "target_id": "p", "readings_id": "r", "pack": summary}
    watch = {"id": "r", "title": "CPO Pack readings: T", "follow_id": record["follow_id"], "last_check": {"rows": [
        {"variable": "v:cohr.us.revenue.quarterly", "name": "Coherent segment revenue", "caveat": "Not CPO alone.",
         "latest": {"period": "FY2027-Q1", "value": 1951.7}, "source_url": "https://www.sec.gov/x"}]}}
    page = render(None, [], [watch], followed={"p": record})
    assert ">If it holds<" in page and "optical modules gain (per the Pack)" in page
    assert ">Sources<" in page and '<a href="https://www.sec.gov/x">Coherent</a>' in page
    summary["hypotheses"][0]["moves"] = []
    page = render(None, [], [watch], followed={"p": record})
    assert "not stated in the Pack yet" in page and "If it fails" not in page  # nothing is inferred



def test_core_hypotheses_lead_and_the_rest_fold():
    from equitylayer_plugin.dashboard import render

    def hyp(text, role):
        return {"statement": text, "confidence": "low", "due": "2027-02-10", "falsifier": "x", "role": role, "variables": []}

    record = {"follow_id": "follow_" + "1" * 32, "target_id": "p",
              "pack": {"title": "T", "theme_id": "optical_cpo", "category": "thesis",
                       "hypotheses": [hyp("Core claim", "core"), hyp("Supporting check", "supporting"), hyp("A risk", "risk")]}}
    page = render(None, [], [], followed={"p": record})
    card = page[page.index("thesis-card"):]
    assert card.index("Core claim") < card.index("+ 1 supporting · 1 risk") < card.index("Supporting check")
    assert "not tested yet" not in page and "confidence low</span></summary>" not in page
    assert "confidence low" in page  # still there, inside the opened list



def test_model_line_uses_equitylayers_mapping_or_a_marked_derived_label():
    from equitylayer_plugin.dashboard import _model_line

    mapped = {"variable": "v:cohr.us.data_center_communications_revenue.quarterly", "name": "Coherent segment revenue",
              "model_line": {"line": "segment_revenue", "timing": "lagging", "part_of": "v:cohr.us.revenue.quarterly",
                             "share_of_total": {"pct": 82.3, "period": "FY2027-Q1", "of": "v:cohr.us.revenue.quarterly"}}}
    assert _model_line(mapped) == ("segment revenue, about 82% of the company total in FY2027-Q1", "lagging")
    assert _model_line({"variable": "v:x", "model_line": {"line": "orders_outlook", "timing": "leading", "share_of_total": None}}) == (
        "orders and outlook (not revenue yet)", "leading")
    # Not mapped yet: a label read off the variable, marked as derived.
    assert _model_line({"variable": "v:3081.two.revenue.monthly", "name": "LandMark (3081) monthly revenue"}) == (
        "company revenue (derived)", "monthly, an early read on the quarter")
    assert _model_line({"variable": "v:form.us.systems_revenue.quarterly", "name": "FormFactor Systems segment revenue"})[0] == (
        "segment revenue (derived)")
    assert _model_line({"variable": "v:x.us.other.quarterly", "name": "Something"})[0] == ""


def test_dashboard_json_carries_a_signal_per_hypothesis():
    from equitylayer_plugin.dashboard import hypothesis_signal

    h = {"variables": ["v:a.us.revenue.quarterly"],
         "reads": {"v:a.us.revenue.quarterly": {"baseline": "2026-Q3", "rules": [{"if": ">= 100", "means": "strengthens"},
                                                                               {"if": "< 90", "means": "weakens"}]}}}
    assert hypothesis_signal(h, {"v:a.us.revenue.quarterly": {"latest": {"period": "2026-Q3", "value": 120}}}) == "no_verdict"
    assert hypothesis_signal(h, {"v:a.us.revenue.quarterly": {"latest": {"period": "2026-Q4", "value": 120}}}) == "supports"
    assert hypothesis_signal(h, {"v:a.us.revenue.quarterly": {"latest": {"period": "2026-Q4", "value": 80}}}) == "weakens"
    two = {"variables": ["v:a.us.revenue.quarterly", "v:b.us.revenue.quarterly"], "reads": {
        "v:a.us.revenue.quarterly": h["reads"]["v:a.us.revenue.quarterly"],
        "v:b.us.revenue.quarterly": {"baseline": "2026-Q3", "rules": [{"if": ">= 5", "means": "strengthens"}]}}}
    by_var = {"v:a.us.revenue.quarterly": {"latest": {"period": "2026-Q4", "value": 120}},
              "v:b.us.revenue.quarterly": {"latest": {"period": "2026-Q3", "value": 9}}}   # b is still at its baseline
    assert hypothesis_signal(two, by_var) == "partly_supports"
