import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_ON_EMPTY"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.seed import seed_if_empty


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


client = TestClient(app)


def _latest_id() -> int:
    return client.get("/api/seating/latest?hall_id=1").json()["id"]


def _set_side(cid: int, side):
    return client.put(f"/api/candidates/{cid}", json={"side": side})


def test_seed_hall_has_boundary_3():
    halls = client.get("/api/halls").json()
    assert halls[0]["boundary_col"] == 3
    assert halls[0]["cols"] == 6


def test_run_writes_two_ledgers_one_source():
    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["boundary_col"] == 3
    left, right = data["ledgers"]["left"], data["ledgers"]["right"]
    # 种子分界列 3：左账不得出现列号 >= 3 的人
    assert all(a["col"] < 3 for a in left)
    assert all(a["col"] >= 3 for a in right)
    # 排座图、左账、右账、统计同一套
    assert data["assignments"] == left + right
    assert data["stats"]["left_seated"] == len(left)
    assert data["stats"]["right_seated"] == len(right)
    assert data["stats"]["seated"] == len(left) + len(right)
    assert abs(len(left) - len(right)) <= 1
    # 12 名考生全部归入且只归入一本账
    ids = [a["candidate_id"] for a in data["assignments"]]
    assert len(ids) == len(set(ids)) == 12


def test_stats_share_same_ledgers():
    client.post("/api/seating/run?hall_id=1")
    latest = client.get("/api/seating/latest?hall_id=1").json()
    stats = client.get("/api/seating/stats?hall_id=1").json()
    assert stats["left_seated"] == len(latest["ledgers"]["left"])
    assert stats["right_seated"] == len(latest["ledgers"]["right"])
    assert stats["seated"] == stats["left_seated"] + stats["right_seated"]


def test_boundary_out_of_range_rejected_three_places_untouched():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    for bad in (0, -1, 6, 99):
        res = client.put("/api/halls/1", json={"boundary_col": bad})
        assert res.status_code == 400
        assert "分界列越界" in res.text
    # 三处不动：考室分界列、左账、右账（最新方案）都保持原样
    assert client.get("/api/halls").json()[0]["boundary_col"] == 3
    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest["id"] == plan_id
    assert latest["boundary_col"] == 3


def test_boundary_change_reruns_atomically():
    client.post("/api/seating/run?hall_id=1")
    old_id = _latest_id()
    # 分界列 4：右半场 5x2 间距 2 最多坐 5 人，6 人放不下 → 两本账与最新方案同失败
    res = client.put("/api/halls/1", json={"boundary_col": 4})
    assert res.status_code == 200
    body = res.json()
    assert body["boundary_col"] == 4  # 数据变更保存，但方案不增
    assert body["seating"]["ok"] is False
    assert body["seating"]["errors"] == ["间距不足"]
    assert _latest_id() == old_id
    # 改回 3：同成功，新方案与两本账一起落库，历史方案不回刷
    res = client.put("/api/halls/1", json={"boundary_col": 3})
    assert res.json()["seating"]["ok"] is True
    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest["id"] != old_id
    assert latest["boundary_col"] == 3
    assert all(a["col"] < 3 for a in latest["ledgers"]["left"])
    assert all(a["col"] >= 3 for a in latest["ledgers"]["right"])


def test_mark_change_failure_adds_no_plan_and_keeps_history():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    cands = client.get("/api/candidates").json()
    last = None
    # 8 左 4 右：合账差 4 > 1 且账内无法消化 → 整场失败
    for i, c in enumerate(cands):
        last = _set_side(c["id"], "L" if i < 8 else "R")
    assert last.status_code == 200
    assert last.json()["seating"]["ok"] is False
    assert last.json()["seating"]["errors"] == ["左右半场已座人数之差大于 1"]
    # 不增方案，历史方案不回刷
    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest["id"] == plan_id
    assert latest["boundary_col"] == 3
    # 改回未标记 → 同一次提交里两本账恢复成功
    for c in cands:
        last = _set_side(c["id"], None)
    assert last.json()["seating"]["ok"] is True
    assert _latest_id() != plan_id


def test_half_capacity_message_not_merged_with_spacing():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    # 分界列改为 1：左账容量 5；再标记 6 人左 → 半场座位不足
    assert client.put("/api/halls/1", json={"boundary_col": 1}).status_code == 200
    cands = client.get("/api/candidates").json()
    last = None
    for c in cands[:6]:
        last = _set_side(c["id"], "L")
    errors = last.json()["seating"]["errors"]
    assert errors == ["半场座位不足"]
    assert all("间距不足" not in m for m in errors)  # 不得与间距不足并句
    assert _latest_id() == plan_id  # 失败不增方案
    # 清理：恢复种子状态
    for c in cands[:6]:
        _set_side(c["id"], None)
    res = client.put("/api/halls/1", json={"boundary_col": 3})
    assert res.json()["seating"]["ok"] is True


def test_candidate_side_validation():
    res = client.put("/api/candidates/1", json={"side": "X"})
    assert res.status_code == 400
    assert "左右标记非法" in res.text


def test_run_failure_returns_messages_and_no_plan():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    cands = client.get("/api/candidates").json()
    for c in cands:
        _set_side(c["id"], "L")  # 12 人全左：左账容量 15 够，但 5x3 间距 2 放不下 → 间距不足
    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 400
    assert res.json()["detail"] == ["间距不足"]
    assert _latest_id() == plan_id
    for c in cands:
        _set_side(c["id"], None)
