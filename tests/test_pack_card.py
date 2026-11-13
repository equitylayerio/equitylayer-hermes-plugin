"""The Research Pack card: the same fields as EquityLayer's website and in-chat card."""

SUMMARY = {
    "pack_id": "cpo-timing-and-form", "title": "Filed outlooks put the CPO volume step in 2H 2027",
    "view": "Short view.", "theme_id": "optical_cpo", "revision": "R2", "category": "thesis",
    "url": "https://equitylayer.io/research/packs/cpo-timing-and-form",
    "variables": ["v:a", "v:b", "v:c", "v:d"],
    "hypotheses": [
        {"statement": "A risk", "role": "risk", "falsifier": "Risk falsifier"},
        {"statement": "Core claim", "role": "core", "falsifier": "Core falsifier"},
    ],
}
ROWS = {
    "v:b": {"name": "B revenue", "unit": "USD million", "latest": {"period": "FY2027-Q1", "value": 508.4}, "change": "+42.4% vs FY2026-Q4"},
    "v:c": {"name": "C revenue", "unit": "TWD thousand", "latest": {"period": "2026-10", "value": None, "withheld": "grant_required"}},
    "v:d": {"name": "D revenue", "unit": "USD million", "latest": {"period": "FY2027-Q1", "value": 1951.7}, "change": "+20.8% vs FY2026-Q4"},
}


def test_card_is_built_from_the_summary_and_the_readings():
    from equitylayer_plugin import pack_card

    card = pack_card.build(SUMMARY, ROWS, "2026-12-10")
    assert card["industry"] == ["CPO and optical networking", "CPO 與光通訊"]
    assert card["card"] == "cpo-timing-and-form@R2" and card["version"] == "R2"
    assert card["follow"] == {"tool": "create_research_follow", "arguments": {"pack_id": "cpo-timing-and-form"}}
    assert card["check"]["next_check"] == "2026-12-10"
    assert card["wrong_if"] == ["Core falsifier", "Risk falsifier"]  # core first
    front = pack_card.front_variables(card)
    assert [v["id"] for v in front] == ["v:b", "v:d", "v:a"]  # readings first, withheld counts as no reading
    assert front[0]["change"] == "+42.4% vs FY2026-Q4" and front[2]["latest"] is None


def test_equitylayers_own_card_is_used_as_it_is():
    from equitylayer_plugin import pack_card

    server = {"kind": "research_pack_card", "pack_id": "p", "title": "Server title", "industry": ["X", "X"],
              "check": {"tool": "check_research_follow", "next_check": "2026-12-10"}, "watch": [], "wrong_if": []}
    card = pack_card.build(SUMMARY, ROWS, "2026-11-20", server)
    assert card["title"] == "Server title" and "kind" not in card
    assert card["check"]["next_check"] == "2026-11-20"  # the follow's own date wins
    assert pack_card.build(SUMMARY, ROWS, None, {"kind": "something_else"})["title"] == SUMMARY["title"]


def test_industry_names_match_the_dashboard_and_onboarding():
    from equitylayer_plugin import pack_card
    from equitylayer_plugin.dashboard import THEME_LABELS

    for theme, label in THEME_LABELS.items():
        if theme != "other":
            assert pack_card.INDUSTRY[theme][0] == label


def test_dashboard_shows_followed_packs_as_cards_with_changes_first():
    from equitylayer_plugin.dashboard import render

    def record(n, pid, pending=None):
        return {"follow_id": "follow_" + str(n) * 32, "target_id": pid, "next_check_at": "2099-01-01",
                "pending_review": pending,
                "pack": {**SUMMARY, "pack_id": pid, "title": f"Title {pid}", "hypotheses": SUMMARY["hypotheses"]}}

    followed = {"first": record(1, "first"), "second": record(2, "second", {"revision_changed": True})}
    page = render(None, [], [], followed=followed)
    assert '<h2 id="glance">Your Research Packs</h2>' in page
    assert page.count('class="pc-industry">CPO and optical networking<') == 2
    assert page.index("Title second") < page.index("Title first")  # a new version comes first
    assert ">New version<" in page and ">Up to date<" in page
    assert 'data-hermes-send="Show me what changed in the Pack Title second."' in page
    assert "<summary>Open the Pack</summary>" in page and "thesis-card" in page  # the fuller view folds under the card
    assert "<summary>Agent side</summary>" in page and "create_research_follow" in page
    assert "Version 2" not in page and "&quot;version&quot;: &quot;R2&quot;" in page  # the version is on the agent side only
    assert "Wrong if" in page and "Core falsifier" in page


def test_attach_card_keeps_the_server_card_or_nothing():
    from equitylayer_plugin.tools import EquityLayerTools

    class Stub:
        def __init__(self, answer):
            self.answer = answer

        def _call(self, name, arguments):
            assert name == "get_research_pack" and arguments["format"] == "card"
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    record = {"target_id": "p", "card": {"stale": True}}
    EquityLayerTools._attach_card(Stub({"kind": "research_pack_card", "pack_id": "p"}), record)
    assert record["card"]["pack_id"] == "p"
    EquityLayerTools._attach_card(Stub(RuntimeError("no card format yet")), record)
    assert "card" not in record
    EquityLayerTools._attach_card(Stub({"kind": "research_pack"}), record)
    assert "card" not in record
