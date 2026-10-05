from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate
from app.api.seating import execute_seating
router = APIRouter(prefix="/candidates", tags=["candidates"])


class CandidateUpdate(BaseModel):
    side: str | None = None  # L 左账 / R 右账 / null 未标记


def candidate_dict(r: Candidate) -> dict:
    return {"id": r.id, "hall_id": r.hall_id, "name": r.name, "ticket_no": r.ticket_no,
            "paper_id": r.paper_id, "side": r.side}


@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [candidate_dict(r) for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]


@router.put("/{candidate_id}")
def update_candidate(candidate_id: int, body: CandidateUpdate, db: Session = Depends(get_db)):
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "考生不存在")
    side = body.side or None
    if side not in (None, "L", "R"):
        raise HTTPException(400, "左右标记非法")
    cand.side = side
    db.commit(); db.refresh(cand)
    # 改标记后重提交：两本账与最新方案同成功或同失败，历史方案不回刷
    data, errors = execute_seating(db, cand.hall_id)
    out = candidate_dict(cand)
    out["seating"] = {"ok": not errors, "errors": errors,
                      "plan_id": data["id"] if data else None}
    return out
