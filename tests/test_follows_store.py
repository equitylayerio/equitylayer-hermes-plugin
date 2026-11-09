from datetime import datetime, timezone

import pytest

from equitylayer_plugin.follows import FollowStore, build_record, is_due

CARD = {"follow_id": "follow_" + "a" * 32, "pack_id": "tw-monthly-revenue", "version": "2026-09"}


def test_round_trip_survives_a_new_store_instance(tmp_path):
    record = build_record(CARD, {"next_check_at": "2026-11-10", "next_check_reason": "next_release_due"})
    FollowStore(tmp_path).save(record)
    again = FollowStore(tmp_path).get(CARD["follow_id"])
    assert again["follow_card"] == CARD
    assert again["next_check_at"] == "2026-11-10"
    assert (tmp_path / "follows" / f"{CARD['follow_id']}.json").exists()


def test_write_leaves_no_temp_files(tmp_path):
    FollowStore(tmp_path).save(build_record(CARD))
    assert [p.name for p in (tmp_path / "follows").iterdir()] == [f"{CARD['follow_id']}.json"]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "follow_xyz", "", None, "follow_" + "a" * 32 + "/x"])
def test_path_traversal_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        FollowStore(tmp_path).get(bad)


def test_corrupt_file_is_reported_not_fatal(tmp_path):
    store = FollowStore(tmp_path)
    store.save(build_record(CARD))
    (tmp_path / "follows" / ("follow_" + "b" * 32 + ".json")).write_text("{not json")
    records, unreadable = store.all()
    assert [r["follow_id"] for r in records] == [CARD["follow_id"]]
    assert unreadable == ["follow_" + "b" * 32 + ".json"]


def test_find_target_and_delete(tmp_path):
    store = FollowStore(tmp_path)
    store.save(build_record(CARD))
    assert store.find_target("pack", "tw-monthly-revenue")["follow_id"] == CARD["follow_id"]
    assert store.find_target("view", "tw-monthly-revenue") is None
    assert store.delete(CARD["follow_id"]) is True
    assert store.delete(CARD["follow_id"]) is False


def test_due_uses_taipei_dates():
    # 2026-11-09 16:30 UTC is already 2026-11-10 in Taipei.
    assert is_due("2026-11-10", datetime(2026, 11, 9, 16, 30, tzinfo=timezone.utc))
    assert not is_due("2026-11-10", datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc))
    assert is_due(None)
