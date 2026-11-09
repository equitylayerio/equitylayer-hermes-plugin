import json

from equitylayer_plugin.commands import THESIS_CRON_PROMPT, make_slash_handler

ROUTES = {
    "get_variable": "get_variable_foci",
    "list_research_events": "list_research_events_foci",
    "list_upcoming_triggers": "list_upcoming_triggers_cpo",
}
FOCI = "v:3363.two.revenue.monthly"


def _save(service, title="CPO curated readings"):
    return json.loads(service.el_watch_save({"title": title, "variables": [FOCI], "theme": "optical_cpo"}))


def test_save_checks_ids_with_equitylayer(make_service):
    service, transport, _ = make_service(ROUTES)
    saved = _save(service)
    assert saved["ok"] and saved["watch_id"] == "cpo-curated-readings"
    assert transport.names() == ["get_variable"]
    bad = json.loads(service.el_watch_save({"title": "x", "variables": ["FOCI revenue"]}))
    assert bad["ok"] is False and bad["error"] == "invalid_argument"
    too_many = json.loads(service.el_watch_save({"title": "x", "variables": [f"v:a{i}.two.revenue" for i in range(9)]}))
    assert too_many["error"] == "invalid_argument"


def test_first_check_reports_and_waits_for_the_person(make_service):
    service, transport, _ = make_service(ROUTES)
    watch_id = _save(service)["watch_id"]
    result = json.loads(service.el_watch_check({}))
    assert result["report_total"] == 1 and result["awaiting_read"] == [watch_id]
    text = result["markdown"]
    assert "First check of this watchlist" in text
    assert "224,257 TWD thousand" in text and "+9.7% vs 2026-08" in text
    assert "It does not show FAU or CPO revenue." in text
    assert "TPEx open data lists 2026-09 monthly revenue" in text
    assert "Coming up" in text and "Open Government Data License" in text
    # Readings come from the core route; events and due dates from the same server's full list.
    paths = dict(zip(transport.names(), transport.paths))
    assert paths["get_variable"].endswith("/mcp")
    assert paths["list_research_events"].endswith("/mcp/full")
    assert paths["list_upcoming_triggers"].endswith("/mcp/full")


def test_unread_repeats_then_nothing_new_is_silent(make_service):
    service, _, _ = make_service(ROUTES)
    watch_id = _save(service)["watch_id"]
    service.el_watch_check({})
    again = json.loads(service.el_watch_check({}))
    assert again["report_total"] == 1  # still unread, so it repeats
    assert json.loads(service.el_watch_seen({"watch_id": watch_id}))["ok"]
    quiet = json.loads(service.el_watch_check({"watch_id": watch_id}))
    assert quiet["report_total"] == 0 and "Nothing new since you last read." in quiet["markdown"]


def test_scheduled_runs_never_mark_read(make_service):
    service, _, _ = make_service(ROUTES)
    watch_id = _save(service)["watch_id"]
    cron, _, _ = make_service(ROUTES, in_cron=True)
    assert json.loads(cron.el_watch_check({}))["awaiting_read"] == [watch_id]
    refused = json.loads(cron.el_watch_seen({"watch_id": watch_id}))
    assert refused["ok"] is False and refused["error"] == "not_in_scheduled_run"


def test_dashboard_is_local_escaped_and_listed_as_an_artifact(make_service, tmp_path):
    service, _, _ = make_service(ROUTES)
    _save(service, title="<script>alert(1)</script> CPO")
    service.el_watch_check({})
    rendered = json.loads(service.el_dashboard_render({}))
    path = rendered["artifact_file"]
    assert path.endswith("dashboard.html") and path.startswith(str(tmp_path))
    page = open(path, encoding="utf-8").read()
    assert "<script" not in page and "&lt;script&gt;" in page
    assert "Needs you" in page and "224,257" in page
    assert "<polyline" in page  # sparkline drawn inline, no remote assets
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "nothing here says what to buy, sell, size or time" in page


def test_checks_refresh_the_dashboard(make_service, tmp_path):
    service, _, _ = make_service(ROUTES)
    _save(service)
    service.el_watch_check({})
    assert (tmp_path / "dashboard.html").exists()


def test_daily_prompt_covers_watchlists_and_never_marks_read():
    assert "el_watch_check" in THESIS_CRON_PROMPT and "el_harness_check" in THESIS_CRON_PROMPT
    assert "never call el_harness_seen or el_watch_seen" in THESIS_CRON_PROMPT
    assert "[SILENT]" in THESIS_CRON_PROMPT


def test_slash_watch_commands(make_service):
    service, _, _ = make_service(ROUTES)
    handle = make_slash_handler(service)
    _save(service)
    assert "cpo-curated-readings" in handle("watches")
    assert "Saved as read." in handle("watch-check cpo-curated-readings")
    assert "dashboard.html" in handle("dashboard")
    assert "Removed" in handle("unwatch cpo-curated-readings")
