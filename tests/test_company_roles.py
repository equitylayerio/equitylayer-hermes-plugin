import json

from equitylayer_plugin import company_roles

ROUTES = {
    "get_variable": "get_variable_foci",
    "list_research_events": "list_research_events_foci",
    "list_upcoming_triggers": "list_upcoming_triggers_cpo",
}
ROLE = {"name": "FOCI Fiber Optic Communications", "step": "Passive optics and fiber arrays", "step_order": 3,
        "role": "Makes fiber array units that connect fiber to optical engines.", "source_title": "FOCI IR",
        "source_url": "https://www.foci.com.tw/en/about"}


def test_loader_keeps_only_well_formed_entries(tmp_path):
    path = tmp_path / "roles.json"
    path.write_text(json.dumps({"companies": {
        "3363.TWO": ROLE,
        "BAD": ROLE,                                            # entity id shape
        "2455.TW": {**ROLE, "source_url": "ftp://x"},          # not a web source
        "3081.TWO": {**ROLE, "role": None},                    # no role
        "3163.TWO": {**ROLE, "role": "x" * 300},               # too long
    }}))
    company_roles.load.cache_clear()
    loaded = company_roles.load(str(path))
    company_roles.load.cache_clear()
    assert list(loaded) == ["3363.TWO"] and loaded["3363.TWO"]["step_order"] == 3


def test_role_shows_in_variable_and_dashboard(make_service, monkeypatch):
    import equitylayer_plugin.harness_tools as ht
    import equitylayer_plugin.watch_tools as wt

    clean = company_roles._clean(ROLE)
    monkeypatch.setattr(ht, "role_for", lambda entity: clean if entity == "3363.TWO" else None)
    monkeypatch.setattr(wt, "role_for", lambda entity: clean if entity == "3363.TWO" else None)
    service, _, _ = make_service(ROUTES)
    variable = json.loads(service.el_get_variable({"variable": "v:3363.two.revenue.monthly"}))
    assert variable["company_role"]["step"] == "Passive optics and fiber arrays"
    assert "**What FOCI Fiber Optic Communications does** (Passive optics and fiber arrays)" in variable["markdown"]
    assert "https://" not in variable["markdown"].split("**What")[1]
    rendered = json.loads(service.el_dashboard_render({"preview_variables": ["v:3363.two.revenue.monthly"]}))
    page = open(rendered["artifact_file"], encoding="utf-8").read()
    assert "Passive optics and fiber arrays" in page and "Makes fiber array units" in page
    assert 'href="https://www.foci.com.tw/en/about"' in page


def test_shipped_roles_file_is_valid():
    raw = json.loads(company_roles.ROLES_FILE.read_text(encoding="utf-8"))
    company_roles.load.cache_clear()
    assert len(company_roles.load()) == sum(1 for e in raw["companies"].values() if company_roles._clean(e))
