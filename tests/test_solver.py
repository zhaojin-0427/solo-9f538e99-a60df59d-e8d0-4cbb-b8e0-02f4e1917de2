# -*- coding: utf-8 -*-
"""solver 纯逻辑自测：有解（0/1/2 条撤下、优选、连通性）与无解情形。

直接运行：
    python -m unittest tests.test_solver -v
"""

import unittest

from app.solver import Crack, Edge, Pin, evaluate_candidate, solve
from app.seed_data import (
    ALIGNMENTS, CRACKS, DEMO_NO_SOLUTION, DEMO_SOLVABLE, IMAGES,
)


def E(key, a, b, ax, ay, bx, by, reviewed=False, mandatory=False):
    return Edge(str(key), a, b, ax, ay, bx, by, reviewed, mandatory)


def C(cid, img, x=0, y=0, tagged=False):
    return Crack(cid, img, x, y, tagged)


def S(images, edges, cracks=None, pins=None, **kw):
    """合成小夹具的基准图 id 固定为 '0'。"""
    kw.setdefault("base_id", "0")
    return solve(images, edges, cracks or [], pins=pins, **kw)


class SolverTests(unittest.TestCase):
    def test_consistent_submission_needs_zero_removal(self):
        images = {"0": (0, 0), "1": (100, 0), "2": (200, 0)}
        edges = [
            E("r01", "0", "1", 100, 0, 0, 0, reviewed=True),   # d=(100,0)
            E("u12", "1", "2", 100, 0, 0, 0),                  # d=(100,0)
            E("new", "0", "2", 200, 0, 0, 0, mandatory=True),  # d=(200,0)
        ]
        out = S(images, edges, [C("c1", "1", 5, 5)])
        self.assertEqual(out.status, "applied")
        self.assertEqual(out.removed_keys, [])
        self.assertEqual(out.translations["2"], (200, 0))
        self.assertEqual(out.shifted, [])

    def test_remove_one_bad_alignment_and_report_shift(self):
        # 旧图按错误对位把 img1 放在 (130,0)；新正确对位要求 (100,0)
        images = {"0": (0, 0), "1": (130, 0)}
        edges = [
            E("bad", "0", "1", 130, 0, 0, 0),                  # 未复核错误对位
            E("new", "0", "1", 100, 0, 0, 0, mandatory=True),
        ]
        cracks = [C("LF-X", "1", 10, 10)]
        out = S(images, edges, cracks)
        self.assertEqual(out.status, "applied")
        self.assertEqual(out.removed_keys, ["bad"])
        self.assertEqual(out.translations["1"], (100, 0))
        self.assertEqual(len(out.shifted), 1)
        s = out.shifted[0]
        self.assertEqual(s["old"], [140, 10])
        self.assertEqual(s["new"], [110, 10])

    def test_tie_break_prefers_fewer_shifted_cracks(self):
        # 四边形冲突环：撤 u23 时 img3 留在旧位置（0 移位）；
        # 撤 u30 时 img3 被抬高 6px（1 条裂缝移位）。
        images = {
            "0": (0, 0), "1": (10, 0),
            "2": (20, 0), "3": (10, 10),
        }
        edges = [
            E("r01", "0", "1", 10, 0, 0, 0, reviewed=True),
            E("new", "1", "2", 10, 0, 0, 0, mandatory=True),
            E("u23", "2", "3", -10, 16, 0, 0),   # d=(-10,16)，错 6px
            E("u30", "3", "0", -10, -10, 0, 0),  # d=(-10,-10) 正确
        ]
        cracks = [C("c3", "3", 1, 1)]
        out = S(images, edges, cracks)
        self.assertEqual(out.status, "applied")
        self.assertEqual(out.removed_keys, ["u23"])
        self.assertEqual(len(out.shifted), 0)

        # 反向验证：若只剩“撤 u30”这一种可行解，就会移动裂缝
        res = evaluate_candidate(
            images, edges, [], cracks, removed=["u30"], base_id="0"
        )
        self.assertTrue(res.feasible, res.reasons)
        self.assertEqual(len(res.shifted), 1)
        self.assertAlmostEqual(res.translations["3"][1], 16)

    def test_two_removals_seed_scenario(self):
        """内置种子：有解示例必须撤 DW-02 + DW-03，且只移 LF-03/LF-04。"""
        images = {i["id"]: (i["tx"], i["ty"]) for i in IMAGES}
        edges = [
            E(a["code"], a["image_a"], a["image_b"],
              a["ax"], a["ay"], a["bx"], a["by"], bool(a["reviewed"]))
            for a in ALIGNMENTS
        ]
        cracks = [
            Crack(c["id"], c["image_id"], c["x"], c["y"], bool(c["tagged"]))
            for c in CRACKS
        ]
        pins = [Pin("img0", 0, 0)]
        for c in CRACKS:
            if c["tagged"] and c["image_id"] != "img0":
                tx, ty = images[c["image_id"]]
                pins.append(Pin(c["image_id"], tx, ty))

        d = DEMO_SOLVABLE
        edges.append(E("new", d["image_a"], d["image_b"],
                       d["ax"], d["ay"], d["bx"], d["by"],
                       reviewed=True, mandatory=True))
        out = solve(images, edges, cracks, pins)
        self.assertEqual(out.status, "applied")
        self.assertEqual(out.removed_keys, d["expect"]["removed_codes"])
        self.assertEqual([s["cid"] for s in out.shifted],
                         d["expect"]["shifted_ids"])
        for s in out.shifted:
            self.assertEqual(
                d["expect"]["new_master"][s["cid"]],
                [int(s["new"][0]), int(s["new"][1])],
            )
        # 贴签裂缝一条都不能移位
        self.assertFalse([s for s in out.shifted if s["tagged"]])
        # 求解后所有图像都在
        self.assertEqual(set(out.translations), set(images))

    def test_unsolvable_reviewed_direct_conflict(self):
        images = {"0": (0, 0), "1": (100, 0)}
        edges = [
            E("r01", "0", "1", 100, 0, 0, 0, reviewed=True),
            E("u_x", "0", "1", 999, 999, 0, 0),  # 无关的未复核边
            E("new", "0", "1", 140, 0, 0, 0, mandatory=True),
        ]
        out = S(images, edges, [])
        self.assertEqual(out.status, "no_solution")
        self.assertIn("已复核", out.reason)

    def test_unsolvable_when_three_bad_edges_but_limit_two(self):
        images = {"0": (0, 0), "1": (100, 0)}
        edges = [
            E("u1", "0", "1", 130, 0, 0, 0),
            E("u2", "0", "1", 131, 0, 0, 0),
            E("u3", "0", "1", 132, 0, 0, 0),
            E("new", "0", "1", 100, 0, 0, 0, mandatory=True),
        ]
        out = S(images, edges, [], max_remove=2)
        self.assertEqual(out.status, "no_solution")
        # 枚举了 1(0 条) + 3(1 条) + 3(2 条) = 7 种撤法
        self.assertEqual(out.tried_candidates, 7)

    def test_connectivity_required(self):
        images = {"0": (0, 0), "1": (10, 0), "2": (50, 50)}
        edges = [
            E("r01", "0", "1", 10, 0, 0, 0, reviewed=True),
            E("new", "0", "1", 10, 0, 0, 0, mandatory=True),
        ]
        out = S(images, edges, [])
        self.assertEqual(out.status, "no_solution")
        self.assertTrue(any(c["reasons"] and "定位到基准图" in c["reasons"][0]
                            for c in out.candidates))

    def test_tagged_crack_pin_blocks_move(self):
        images = {"0": (0, 0), "1": (100, 0)}
        pins = [Pin("0", 0, 0), Pin("1", 100, 0, "已贴签 LF-02")]
        edges = [E("new", "0", "1", 120, 0, 0, 0, mandatory=True)]
        out = S(images, edges, [C("LF-02", "1", 1, 1, True)], pins)
        self.assertEqual(out.status, "no_solution")

    def test_base_never_moves(self):
        images = {"0": (0, 0), "1": (30, 40)}
        edges = [E("new", "1", "0", -30, -40, 0, 0, mandatory=True)]
        out = S(images, edges, [])
        self.assertEqual(out.status, "applied")
        self.assertEqual(out.translations["0"], (0, 0))

    def test_demo_no_solution_seed(self):
        images = {i["id"]: (i["tx"], i["ty"]) for i in IMAGES}
        edges = [
            E(a["code"], a["image_a"], a["image_b"],
              a["ax"], a["ay"], a["bx"], a["by"], bool(a["reviewed"]))
            for a in ALIGNMENTS
        ]
        d = DEMO_NO_SOLUTION
        edges.append(E("new", d["image_a"], d["image_b"],
                       d["ax"], d["ay"], d["bx"], d["by"],
                       reviewed=True, mandatory=True))
        out = solve(images, edges, [], base_id="img0")
        self.assertEqual(out.status, "no_solution")


if __name__ == "__main__":
    unittest.main(verbosity=2)
