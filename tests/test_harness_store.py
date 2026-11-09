import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from equitylayer_plugin.harness_store import HarnessStore, is_due, slugify, summarize_check
from support import fixture_text

HARNESS = json.loads((Path(__file__).parent / "harness_demo.json").read_text())["harness"]


def payload(name):
    line = next(l for l in fixture_text(name).splitlines() if l.startswith("data:"))
    return json.loads(json.loads(line[5:])["result"]["content"][0]["text"])


def test_slugify_is_file_safe():
    assert slugify("CPO reaches volume by end-2027!") == "cpo-reaches-volume-by-end-2027"
    assert slugify("共封裝光學") == "thesis"
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert len(slugify("x" * 200)) == 48


def test_round_trip_survives_a_new_store_instance(tmp_path):
    record, created = HarnessStore(tmp_path).save_harness("cpo", HARNESS)
    assert created and record["baseline"] is None and record["history"] == []
    again = HarnessStore(tmp_path).get("cpo")
    assert again["harness"] == HARNESS
    assert again["title"] == HARNESS["title"]
    assert [p.name for p in (tmp_path / "harnesses").iterdir()] == ["cpo.json"]


def test_replacing_text_keeps_baseline_and_history(tmp_path):
    store = HarnessStore(tmp_path)
    store.save_harness("cpo", HARNESS)
    store.record_check("cpo", payload("check_harness_first"), seen=True)
    edited = {**HARNESS, "why": "Changed reasoning."}
    record, created = store.save_harness("cpo", edited)
    assert not created
    assert record["harness"]["why"] == "Changed reasoning."
    assert record["baseline"]["taken_at"] == "2026-11-09"
    assert len(record["history"]) == 1


def test_unique_id_does_not_overwrite(tmp_path):
    store = HarnessStore(tmp_path)
    first = store.unique_id(HARNESS["title"])
    store.save_harness(first, HARNESS)
    second = store.unique_id(HARNESS["title"])
    assert second == first + "-2"


@pytest.mark.parametrize("bad", ["../x", "a/b", "", None, "UPPER", "x" * 49, ".hidden"])
def test_path_traversal_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        HarnessStore(tmp_path).get(bad)


def test_unseen_check_stays_pending_until_marked_seen(tmp_path):
    store = HarnessStore(tmp_path)
    store.save_harness("cpo", HARNESS)
    record = store.record_check("cpo", payload("check_harness_first"), seen=False)
    assert record["baseline"] is None
    assert record["pending_baseline"]["taken_at"] == "2026-11-09"
    promoted = store.mark_seen("cpo")
    assert promoted["baseline"]["taken_at"] == "2026-11-09" and promoted["pending_baseline"] is None
    assert store.mark_seen("cpo") is None


def test_history_is_capped(tmp_path):
    store = HarnessStore(tmp_path)
    store.save_harness("cpo", HARNESS)
    for _ in range(35):
        store.record_check("cpo", payload("check_harness_first"), seen=True)
    assert len(store.get("cpo")["history"]) == 30


def test_summary_keeps_counts_not_readings():
    summary = summarize_check(payload("check_harness_first"))
    assert summary["links"] == {"foci-ramp": "seen", "coherent-dc": "seen", "lumentum-cpo": "no_data"}
    assert summary["counts"]["seen"] == 2 and summary["counts"]["no_data"] == 1
    assert summary["needs_human"] == 1 and summary["wrong_if_fired"] == []
    assert summary["next_due"] == "2026-11-10"
    assert "224257" not in json.dumps(summary)
    assert summarize_check(payload("check_harness_changed"))["variables_changed"] == 2


def test_corrupt_file_is_reported_not_fatal(tmp_path):
    store = HarnessStore(tmp_path)
    store.save_harness("cpo", HARNESS)
    (tmp_path / "harnesses" / "broken.json").write_text("{not json")
    records, unreadable = store.all()
    assert [r["id"] for r in records] == ["cpo"]
    assert unreadable == ["broken.json"]


def test_due_uses_taipei_dates():
    record = {"last_check": {"next_due": "2026-11-10"}}
    # 2026-11-09 16:30 UTC is already 2026-11-10 in Taipei.
    assert is_due(record, datetime(2026, 11, 9, 16, 30, tzinfo=timezone.utc))
    assert not is_due(record, datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc))
    assert is_due({"last_check": None})
    assert is_due({"last_check": {"next_due": None}})
