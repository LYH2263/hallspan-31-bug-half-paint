import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import halves_to_dict, place_halves
from app.services.page_rollup import mix_stats, mix_violations
router = APIRouter(prefix="/seating", tags=["seating"])


def execute_seating(db: Session, hall_id: int, pinned: bool = False) -> tuple[dict | None, list[str]]:
    """提交一次排座：分界列在提交瞬间切开两本账，两本账与最新方案同成功或同失败。

    每次提交先撤掉该考室上一轮的试行方案（写一半就把分界和图一起撤掉）：
    - 成功：写入一条新方案（含左右两本账），返回 (方案, [])；
    - 失败：返回 (None, 失败消息列表)，不增方案、历史方案（pinned）不回刷。
    pinned=True 仅用于正式提交（POST /seating/run）；改界/改标记的重提交一律试行。
    """
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id, "side": c.side}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id).order_by(Candidate.id)).all()]
    try:
        result = place_halves(hall.rows, hall.cols, hall.boundary_col, hall.min_manhattan, cands)
    except ValueError:
        raise HTTPException(400, "分界列越界")
    # 撤掉上一轮试行方案：失败即清空试行，成功则以新方案取而代之；历史方案不动
    db.execute(delete(SeatPlan).where(SeatPlan.hall_id == hall_id, SeatPlan.pinned.is_(False)))
    if not result.ok:
        db.commit()
        return None, [e.message for e in result.errors]
    data = halves_to_dict(result, hall.rows, hall.cols, hall.boundary_col, hall.min_manhattan)
    data["hall"] = {"id": hall.id, "name": hall.name,
                    "min_manhattan": hall.min_manhattan, "boundary_col": hall.boundary_col}
    plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(), pinned=pinned,
                    result_json=json.dumps(data, ensure_ascii=False))
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": plan.id, **data}, []


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    # 正式提交：成功落库为历史方案（pinned），失败不增方案
    data, errors = execute_seating(db, hall_id, pinned=True)
    if errors:
        raise HTTPException(400, detail=errors)
    return data


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    return {"id": plan.id, **data}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **mix_violations(data)}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **mix_stats(data)}
