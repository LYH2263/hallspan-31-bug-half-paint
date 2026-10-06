from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall
from app.api.seating import execute_seating
router = APIRouter(prefix="/halls", tags=["halls"])


class HallUpdate(BaseModel):
    boundary_col: int


def hall_dict(r: Hall) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "rows": r.rows, "cols": r.cols,
            "min_manhattan": r.min_manhattan, "boundary_col": r.boundary_col}


@router.get("")
def list_halls(db: Session = Depends(get_db)):
    return [hall_dict(r) for r in db.scalars(select(Hall).order_by(Hall.id)).all()]


@router.put("/{hall_id}")
def update_hall(hall_id: int, body: HallUpdate, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    # 分界列越界拒绝保存：两本账与最新方案三处不动
    if not 1 <= body.boundary_col < hall.cols:
        raise HTTPException(400, "分界列越界")
    hall.boundary_col = body.boundary_col
    db.commit(); db.refresh(hall)
    # 改分界列后重提交：两本账与最新方案同成功或同失败，历史方案不回刷
    data, errors = execute_seating(db, hall_id)
    out = hall_dict(hall)
    out["seating"] = {"ok": not errors, "errors": errors,
                      "plan_id": data["id"] if data else None}
    return out
