import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import halves_to_dict, place_halves
from app.services.page_rollup import mix_stats, mix_violations
router = APIRouter(prefix="/seating", tags=["seating"])


def execute_seating(db: Session, hall_id: int) -> tuple[dict | None, list[str]]:
    """提交一次排座：分界列在提交瞬间切开两本账，两本账与最新方案同成功或同失败。

    成功：写入一条新方案（含左右两本账），返回 (方案, [])；
    失败：返回 (None, 失败消息列表)，不增方案、历史方案不回刷。
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
    if not result.ok:
        return None, [e.message for e in result.errors]
    data = halves_to_dict(result, hall.rows, hall.cols, hall.boundary_col, hall.min_manhattan)
    data["hall"] = {"id": hall.id, "name": hall.name,
                    "min_manhattan": hall.min_manhattan, "boundary_col": hall.boundary_col}
    plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(),
                    result_json=json.dumps(data, ensure_ascii=False))
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": plan.id, **data}, []


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    data, errors = execute_seating(db, hall_id)
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
