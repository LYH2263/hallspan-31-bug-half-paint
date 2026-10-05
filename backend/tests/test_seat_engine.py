import pytest

from app.services.seat_engine import (
    MSG_HALF_CAPACITY,
    MSG_IMBALANCE,
    MSG_SPACING,
    SeatAssign,
    find_violations,
    halves_to_dict,
    manhattan,
    place_candidates,
    place_halves,
)

def test_manhattan():
    assert manhattan((0, 0), (2, 1)) == 3

def test_min_distance_placement():
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{i}", "paper_id": 1 + (i % 2)} for i in range(4)]
    assigns, unplaced = place_candidates(4, 4, 2, cands)
    assert len(assigns) + len(unplaced) == 4
    for i, a in enumerate(assigns):
        for b in assigns[i+1:]:
            assert manhattan((a.row, a.col), (b.row, b.col)) >= 2

def test_same_paper_not_adjacent_in_result():
    # Force two same paper — engine should avoid 4-neigh
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T1", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T2", "paper_id": 1},
        {"id": 3, "name": "C", "ticket_no": "T3", "paper_id": 2},
    ]
    assigns, _ = place_candidates(3, 3, 1, cands)
    viols = find_violations(3, 3, 1, assigns)
    assert not any(v.kind == "same_paper_adjacent" for v in viols)

def test_violation_detection():
    assigns = [
        SeatAssign(1, "A", "T1", 1, 0, 0),
        SeatAssign(2, "B", "T2", 1, 0, 1),
    ]
    viols = find_violations(2, 2, 2, assigns)
    kinds = {v.kind for v in viols}
    assert "distance" in kinds
    assert "same_paper_adjacent" in kinds


# ---------- 左右半场两本账 ----------

def mk(i, side=None, paper=1):
    return {"id": i, "name": f"C{i}", "ticket_no": f"T{i}", "paper_id": paper, "side": side}


def test_halves_seed_boundary_left_ledger_cols():
    # 种子场景：分界列 3，左账不得出现列号 >= 3 的人，右账不得出现列号 < 3 的人
    cands = [mk(i, side=(["L", "L", "R", "R"] + [None] * 8)[i], paper=1 + (i % 3)) for i in range(12)]
    res = place_halves(5, 6, 3, 2, cands)
    assert res.ok, [e.message for e in res.errors]
    assert res.left.seated + res.right.seated == 12
    for a in res.left.assignments():
        assert a.col < 3 and a.side == "L"
    for a in res.right.assignments():
        assert a.col >= 3 and a.side == "R"
    assert abs(res.left.seated - res.right.seated) <= 1


def test_unmarked_assigned_to_exactly_one_ledger():
    cands = [mk(i) for i in range(5)]  # 全部未标记
    res = place_halves(3, 4, 2, 1, cands)
    assert res.ok
    left_ids = {a.candidate_id for a in res.left.assignments()}
    right_ids = {a.candidate_id for a in res.right.assignments()}
    assert not (left_ids & right_ids)            # 只归入一本账
    assert left_ids | right_ids == set(range(5))  # 必须归入一本账


def test_marked_never_moved_to_opposite_ledger():
    # 左账容量 2，3 个左标记：宁可报半场座位不足，也不许跨到右账凑数
    cands = [mk(i, side="L") for i in range(3)]
    res = place_halves(1, 4, 2, 1, cands)
    assert not res.ok
    assert [e.message for e in res.errors] == [MSG_HALF_CAPACITY]
    assert res.left.seated == 0 and res.right.seated == 0  # 失败即整场失败，账不入库


def test_spacing_message_not_merged_with_half_capacity():
    # 左账容量够（2 人 2 座）但间距放不下：只写间距不足，不得与半场座位不足并句
    cands = [mk(1, side="L"), mk(2, side="L")]
    res = place_halves(1, 4, 2, 2, cands)
    assert not res.ok
    messages = [e.message for e in res.errors]
    assert messages == [MSG_SPACING]
    assert MSG_HALF_CAPACITY not in messages


def test_imbalance_fails_whole_hall():
    # 2 左 0 右，差 2 > 1，账内无法消化 → 整场失败
    cands = [mk(1, side="L"), mk(2, side="L")]
    res = place_halves(2, 4, 2, 1, cands)
    assert not res.ok
    assert [e.message for e in res.errors] == [MSG_IMBALANCE]


def test_imbalance_absorbed_by_unmarked_within_ledgers():
    # 2 左标记 + 2 未标记：未标记归右账后 2v2 均衡，允许成功
    cands = [mk(1, side="L"), mk(2, side="L"), mk(3), mk(4)]
    res = place_halves(2, 4, 2, 1, cands)
    assert res.ok
    assert res.left.seated == 2 and res.right.seated == 2


def test_boundary_out_of_range_rejected():
    for bad in (0, -1, 6, 7):
        with pytest.raises(ValueError):
            place_halves(5, 6, bad, 2, [mk(1)])


def test_ledgers_independent_not_single_map_split():
    # 两本账独立记账：跨分界列的四邻同卷不构成违规（若是单图后切分则会报违规）
    cands = [mk(1, side="L", paper=7), mk(2, side="R", paper=7)]
    res = place_halves(1, 2, 1, 1, cands)
    assert res.ok
    assert res.left.assignments()[0].row == 0 and res.left.assignments()[0].col == 0
    assert res.right.assignments()[0].row == 0 and res.right.assignments()[0].col == 1
    data = halves_to_dict(res, 1, 2, 1, 1)
    assert data["violations"] == []


def test_halves_to_dict_single_source():
    # 排座图、左账、右账、统计同一套
    cands = [mk(i, side=(["L", "R"] + [None] * 4)[i]) for i in range(6)]
    res = place_halves(3, 4, 2, 1, cands)
    assert res.ok
    data = halves_to_dict(res, 3, 4, 2, 1)
    left, right = data["ledgers"]["left"], data["ledgers"]["right"]
    assert data["assignments"] == left + right
    assert data["stats"]["left_seated"] == len(left)
    assert data["stats"]["right_seated"] == len(right)
    assert data["stats"]["seated"] == len(left) + len(right)
    assert all(a["col"] < 2 for a in left)
    assert all(a["col"] >= 2 for a in right)
