# -*- coding: utf-8 -*-
"""对位冲突求解（纯 Python，不依赖 Flask / sqlite，便于单测）。

模型
----
同比例、同朝向下，每张照片只有两个平移变量。对位 e=(a,b) 的一对点
pa、pb 约束：

    t_b - t_a = pa - pb

基准图固定；已贴签裂缝的总图坐标必须保持不变，因此带贴签裂缝的照片
被“钉”在当前平移上。保留的对位必须在容差内全部成立，且保留对位图
必须让每张照片都与基准图连通（即可定位到基准图）。

允许撤下的只有“未复核且非本次新提交”的旧对位，最多 max_remove 条。
在所有可行撤法中，先选撤下条数最少的；条数相同，选移位裂缝数最少的；
仍相同则按撤下对位的标识排序取确定解。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from .seed_data import CONSTRAINT_TOL, SHIFT_EPS, MAX_REMOVE, BASE_IMAGE_ID


@dataclass(frozen=True)
class Edge:
    key: str                 # 对位标识（数据库 id 的字符串；新对位用 "new"）
    a: str
    b: str
    ax: float
    ay: float
    bx: float
    by: float
    reviewed: bool = False
    mandatory: bool = False  # 本次提交的新对位：必须采用，不可撤
    label: str = ""          # 面向用户的编号（如 DW-01）

    @property
    def display(self) -> str:
        return self.label or self.key

    @property
    def delta(self) -> Tuple[float, float]:
        # t_b - t_a = p_a - p_b
        return self.ax - self.bx, self.ay - self.by

    @property
    def removable(self) -> bool:
        return (not self.mandatory) and (not self.reviewed)


@dataclass(frozen=True)
class Pin:
    image_id: str
    x: float
    y: float
    reason: str = ""


@dataclass(frozen=True)
class Crack:
    cid: str
    image_id: str
    x: float
    y: float
    tagged: bool = False


@dataclass
class CandidateResult:
    removed: Tuple[str, ...]
    translations: Dict[str, Tuple[float, float]]
    shifted: List[dict] = field(default_factory=list)
    feasible: bool = True
    reasons: List[str] = field(default_factory=list)


@dataclass
class SolveOutcome:
    status: str                       # "applied" | "no_solution"
    removed_keys: List[str] = field(default_factory=list)
    translations: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    shifted: List[dict] = field(default_factory=list)
    tried_candidates: int = 0
    feasible_candidates: int = 0
    reason: str = ""
    candidates: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "removed_keys": self.removed_keys,
            "translations": {k: list(v) for k, v in self.translations.items()},
            "shifted": self.shifted,
            "tried_candidates": self.tried_candidates,
            "feasible_candidates": self.feasible_candidates,
            "reason": self.reason,
            "candidates": self.candidates,
        }


def _dist(x1, y1, x2, y2) -> float:
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def evaluate_candidate(
    images: Dict[str, Tuple[float, float]],
    edges: Sequence[Edge],
    pins: Sequence[Pin],
    cracks: Sequence[Crack],
    removed: Sequence[str],
    base_id: str = BASE_IMAGE_ID,
    tol: float = CONSTRAINT_TOL,
    shift_eps: float = SHIFT_EPS,
) -> CandidateResult:
    """评估某个撤下集合是否可行；可行时给出平移与移位裂缝。"""
    removed_set = set(removed)
    reasons: List[str] = []

    # 邻接表：adj[i] 中 (j, dx, dy) 表示 t_j = t_i + (dx, dy)
    adj: Dict[str, List[Tuple[str, float, float, str]]] = {
        i: [] for i in images
    }
    retained = [e for e in edges if e.key not in removed_set]
    for e in retained:
        if e.a not in images or e.b not in images:
            reasons.append(f"对位 {e.key} 引用了不存在的图像")
            continue
        dx, dy = e.delta
        adj[e.a].append((e.b, dx, dy, e.key))
        adj[e.b].append((e.a, -dx, -dy, e.key))

    base_pin = next((p for p in pins if p.image_id == base_id), None)
    if base_pin is not None:
        t0 = (base_pin.x, base_pin.y)
    else:
        t0 = images[base_id]

    trans: Dict[str, Tuple[float, float]] = {base_id: t0}
    stack = [base_id]
    seen_edges = set()

    while stack:
        i = stack.pop()
        ix, iy = trans[i]
        for j, dx, dy, ekey in adj.get(i, []):
            exp = (ix + dx, iy + dy)
            if j not in trans:
                trans[j] = exp
                stack.append(j)
            else:
                got = trans[j]
                err = _dist(exp[0], exp[1], got[0], got[1])
                if err > tol and ekey not in seen_edges:
                    reasons.append(
                        f"对位 {ekey} 不成立：残差 {err:.1f}px > 容差 {tol:g}px"
                    )
            seen_edges.add(ekey)

    # 每张图都必须能从基准图到达
    missing = [i for i in images if i not in trans]
    if missing:
        reasons.append("以下图像无法经保留对位定位到基准图：" + "、".join(sorted(missing)))

    # 贴签裂缝 / 基准图的硬钉约束：必须真正保持原坐标（与“移位”判定同阈值）
    for p in pins:
        if p.image_id not in trans:
            continue
        tx, ty = trans[p.image_id]
        err = _dist(tx, ty, p.x, p.y)
        if err > shift_eps:
            reasons.append(
                f"贴签坐标约束不满足：{p.image_id} 需保持平移 "
                f"({p.x:g},{p.y:g})，求解为 ({tx:.1f},{ty:.1f})，残差 {err:.1f}px"
            )

    feasible = not reasons

    shifted: List[dict] = []
    if feasible:
        for c in cracks:
            if c.image_id not in trans:
                continue
            old_tx, old_ty = images[c.image_id]
            new_tx, new_ty = trans[c.image_id]
            old_mx = c.x + old_tx
            old_my = c.y + old_ty
            new_mx = c.x + new_tx
            new_my = c.y + new_ty
            if _dist(old_mx, old_my, new_mx, new_my) > shift_eps:
                shifted.append({
                    "cid": c.cid,
                    "tagged": c.tagged,
                    "old": [old_mx, old_my],
                    "new": [new_mx, new_my],
                    "delta": [new_mx - old_mx, new_my - old_my],
                })
        # 硬约束下贴签裂缝绝不应移位；若出现说明容差判断有漏洞
        bad_tagged = [s for s in shifted if s["tagged"]]
        if bad_tagged:
            feasible = False
            reasons.append("已贴签裂缝发生移位，方案无效")

    return CandidateResult(
        removed=tuple(sorted(removed)),
        translations=trans,
        shifted=shifted,
        feasible=feasible,
        reasons=reasons,
    )


def solve(
    images: Dict[str, Tuple[float, float]],
    edges: Sequence[Edge],
    cracks: Sequence[Crack],
    pins: Optional[Sequence[Pin]] = None,
    base_id: str = BASE_IMAGE_ID,
    max_remove: int = MAX_REMOVE,
    tol: float = CONSTRAINT_TOL,
) -> SolveOutcome:
    """按“最少撤下条数 → 最少移位裂缝数”求最优可行撤法。"""
    pins = list(pins or [])
    # 基准图固定：即便调用方没给 pin 也补上
    if not any(p.image_id == base_id for p in pins):
        bx, by = images[base_id]
        pins.append(Pin(base_id, bx, by, "基准图固定"))

    removable = sorted(e.key for e in edges if e.removable)
    limit = min(max_remove, len(removable))

    tried = 0
    feasible_count = 0
    candidate_summaries: List[dict] = []

    for r in range(0, limit + 1):
        layer: List[CandidateResult] = []
        for combo in combinations(removable, r):
            tried += 1
            res = evaluate_candidate(
                images, edges, pins, cracks, combo,
                base_id=base_id, tol=tol,
            )
            candidate_summaries.append({
                "removed": list(combo),
                "feasible": res.feasible,
                "shifted_count": len(res.shifted),
                "reasons": res.reasons,
            })
            if res.feasible:
                feasible_count += 1
                layer.append(res)

        if layer:
            # 同撤下条数：移位裂缝最少；再相同：撤下标识字典序，保证确定
            best = min(
                layer,
                key=lambda z: (
                    len(z.shifted),
                    tuple(sorted(z.removed)),
                ),
            )
            return SolveOutcome(
                status="applied",
                removed_keys=list(best.removed),
                translations=best.translations,
                shifted=best.shifted,
                tried_candidates=tried,
                feasible_candidates=feasible_count,
                candidates=candidate_summaries,
            )

    # 无解：给出尽量易懂的诊断
    reason = _diagnose(images, edges, pins, base_id, tol)
    return SolveOutcome(
        status="no_solution",
        tried_candidates=tried,
        feasible_candidates=0,
        reason=reason,
        candidates=candidate_summaries,
    )


def _diagnose(images, edges, pins, base_id, tol) -> str:
    """无解时指出“新对位 vs 已复核对位/贴签”这类不可撤冲突。"""
    new_edges = [e for e in edges if e.mandatory]
    reviewed = [e for e in edges if e.reviewed and not e.mandatory]

    # 新对位与同一对照片上的已复核对位直接矛盾
    for ne in new_edges:
        for re_ in reviewed:
            same_pair = (
                (ne.a == re_.a and ne.b == re_.b)
                or (ne.a == re_.b and ne.b == re_.a)
            )
            if not same_pair:
                continue
            d_new = ne.delta
            d_old = re_.delta
            if ne.a == re_.b:
                d_old = (-d_old[0], -d_old[1])
            err = _dist(d_new[0], d_new[1], d_old[0], d_old[1])
            if err > tol:
                return (
                    f"新对位与已复核的对位 {re_.display} 直接冲突"
                    f"（相对位移相差约 {err:.0f}px）；已复核对位不可撤下，"
                    "而允许撤下的未复核对位不包含该矛盾，故无解。"
                )

    # 贴签/基准钉与新对位矛盾
    pin_map = {p.image_id: p for p in pins}
    for ne in new_edges:
        pa = pin_map.get(ne.a)
        pb = pin_map.get(ne.b)
        if pa and pb:
            want = (pb.x - pa.x, pb.y - pa.y)
            got = ne.delta
            err = _dist(want[0], want[1], got[0], got[1])
            if err > tol:
                return (
                    "新对位与两张照片上已贴签裂缝必须保持的总图坐标冲突"
                    f"（相对位移相差约 {err:.0f}px），且贴签约束不可更改，故无解。"
                )

    return (
        "枚举撤下至多 "
        f"{MAX_REMOVE} 条未复核对位后，仍无法同时满足：保留对位全部成立、"
        "每张图可定位到基准图、已贴签裂缝总图坐标不变。"
    )
