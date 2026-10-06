import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_ON_EMPTY"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import Candidate, Hall
from app.services.seed import seed_if_empty
from sqlalchemy import select


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
    # 分界列 4：右半场 5x2 间距 2 最多坐 5 人，6 人放不下 → 分界列与两本账、最新方案同失败
    res = client.put("/api/halls/1", json={"boundary_col": 4})
    assert res.status_code == 200
    body = res.json()
    assert body["boundary_col"] == 3  # 写一半连分界列一起撤，返回值仍是旧界
    assert client.get("/api/halls").json()[0]["boundary_col"] == 3
    assert body["seating"]["ok"] is False
    assert body["seating"]["errors"] == ["间距不足"]
    assert _latest_id() == old_id
    # 再改成 3：同成功，新界与两本账一起落库，历史方案行不回刷、不改字
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
    # 先把 8 个未标记的人补成 6 左 6 右（每次只动一个，未标记的人逐次吸收，差始终 <= 1）
    left_extra = [c for c in cands if c["side"] is None][0:4]
    right_extra = [c for c in cands if c["side"] is None][4:8]
    for c in left_extra:
        assert _set_side(c["id"], "L").json()["seating"]["ok"] is True
    for c in right_extra:
        assert _set_side(c["id"], "R").json()["seating"]["ok"] is True
    assert _latest_id() != plan_id
    balanced_id = _latest_id()
    # 把一个右标记翻成左：7 左 5 右，已无未标记可消化，差 2 > 1 → 整场失败
    flip = right_extra[-1]
    res = _set_side(flip["id"], "L")
    assert res.status_code == 200
    body = res.json()
    assert body["side"] == "R"  # 写一半连标记一起撤：返回值仍是旧标记
    assert body["seating"]["ok"] is False
    assert body["seating"]["errors"] == ["左右半场已座人数之差大于 1"]
    # 不增方案，历史方案不回刷；库里的标记也回到 R
    assert _latest_id() == balanced_id
    flipped = next(c for c in client.get("/api/candidates").json() if c["id"] == flip["id"])
    assert flipped["side"] == "R"
    # 重新标回 R（本就是 R，等于再提交一次）→ 两本账恢复成功
    assert _set_side(flip["id"], "R").json()["seating"]["ok"] is True
    assert _latest_id() != balanced_id


def test_half_capacity_message_not_merged_with_spacing():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    cands = client.get("/api/candidates").json()
    # 直接构造：分界列 1（左账容量 5）+ 6 人标左。这种状态无法靠逐人改标到达
    # （中途的不平衡态会被原子回滚挡下），故在库内一次写就后再提交排座。
    db = SessionLocal()
    try:
        hall = db.get(Hall, 1)
        hall.boundary_col = 1
        for c in db.scalars(select(Candidate)).all():
            c.side = None
        for c in db.scalars(select(Candidate).where(Candidate.id.in_([c["id"] for c in cands[:6]]))).all():
            c.side = "L"
        db.commit()
    finally:
        db.close()
    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 400
    errors = res.json()["detail"]
    assert errors == ["半场座位不足"]
    assert all("间距不足" not in m for m in errors)  # 不得与间距不足并句
    assert _latest_id() == plan_id  # 失败不增方案
    # 清理：恢复种子状态后再提交
    db = SessionLocal()
    try:
        db.get(Hall, 1).boundary_col = 3
        for c in db.scalars(select(Candidate)).all():
            c.side = None
        c = db.scalars(select(Candidate).order_by(Candidate.id)).all()
        c[0].side, c[1].side, c[2].side, c[3].side = "L", "L", "R", "R"
        db.commit()
    finally:
        db.close()
    assert client.post("/api/seating/run?hall_id=1").status_code == 200


def test_candidate_side_validation():
    res = client.put("/api/candidates/1", json={"side": "X"})
    assert res.status_code == 400
    assert "左右标记非法" in res.text


def test_run_failure_returns_messages_and_no_plan():
    client.post("/api/seating/run?hall_id=1")
    plan_id = _latest_id()
    cands = client.get("/api/candidates").json()
    # 12 人全左：左账容量 15 够，但 5x3 间距 2 放不下 → 间距不足（库内直接构造）
    db = SessionLocal()
    try:
        for c in db.scalars(select(Candidate)).all():
            c.side = "L"
        db.commit()
    finally:
        db.close()
    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 400
    assert res.json()["detail"] == ["间距不足"]
    assert _latest_id() == plan_id
    # 恢复种子标记
    db = SessionLocal()
    try:
        c = db.scalars(select(Candidate).order_by(Candidate.id)).all()
        c[0].side, c[1].side, c[2].side, c[3].side = "L", "L", "R", "R"
        for x in c[4:]:
            x.side = None
        db.commit()
    finally:
        db.close()
