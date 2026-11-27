# -*- coding: utf-8 -*-
"""业务服务：读取状态、提交新对位并事务性地应用求解结果。"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

from .solver import Crack, Edge, Pin, solve
from .db import get_state_version
from .seed_data import (
    BASE_IMAGE_ID,
    DEMO_NO_SOLUTION,
    DEMO_SOLVABLE,
    MAX_REMOVE,
)


class ValidationError(ValueError):
    """提交数据不合法（与“无解”区分：无解是合法输入但冲突不可解）。"""


class StaleStateError(Exception):
    """浏览器所持 base_version 与当前数据版本不一致（其他标签页已改动）。"""

    def __init__(self, current_version: int):
        super().__init__("页面状态已过期，请先补齐最新总图与台账")
        self.current_version = current_version


def _as_float(v, field: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 必须是数字")
    if not math.isfinite(f):
        raise ValidationError(f"{field} 必须是有限数字")
    return f


def validate_payload(db, data: Dict[str, Any]) -> Dict[str, Any]:
    image_a = str(data.get("image_a") or "").strip()
    image_b = str(data.get("image_b") or "").strip()
    if not image_a or not image_b:
        raise ValidationError("请选择两张照片")
    if image_a == image_b:
        raise ValidationError("请选择两张不同的照片")

    rows = {r["id"]: r for r in db.execute("SELECT * FROM images").fetchall()}
    if image_a not in rows or image_b not in rows:
        raise ValidationError("选择的照片不存在")

    ax = _as_float(data.get("ax"), "A 图横坐标")
    ay = _as_float(data.get("ay"), "A 图纵坐标")
    bx = _as_float(data.get("bx"), "B 图横坐标")
    by = _as_float(data.get("by"), "B 图纵坐标")

    for name, x, y, row in (
        ("A 图", ax, ay, rows[image_a]),
        ("B 图", bx, by, rows[image_b]),
    ):
        if not (0 <= x <= row["w"] and 0 <= y <= row["h"]):
            raise ValidationError(
                f"{name}点选位置超出样片范围 "
                f"(0..{row['w']}, 0..{row['h']})，请在照片上重新点选纹样"
            )

    return {
        "image_a": image_a, "image_b": image_b,
        "ax": ax, "ay": ay, "bx": bx, "by": by,
    }


def _build_inputs(db, payload: Dict[str, Any]):
    img_rows = db.execute("SELECT * FROM images ORDER BY sort_order").fetchall()
    images = {r["id"]: (r["tx"], r["ty"]) for r in img_rows}

    al_rows = db.execute(
        "SELECT * FROM alignments WHERE status = 'active' ORDER BY id"
    ).fetchall()
    edges = [
        Edge(
            key=str(r["id"]),
            a=r["image_a"], b=r["image_b"],
            ax=r["ax"], ay=r["ay"], bx=r["bx"], by=r["by"],
            reviewed=bool(r["reviewed"]),
            label=r["code"] or f"#{r['id']}",
        )
        for r in al_rows
    ]
    # 本次必须采用的新对位：已复核、不可撤
    edges.append(Edge(
        key="new",
        a=payload["image_a"], b=payload["image_b"],
        ax=payload["ax"], ay=payload["ay"],
        bx=payload["bx"], by=payload["by"],
        reviewed=True, mandatory=True,
    ))

    crack_rows = db.execute("SELECT * FROM cracks").fetchall()
    cracks = [
        Crack(cid=r["id"], image_id=r["image_id"], x=r["x"], y=r["y"],
              tagged=bool(r["tagged"]))
        for r in crack_rows
    ]

    # 基准图固定 + 每张含已贴签裂缝的照片钉在当前平移
    pins = [Pin(BASE_IMAGE_ID, *images[BASE_IMAGE_ID], "基准图固定")]
    # Row 没有 tx 字段，统一用 images 当前平移
    for cr in crack_rows:
        if cr["tagged"] and cr["image_id"] != BASE_IMAGE_ID:
            tx, ty = images[cr["image_id"]]
            pins.append(Pin(
                cr["image_id"], tx, ty,
                f"已贴签裂缝 {cr['code']} 坐标照旧",
            ))
    return images, edges, cracks, pins, al_rows


def submit_alignment(
    db,
    data: Dict[str, Any],
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """校验、求解并（有解时）落库。返回本次 run 的完整字典。

    expected_version 为浏览器提交时所持的数据版本：
    * 与当前版本一致 -> 正常求解，有解时返回增量 delta 与新版本；
    * 不一致         -> 抛 StaleStateError，不写任何记录，由路由回整份状态。
    expected_version 为 None（传统表单 / 旧调用方）时不做版本检查。
    """
    # 立即拿写锁，保证“读版本 -> 求解 -> 落库 -> 版本 +1”在多 worker /
    # 多标签页并发提交下仍然串行，不会出现两个提交基于同一版本都成功。
    db.execute("BEGIN IMMEDIATE")
    try:
        current_version = get_state_version(db)
        if (
            expected_version is not None
            and int(expected_version) != current_version
        ):
            db.rollback()
            raise StaleStateError(current_version)

        payload = validate_payload(db, data)
        images, edges, cracks, pins, al_rows = _build_inputs(db, payload)
        before_trans = {k: (float(v[0]), float(v[1])) for k, v in images.items()}

        outcome = solve(
            images=images, edges=edges, cracks=cracks, pins=pins,
            base_id=BASE_IMAGE_ID, max_remove=MAX_REMOVE,
        )

        # 先写 run 审计记录（无解也写，但不动任何业务数据）
        cur = db.execute(
            """INSERT INTO runs
               (status, image_a, image_b, ax, ay, bx, by,
                payload_json, result_json, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (outcome.status, payload["image_a"], payload["image_b"],
             payload["ax"], payload["ay"], payload["bx"], payload["by"],
             json.dumps(payload, ensure_ascii=False),
             "{}", ""),
        )
        run_id = cur.lastrowid

        if outcome.status != "applied":
            summary = "无解：原图与对位均保留"
            result = outcome.to_dict()
            db.execute(
                "UPDATE runs SET result_json=?, summary=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), summary, run_id),
            )
            # 无解：业务数据与版本号都不变，delta=None 告诉前端只更新结果。
            db.commit()
            run = get_run(db, run_id)
            run["version"] = current_version
            run["delta"] = None
            return run

        # ---- 有解：在同一事务内更新总图 / 撤对位 / 记新对位 ----
        id_to_row = {r["id"]: r for r in al_rows}
        removed_snapshot = []
        removed_ids = []
        for key in outcome.removed_keys:
            row = id_to_row[int(key)]
            removed_ids.append(row["id"])
            removed_snapshot.append({
                "id": row["id"],
                "code": row["code"],
                "image_a": row["image_a"],
                "image_b": row["image_b"],
                "ax": row["ax"], "ay": row["ay"],
                "bx": row["bx"], "by": row["by"],
                "reviewed": bool(row["reviewed"]),
                "note": row["note"],
            })
            db.execute(
                "UPDATE alignments SET status='withdrawn', run_id=? WHERE id=?",
                (run_id, row["id"]),
            )

        # 更新每张照片的平移（总图）
        for img_id, (tx, ty) in outcome.translations.items():
            db.execute(
                "UPDATE images SET tx=?, ty=? WHERE id=?", (tx, ty, img_id)
            )

        # 新对位记为已复核
        ncur = db.execute(
            """INSERT INTO alignments
               (code, image_a, image_b, ax, ay, bx, by,
                reviewed, status, origin, note, run_id)
               VALUES (NULL,?,?,?,?,?,?, 1,'active','submitted',?,?)""",
            (payload["image_a"], payload["image_b"],
             payload["ax"], payload["ay"], payload["bx"], payload["by"],
             "修复师点选提交，求解采用并记为已复核", run_id),
        )
        new_id = ncur.lastrowid
        new_code = f"DW-{new_id:02d}"
        db.execute("UPDATE alignments SET code=? WHERE id=?", (new_code, new_id))

        crack_rows = {r["id"]: r for r in db.execute("SELECT * FROM cracks").fetchall()}
        shifted = []
        for s in outcome.shifted:
            row = crack_rows[s["cid"]]
            shifted.append({
                "id": row["id"],
                "code": row["code"],
                "image_id": row["image_id"],
                "tagged": bool(row["tagged"]),
                "old": [round(s["old"][0], 2), round(s["old"][1], 2)],
                "new": [round(s["new"][0], 2), round(s["new"][1], 2)],
                "delta": [round(s["delta"][0], 2), round(s["delta"][1], 2)],
            })

        result = {
            "removed": removed_snapshot,
            "shifted": shifted,
            "new_alignment": {"id": new_id, "code": new_code},
            "translations": {k: [round(v[0], 3), round(v[1], 3)]
                             for k, v in outcome.translations.items()},
            "tried_candidates": outcome.tried_candidates,
            "feasible_candidates": outcome.feasible_candidates,
        }
        n_rm = len(removed_snapshot)
        n_sh = len(shifted)
        summary = (
            f"已采用新对位 {new_code}；撤下 {n_rm} 条未复核对位；"
            f"{n_sh} 条裂缝总图坐标移位"
        )
        db.execute(
            "UPDATE runs SET result_json=?, summary=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False), summary, run_id),
        )

        new_version = current_version + 1
        db.execute(
            "UPDATE meta SET value=? WHERE key='state_version'",
            (str(new_version),),
        )
        db.commit()

        run = get_run(db, run_id)
        run["version"] = new_version
        run["delta"] = _build_delta(
            db,
            before_trans=before_trans,
            outcome_trans=outcome.translations,
            removed_ids=removed_ids,
            new_alignment_id=new_id,
        )
        return run
    except ValidationError:
        db.rollback()
        raise
    except StaleStateError:
        # 抛出前已经 rollback
        raise
    except Exception:
        db.rollback()
        raise


def _build_delta(
    db,
    *,
    before_trans: Dict[str, tuple],
    outcome_trans: Dict[str, tuple],
    removed_ids: list,
    new_alignment_id: int,
) -> Dict[str, Any]:
    """提交落库后，对比新旧状态，构造只含本次变动的增量。"""
    moved_ids = []
    for iid, (tx, ty) in outcome_trans.items():
        old = before_trans.get(iid)
        if old is None:
            moved_ids.append(iid)
        elif abs(float(tx) - old[0]) > 1e-9 or abs(float(ty) - old[1]) > 1e-9:
            moved_ids.append(iid)
    moved_set = set(moved_ids)

    fresh = load_state(db)
    images_by_id = {i["id"]: i for i in fresh["images"]}

    # 只有平移真的变化的样片才下发；没动的样片前端完全保留原图层。
    delta_images = []
    for iid in moved_ids:
        row = images_by_id.get(iid)
        if row is not None:
            delta_images.append({
                "id": row["id"],
                "name": row["name"],
                "file": row["file"],
                "w": row["w"], "h": row["h"],
                "is_base": row["is_base"],
                "tx": row["tx"], "ty": row["ty"],
            })

    # 随移动样片一起移位的裂缝：下发新的总图坐标供台账更新。
    delta_cracks = [
        {
            "id": c["id"],
            "code": c["code"],
            "image_id": c["image_id"],
            "master_x": c["master_x"],
            "master_y": c["master_y"],
        }
        for c in fresh["cracks"]
        if c["image_id"] in moved_set
    ]

    # 保留对位中，只有端点落在移动样片上的，标记几何才需要更新；
    # 新对位的标记也要新增。
    upsert_marks = []
    for m in fresh["alignment_marks"]:
        if (
            m["id"] == new_alignment_id
            or m.get("image_a") in moved_set
            or m.get("image_b") in moved_set
        ):
            upsert_marks.append(m)

    new_row = db.execute(
        "SELECT * FROM alignments WHERE id=?", (new_alignment_id,)
    ).fetchone()

    return {
        "version": fresh["version"],
        "moved_image_ids": moved_ids,
        "images": delta_images,
        "cracks": delta_cracks,
        "removed_alignment_ids": list(removed_ids),
        "alignment_marks_remove": list(removed_ids),
        "alignment_marks_upsert": upsert_marks,
        "alignments_upsert": [dict(new_row)] if new_row is not None else [],
        "alignment_total": len(fresh["alignments"]),
    }


def get_run(db, run_id: int) -> Optional[Dict[str, Any]]:
    row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return _serialize_run(row) if row else None


def _serialize_run(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["result"] = json.loads(d.pop("result_json") or "{}")
    except json.JSONDecodeError:
        d["result"] = {}
    try:
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        d["payload"] = {}
    return d


def list_runs(db, limit: int = 12):
    rows = db.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_serialize_run(r) for r in rows]


def load_state(db) -> Dict[str, Any]:
    images = [dict(r) for r in db.execute(
        "SELECT * FROM images ORDER BY sort_order"
    ).fetchall()]
    img_map = {i["id"]: i for i in images}

    alignments = [dict(r) for r in db.execute(
        "SELECT * FROM alignments ORDER BY id"
    ).fetchall()]

    cracks_raw = [dict(r) for r in db.execute("SELECT * FROM cracks").fetchall()]
    cracks = []
    for c in cracks_raw:
        img = img_map[c["image_id"]]
        mx = c["x"] + img["tx"]
        my = c["y"] + img["ty"]
        cracks.append({
            **c,
            "master_x": round(mx, 2),
            "master_y": round(my, 2),
        })

    # 生效对位在总图坐标下的两个点选端点（自洽时两点重合）
    alignment_marks = []
    for a in alignments:
        if a["status"] != "active":
            continue
        ia = img_map[a["image_a"]]
        ib = img_map[a["image_b"]]
        axm, aym = a["ax"] + ia["tx"], a["ay"] + ia["ty"]
        bxm, bym = a["bx"] + ib["tx"], a["by"] + ib["ty"]
        alignment_marks.append({
            "id": a["id"],
            "code": a["code"] or f"#{a['id']}",
            "image_a": a["image_a"],
            "image_b": a["image_b"],
            "reviewed": a["reviewed"],
            "axm": axm, "aym": aym, "bxm": bxm, "bym": bym,
            "mx": (axm + bxm) / 2, "my": (aym + bym) / 2,
            "residual": round(((axm - bxm) ** 2 + (aym - bym) ** 2) ** 0.5, 1),
        })

    return {
        "version": get_state_version(db),
        "images": images,
        "alignments": alignments,
        "alignment_marks": alignment_marks,
        "cracks": cracks,
        "runs": list_runs(db),
        "demos": {
            "solvable": DEMO_SOLVABLE,
            "no_solution": DEMO_NO_SOLUTION,
        },
        "max_remove": MAX_REMOVE,
    }
