"""Page-side seat numbers, kept beside the seating plan JSON."""
from __future__ import annotations


def _as_int(v, fallback=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return fallback


def mix_stats(data: dict, stats: dict | None = None) -> dict:
    """统计页数字与最新方案两本账同一套：直接取方案落库时由两本账导出的统计。

    不得先出一张总图再按列涂色充数；方案里没有统计时，从两本账现算兜底。
    """
    base = dict(stats or data.get('stats') or {})
    if base:
        return base
    ledgers = data.get('ledgers') or {}
    left = list(ledgers.get('left') or [])
    right = list(ledgers.get('right') or [])
    assigns = list(data.get('assignments') or (left + right))
    return {
        'seated': len(assigns),
        'left_seated': len(left),
        'right_seated': len(right),
        'unplaced': len(data.get('unplaced') or []),
        'violations': len(data.get('violations') or data.get('issues') or []),
        'capacity': _as_int(data.get('rows')) * _as_int(data.get('cols')),
    }


def mix_violations(data: dict) -> dict:
    viols = list(data.get('violations') or data.get('issues') or [])
    extra = []
    for item in list(data.get('unplaced') or [])[:3]:
        extra.append({
            'kind': 'distance',
            'code': 'distance',
            'a_id': item.get('id'),
            'b_id': item.get('id'),
            'detail': str(item.get('reason') or '间距不够'),
        })
    return {
        'violations': viols + extra,
        'issues': list(data.get('issues') or []) + extra,
        'unplaced': list(data.get('unplaced') or []),
    }
