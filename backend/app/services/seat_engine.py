"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent.

左右半场两本账：分界列把考室切成左 [0, boundary_col) 与右 [boundary_col, cols) 两本
独立占用账。提交排座瞬间两本账各自独立放置、各自记账（双写）；不是先排一张总图
再按列涂色冒充两本账。排座图、左账人数、右账人数、统计都从这两本账导出。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field

# 失败消息各自独立成句：半场座位不足不得与间距不足并句。
MSG_HALF_CAPACITY = "半场座位不足"
MSG_SPACING = "间距不足"
MSG_IMBALANCE = "左右半场已座人数之差大于 1"

SIDE_LEFT = "L"
SIDE_RIGHT = "R"


@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int
    side: str = ""  # 账本归属："L" 左账 / "R" 右账 / "" 不分账（整场直排）


@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str


@dataclass
class SeatError:
    kind: str      # half_capacity | spacing | imbalance
    half: str      # "L" | "R" | ""（整场/两账共同）
    message: str


@dataclass
class HalfLedger:
    """半场占用账：一本账只记自己列范围内的座位，越列记账直接拒绝。"""
    side: str
    rows: int
    col_start: int
    col_end: int  # 不含
    occupied: dict[tuple[int, int], SeatAssign] = field(default_factory=dict)

    @property
    def capacity(self) -> int:
        return self.rows * (self.col_end - self.col_start)

    @property
    def seated(self) -> int:
        return len(self.occupied)

    def write(self, assign: SeatAssign) -> None:
        """记账：座位必须落在本账列范围内。"""
        if not (self.col_start <= assign.col < self.col_end):
            raise ValueError(f"列 {assign.col} 不在{self.side}账列范围 [{self.col_start}, {self.col_end})")
        self.occupied[(assign.row, assign.col)] = assign

    def assignments(self) -> list[SeatAssign]:
        return list(self.occupied.values())


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out


def _seat_ok(occupied: dict[tuple[int, int], SeatAssign], r: int, c: int,
             min_dist: int, paper_id: int) -> bool:
    for pos, other in occupied.items():
        d = manhattan((r, c), pos)
        if d < min_dist:
            return False
        if other.paper_id == paper_id and d == 1:  # 四邻即曼哈顿距离 1
            return False
    return True


def _place_into_ledger(ledger: HalfLedger, min_dist: int, candidates: list[dict]) -> list[dict]:
    """在一本账的列范围内贪心落座、逐笔记账；返回放不下的人。"""
    unplaced: list[dict] = []
    for cand in candidates:
        placed = False
        for r in range(ledger.rows):
            for c in range(ledger.col_start, ledger.col_end):
                if (r, c) in ledger.occupied:
                    continue
                if not _seat_ok(ledger.occupied, r, c, min_dist, cand["paper_id"]):
                    continue
                ledger.write(SeatAssign(cand["id"], cand["name"], cand["ticket_no"],
                                        cand["paper_id"], r, c, ledger.side))
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    return unplaced


def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict]) -> tuple[list[SeatAssign], list[dict]]:
    """Greedy: try seats row-major; accept if manhattan >= min_dist to all placed AND no same paper 4-neigh."""
    ledger = HalfLedger(side="", rows=rows, col_start=0, col_end=cols)
    unplaced = _place_into_ledger(ledger, min_dist, candidates)
    return ledger.assignments(), unplaced


def split_pools(candidates: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """按左右标记分池：左标记进左池、右标记进右池、未标记单独成池。"""
    left = [c for c in candidates if c.get("side") == SIDE_LEFT]
    right = [c for c in candidates if c.get("side") == SIDE_RIGHT]
    unmarked = [c for c in candidates if c.get("side") not in (SIDE_LEFT, SIDE_RIGHT)]
    return left, right, unmarked


@dataclass
class HalvesResult:
    """一次提交的两本账。errors 非空即整场失败，账与方案都不应落库。"""
    left: HalfLedger
    right: HalfLedger
    errors: list[SeatError] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def place_halves(rows: int, cols: int, boundary_col: int, min_dist: int,
                 candidates: list[dict]) -> HalvesResult:
    """提交排座：分界列切开两本账，两账各自独立放置、各自记账。

    - 已标记左右的人只进自己那本账，禁止为凑均衡记进对面账；
    - 未标记的人在该次提交里归入且只归入一本账（归向人较少且仍有空位的账）；
    - 半场座位不足与间距不足各自独立成句；
    - 合账已座人数之差大于 1 则整场失败。
    """
    if not 1 <= boundary_col < cols:
        raise ValueError("分界列越界")
    left_ledger = HalfLedger(SIDE_LEFT, rows, 0, boundary_col)
    right_ledger = HalfLedger(SIDE_RIGHT, rows, boundary_col, cols)
    result = HalvesResult(left_ledger, right_ledger)

    left_pool, right_pool, unmarked = split_pools(candidates)

    # 1) 半场容量：已标记的人不许跨账，先核两账各自容量
    if len(left_pool) > left_ledger.capacity:
        result.errors.append(SeatError("half_capacity", SIDE_LEFT, MSG_HALF_CAPACITY))
    if len(right_pool) > right_ledger.capacity:
        result.errors.append(SeatError("half_capacity", SIDE_RIGHT, MSG_HALF_CAPACITY))
    if result.errors:
        return result

    # 2) 未标记的人：该次提交里归入且只归入一本账
    for cand in unmarked:
        can_l = len(left_pool) < left_ledger.capacity
        can_r = len(right_pool) < right_ledger.capacity
        if can_l and (not can_r or len(left_pool) <= len(right_pool)):
            left_pool.append(cand)
        elif can_r:
            right_pool.append(cand)
        else:
            result.errors.append(SeatError("half_capacity", "", MSG_HALF_CAPACITY))
            break
    if result.errors:
        return result

    # 3) 两本账各自独立放置、各自记账（双写，不是单图后切分）
    unplaced_left = _place_into_ledger(left_ledger, min_dist, left_pool)
    unplaced_right = _place_into_ledger(right_ledger, min_dist, right_pool)
    result.unplaced = unplaced_left + unplaced_right
    if unplaced_left:
        result.errors.append(SeatError("spacing", SIDE_LEFT, MSG_SPACING))
    if unplaced_right:
        result.errors.append(SeatError("spacing", SIDE_RIGHT, MSG_SPACING))
    if result.errors:
        return result

    # 4) 合账均衡：两账已座人数之差大于 1 且无法在账内消化 → 整场失败
    if abs(left_ledger.seated - right_ledger.seated) > 1:
        result.errors.append(SeatError("imbalance", "", MSG_IMBALANCE))
    return result


def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
    return viols


def halves_to_dict(result: HalvesResult, rows: int, cols: int, boundary_col: int,
                   min_dist: int) -> dict:
    """排座图、左账、右账、统计同一套：全部由两本账导出。"""
    left_assigns = result.left.assignments()
    right_assigns = result.right.assignments()
    assignments = left_assigns + right_assigns
    viols = (find_violations(rows, cols, min_dist, left_assigns)
             + find_violations(rows, cols, min_dist, right_assigns))
    return {
        "rows": rows,
        "cols": cols,
        "boundary_col": boundary_col,
        "assignments": [asdict(a) for a in assignments],
        "ledgers": {
            "left": [asdict(a) for a in left_assigns],
            "right": [asdict(a) for a in right_assigns],
        },
        "unplaced": result.unplaced,
        "violations": [asdict(v) for v in viols],
        "stats": {
            "seated": len(assignments),
            "left_seated": len(left_assigns),
            "right_seated": len(right_assigns),
            "unplaced": len(result.unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
        },
    }


def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation], rows: int, cols: int) -> dict:
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
        },
    }
