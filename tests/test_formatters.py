from support import fixture_text

from equitylayer_plugin import formatters
from equitylayer_plugin.mcp_client import extract_tool_payload, parse_rpc_response


def payload(name):
    return extract_tool_payload(parse_rpc_response("text/event-stream", fixture_text(name), 1)["result"])


def test_pack_markdown_has_figures_and_source_attribution():
    text = formatters.format_pack(payload("get_research_pack"))
    assert "tw-monthly-revenue" in text
    assert "台光電" in text
    assert "21,532,230" in text  # published value, unscaled
    assert "+6.88%" in text
    assert "Taiwan Stock Exchange (臺灣證券交易所)" in text
    assert "https://openapi.twse.com.tw/v1/opendata/t187ap05_L" in text
    assert "not human-reviewed" in text
    assert "Not investment advice" in text


def test_pack_markdown_limits_records():
    text = formatters.format_pack(payload("get_research_pack"), max_records=1)
    assert "Showing 1 of 3 records." in text
    assert "欣興" not in text.split("### Public claims")[0].split("### Records")[1]


def test_pack_tolerates_unknown_shape():
    text = formatters.format_pack({"pack_id": "future", "records": [{"a": 1, "nested": {}}], "source": "text source"})
    assert "future" in text and "text source" in text and "| a |" in text


def test_format_v1_hypotheses_and_not_covered():
    text = formatters.format_pack(
        {"pack_id": "p", "hypotheses": [{"id": "h1", "statement": "S", "confidence": "low"}], "not_covered": ["Q"]}
    )
    assert "Publisher hypotheses" in text and "| h1 | S | low |" in text and "- Q" in text


def test_scorecard_is_a_short_card_with_resolution_counts():
    text = formatters.format_scorecard(payload("get_pack_scorecard_view"))
    assert "2 total: 2 confirmed, 0 missed, 0 mixed, 0 open" in text
    assert "fresh, 0 days overdue" in text
    assert "Not a recommendation" in text
    assert "Cite as: EquityLayer Research." in text


def test_table_cells_cannot_break_out_of_a_row():
    assert formatters._cell("a|b\nc") == "a\\|b c"
    assert formatters._cell(None) == "—"
    assert formatters._cell(0) == "0"



def test_registry_marks_in_review_entries_as_not_published():
    from equitylayer_plugin.formatters import format_registry

    text = format_registry([{"id": "cpo-pack", "title": "CPO Pack", "status": "in_review", "kind": "in_review"}])
    assert "in review, not published yet" in text and "can't be read or followed" in text
    assert "ask to read or follow" not in text



def test_pack_format_v1_shows_view_hypotheses_and_sources():
    import json
    from support import fixture_text
    from equitylayer_plugin.formatters import format_pack

    line = [l for l in fixture_text("get_research_pack_cpo_v1").splitlines() if l.startswith("data: ")][0][6:]
    pack = json.loads(json.loads(line)["result"]["content"][0]["text"])
    text = format_pack(pack)
    assert "What Taiwan's optical suppliers report" in text and "**View:**" in text
    assert "LandMark, a laser epi supplier" in text and "Would be wrong if:" in text and "`v:3081.two.revenue.monthly`" in text
    assert "(management claim)" in text and "Not covered" in text and "Cite as:" in text
    assert "sha256:" not in text.split("## Evidence")[0] and "https://" not in text



def test_pack_format_v1_survives_odd_provenance_and_many_sources():
    from equitylayer_plugin.formatters import format_pack

    pack = {"view": "A view.", "claims": [{"assertion": {"statement": "S", "kind": "reported_fact"}, "provenance": "x"},
                                          {"assertion": {"statement": "T"}, "provenance": {"source_ids": [None, "S1", 2]}}],
            "sources": [{"id": f"S{i}", "publisher": "P"} for i in range(15)]}
    text = format_pack(pack)
    assert "(reported fact) S" in text and "[S1, 2]" in text and "…and 3 more on the Pack page." in text
