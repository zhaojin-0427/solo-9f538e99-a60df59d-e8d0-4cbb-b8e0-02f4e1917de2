# -*- coding: utf-8 -*-
"""内置样片、旧对位、裂缝与演示点的唯一数据来源。

几何约定（同比例、同朝向，单位为样片像素 = 总图坐标单位）：

* 每张样片 i 只平移：样片坐标 p 对应总图坐标 p + (tx_i, ty_i)。
* 基准图 img0 固定在 (0, 0)。
* 对位 e=(a,b) 上点选的两点 pa、pb 为同一处纹样，因此
  tb - ta = pa - pb （记为该对位给出的相对位移 d）。

下面的旧数据特意排成：旧总图与全部五条旧对位在“旧平移”下完全自洽；
其中 DW-02 是一条点错纹样的未复核对位，把 img2/img4 一带错位了。
新的正确对位 DEMO_SOLVABLE 到来后，至少要撤下两条未复核对位才能恢复一致，
而两种撤两条的方案会移动数量不同的裂缝 —— 正好验证优选规则。
"""

IMG_W = 480
IMG_H = 360

# 总图画布范围（覆盖当前所有平移位置）
MASTER_W = 1320
MASTER_H = 680

BASE_IMAGE_ID = "img0"
MAX_REMOVE = 2
# “对位成立”的容许残差（总图坐标单位，约等于像素）。种子数据的冲突量
# 都是 20~50，远大于该容差。
CONSTRAINT_TOL = 2.0
# 坐标变化超过该值即计为“移位裂缝”
SHIFT_EPS = 0.5

# ox/oy：样片 SVG 取景窗在“真实壁画全局坐标”中的原点（只用于画样片内容）。
# tx/ty：当前总图给该样片安排的平移（初始 = 旧总图位置）。
IMAGES = [
    {
        "id": "img0",
        "name": "基准图 · 西壁西段",
        "file": "samples/img0.svg",
        "ox": 0, "oy": 0,
        "tx": 0, "ty": 0,
        "is_base": 1,
        "sort_order": 0,
    },
    {
        "id": "img1",
        "name": "样片一 · 主壁中段",
        "file": "samples/img1.svg",
        "ox": 400, "oy": 0,
        "tx": 400, "ty": 0,
        "is_base": 0,
        "sort_order": 1,
    },
    {
        "id": "img2",
        "name": "样片二 · 东壁东段",
        "file": "samples/img2.svg",
        "ox": 800, "oy": 0,
        "tx": 830, "ty": 20,
        "is_base": 0,
        "sort_order": 2,
    },
    {
        "id": "img3",
        "name": "样片三 · 南壁下段",
        "file": "samples/img3.svg",
        "ox": 400, "oy": 300,
        "tx": 400, "ty": 300,
        "is_base": 0,
        "sort_order": 3,
    },
    {
        "id": "img4",
        "name": "样片四 · 东壁下段",
        "file": "samples/img4.svg",
        "ox": 800, "oy": 300,
        "tx": 800, "ty": 300,
        "is_base": 0,
        "sort_order": 4,
    },
]

# 旧对位。ax/ay 属于 image_a，bx/by 属于 image_b。
# reviewed=1 已复核（不可撤下）；0 未复核（最多撤两条）。
ALIGNMENTS = [
    {
        "code": "DW-01",
        "image_a": "img0", "image_b": "img1",
        "ax": 450, "ay": 160, "bx": 50, "by": 160,
        "reviewed": 1, "note": "旧复核：西侧莲纹相接",
    },
    {
        "code": "DW-02",
        "image_a": "img1", "image_b": "img2",
        "ax": 455, "ay": 210, "bx": 25, "by": 190,
        "reviewed": 0, "note": "旧对位：经变画边框（疑似误点）",
    },
    {
        "code": "DW-03",
        "image_a": "img2", "image_b": "img4",
        "ax": 120, "ay": 320, "bx": 150, "by": 40,
        "reviewed": 0, "note": "旧对位：上下边饰",
    },
    {
        "code": "DW-04",
        "image_a": "img1", "image_b": "img3",
        "ax": 220, "ay": 330, "bx": 220, "by": 30,
        "reviewed": 1, "note": "旧复核：纵向卷草纹",
    },
    {
        "code": "DW-05",
        "image_a": "img3", "image_b": "img4",
        "ax": 450, "ay": 200, "bx": 50, "by": 200,
        "reviewed": 0, "note": "旧对位：东侧莲座",
    },
]

# 裂缝坐标是“所在样片”的局部坐标。tagged=1 表示已贴签，
# 其总图坐标必须保持旧值，等价于把所在样片钉在当前平移上。
CRACKS = [
    {"id": "LF-01", "image_id": "img0", "code": "LF-01",
     "x": 140, "y": 110, "tagged": 1, "note": "西壁斜裂，已贴签"},
    {"id": "LF-02", "image_id": "img1", "code": "LF-02",
     "x": 250, "y": 140, "tagged": 1, "note": "中段龟裂纹，已贴签"},
    {"id": "LF-03", "image_id": "img2", "code": "LF-03",
     "x": 160, "y": 200, "tagged": 0, "note": "东段纵向裂缝"},
    {"id": "LF-04", "image_id": "img2", "code": "LF-04",
     "x": 320, "y": 90, "tagged": 0, "note": "东段枝状裂缝"},
    {"id": "LF-05", "image_id": "img4", "code": "LF-05",
     "x": 180, "y": 170, "tagged": 0, "note": "东壁下部裂缝"},
    {"id": "LF-06", "image_id": "img3", "code": "LF-06",
     "x": 230, "y": 150, "tagged": 1, "note": "南壁横向裂，已贴签"},
]

# 全局壁画上的装饰纹样（用于生成 SVG 样片，让点击点落在可见纹样上）
MOTIFS = [
    {"x": 150, "y": 250, "kind": "lotus", "r": 26, "color": "#b5402f"},
    {"x": 250, "y": 70, "kind": "diamond", "r": 18, "color": "#2b5d8a"},
    {"x": 450, "y": 160, "kind": "lotus", "r": 24, "color": "#c8862d"},
    {"x": 620, "y": 330, "kind": "diamond", "r": 22, "color": "#3a7d5d"},
    {"x": 840, "y": 170, "kind": "lotus", "r": 30, "color": "#b5402f"},
    {"x": 1080, "y": 60, "kind": "lotus", "r": 20, "color": "#2b5d8a"},
    {"x": 1120, "y": 250, "kind": "spiral", "r": 26, "color": "#3a7d5d"},
    {"x": 60, "y": 520, "kind": "spiral", "r": 24, "color": "#2b5d8a"},
    {"x": 700, "y": 520, "kind": "lotus", "r": 28, "color": "#c8862d"},
    {"x": 850, "y": 500, "kind": "lotus", "r": 24, "color": "#b5402f"},
    {"x": 1180, "y": 560, "kind": "diamond", "r": 22, "color": "#2b5d8a"},
    {"x": 360, "y": 620, "kind": "diamond", "r": 18, "color": "#3a7d5d"},
]

# 页面“填入示例”按钮使用的点击数据。
DEMO_SOLVABLE = {
    "label": "有解冲突：img1 / img2 上的同一朵莲纹",
    "image_a": "img1", "image_b": "img2",
    "ax": 440, "ay": 170, "bx": 40, "by": 170,
    # 求解器应给出的结果（供自测/页面说明核对）
    "expect": {
        "status": "applied",
        "removed_codes": ["DW-02", "DW-03"],
        "shifted_ids": ["LF-03", "LF-04"],
        "new_master": {
            "LF-03": [960, 200],
            "LF-04": [1120, 90],
        },
    },
}

DEMO_NO_SOLUTION = {
    "label": "无解冲突：新点选与已复核 DW-01 直接矛盾",
    "image_a": "img0", "image_b": "img1",
    "ax": 470, "ay": 150, "bx": 20, "by": 150,
    "expect": {"status": "no_solution"},
}


def seed_if_empty(db):
    """空库时写入内置样片数据。db 为已打开的 sqlite3 连接。

    用固定主键 + 事务保护，即使多个 gunicorn worker 同时首启也不会
    重复播种（后到者撞主键后回滚即可）。
    """
    import sqlite3

    count = db.execute("SELECT COUNT(*) AS n FROM images").fetchone()["n"]
    if count:
        return False

    try:
        db.execute("BEGIN")
        for img in IMAGES:
            db.execute(
                """INSERT OR IGNORE INTO images
                   (id, name, file, w, h, is_base, tx, ty, sort_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (img["id"], img["name"], img["file"], IMG_W, IMG_H,
                 img["is_base"], img["tx"], img["ty"], img["sort_order"]),
            )

        for al in ALIGNMENTS:
            db.execute(
                """INSERT INTO alignments
                   (code, image_a, image_b, ax, ay, bx, by,
                    reviewed, status, origin, note)
                   VALUES (?,?,?,?,?,?,?,?, 'active', 'seed', ?)""",
                (al["code"], al["image_a"], al["image_b"],
                 al["ax"], al["ay"], al["bx"], al["by"],
                 al["reviewed"], al["note"]),
            )

        for cr in CRACKS:
            db.execute(
                """INSERT OR IGNORE INTO cracks
                   (id, image_id, code, x, y, tagged, note)
                   VALUES (?,?,?,?,?,?,?)""",
                (cr["id"], cr["image_id"], cr["code"],
                 cr["x"], cr["y"], cr["tagged"], cr["note"]),
            )

        db.commit()
        return True
    except sqlite3.IntegrityError:
        # 另一个进程/worker 已完成播种
        db.rollback()
        return False


def reset_all(db):
    """清空业务数据并重新写入内置样片。"""
    for table in ("runs", "alignments", "cracks", "images"):
        db.execute(f"DELETE FROM {table}")
    # 复位自增 id，让演示对位编号保持稳定
    db.execute("DELETE FROM sqlite_sequence WHERE name IN ('runs','alignments')")
    db.commit()
    return seed_if_empty(db)
