# -*- coding: utf-8 -*-
"""Flask + SQLite 接口与事务自测：有解落库、无解原样保留、表单通道。

运行：
    python -m unittest tests.test_api -v
"""

import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.db import connect
from app.seed_data import DEMO_NO_SOLUTION, DEMO_SOLVABLE


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_mural.db"
        self.app = create_app(database=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    # ---------- 页面 / 状态 ----------
    def test_health_and_index(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("裂缝定位总图", html)
        self.assertIn("DW-01", html)
        self.assertIn("LF-01", html)

    def test_state_seed_counts(self):
        st = self.client.get("/api/state").get_json()
        self.assertEqual(len(st["images"]), 5)
        self.assertEqual(len(st["alignments"]), 5)
        self.assertEqual(len(st["cracks"]), 6)
        tagged = [c for c in st["cracks"] if c["tagged"]]
        self.assertEqual(len(tagged), 3)

    def test_sample_svgs_served(self):
        for img_id in ("img0", "img1", "img2", "img3", "img4"):
            r = self.client.get(f"/static/samples/{img_id}.svg")
            self.assertEqual(r.status_code, 200, img_id)
            self.assertIn("<svg", r.get_data(as_text=True))

    # ---------- 有解 ----------
    def test_submit_solvable_applies_everything(self):
        d = DEMO_SOLVABLE
        r = self.client.post("/api/submit", json={
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "applied", body)
        self.assertEqual([x["code"] for x in body["removed"]],
                          ["DW-02", "DW-03"])
        self.assertEqual([x["code"] for x in body["shifted"]],
                          ["LF-03", "LF-04"])
        coord = {x["code"]: x["new"] for x in body["shifted"]}
        self.assertEqual(coord["LF-03"], [960, 200])
        self.assertEqual(coord["LF-04"], [1120, 90])
        self.assertTrue(body["new_alignment"]["code"].startswith("DW-"))

        # ---- 数据库核对 ----
        db = connect(self.db_path)
        try:
            imgs = {r["id"]: r for r in db.execute("SELECT * FROM images")}
            self.assertAlmostEqual(imgs["img2"]["tx"], 800)
            self.assertAlmostEqual(imgs["img2"]["ty"], 0)
            # 优选方案保留 DW-05，img4 不动
            self.assertAlmostEqual(imgs["img4"]["tx"], 800)
            self.assertAlmostEqual(imgs["img4"]["ty"], 300)
            # 基准图不动
            self.assertAlmostEqual(imgs["img0"]["tx"], 0)

            al = {r["code"]: r for r in db.execute("SELECT * FROM alignments")}
            self.assertEqual(al["DW-02"]["status"], "withdrawn")
            self.assertEqual(al["DW-03"]["status"], "withdrawn")
            self.assertEqual(al["DW-05"]["status"], "active")
            # 新对位已复核
            new = db.execute(
                "SELECT * FROM alignments WHERE origin='submitted'"
            ).fetchone()
            self.assertEqual(new["reviewed"], 1)
            self.assertEqual(new["status"], "active")
            self.assertIsNotNone(new["run_id"])

            # 已贴签裂缝的总图坐标照旧（局部坐标 + 平移）
            for code, expect in {
                "LF-01": (140, 110),
                "LF-02": (250 + 400, 140),
                "LF-06": (230 + 400, 150 + 300),
            }.items():
                c = db.execute("SELECT * FROM cracks WHERE code=?",
                               (code,)).fetchone()
                i = imgs[c["image_id"]]
                self.assertAlmostEqual(c["x"] + i["tx"], expect[0])
                self.assertAlmostEqual(c["y"] + i["ty"], expect[1])
        finally:
            db.close()

        # 页面能看到结果
        page = self.client.get(f"/?run={body['id']}#result").get_data(as_text=True)
        self.assertIn("撤下的对位", page)
        self.assertIn("DW-02", page)
        self.assertIn("(960, 200)", page)

    def test_consistent_submission_zero_removal(self):
        r = self.client.post("/api/submit", json={
            "image_a": "img0", "image_b": "img1",
            "ax": 450, "ay": 160, "bx": 50, "by": 160,
        })
        body = r.get_json()
        self.assertEqual(body["status"], "applied")
        self.assertEqual(body["removed"], [])
        self.assertEqual(body["shifted"], [])

    # ---------- 无解 ----------
    def test_submit_no_solution_keeps_map_and_alignments(self):
        d = DEMO_NO_SOLUTION
        r = self.client.post("/api/submit", json={
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        })
        body = r.get_json()
        self.assertEqual(body["status"], "no_solution")
        self.assertIn("已复核", body["reason"])

        db = connect(self.db_path)
        try:
            # 原图位置不变
            i2 = db.execute("SELECT * FROM images WHERE id='img2'").fetchone()
            self.assertAlmostEqual(i2["tx"], 830)
            self.assertAlmostEqual(i2["ty"], 20)
            # 对位仍是原来 5 条且全部 active，没有偷偷写入新对位
            n = db.execute("SELECT COUNT(*) n FROM alignments").fetchone()["n"]
            active = db.execute(
                "SELECT COUNT(*) n FROM alignments WHERE status='active'"
            ).fetchone()["n"]
            submitted = db.execute(
                "SELECT COUNT(*) n FROM alignments WHERE origin='submitted'"
            ).fetchone()["n"]
            self.assertEqual(n, 5)
            self.assertEqual(active, 5)
            self.assertEqual(submitted, 0)
            # 但审计记录保留
            runs = db.execute("SELECT * FROM runs").fetchall()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "no_solution")
        finally:
            db.close()

    # ---------- 非法输入 ----------
    def test_invalid_payload_same_image(self):
        r = self.client.post("/api/submit", json={
            "image_a": "img0", "image_b": "img0",
            "ax": 10, "ay": 10, "bx": 20, "by": 20,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["status"], "invalid")

    def test_invalid_payload_out_of_range(self):
        r = self.client.post("/api/submit", json={
            "image_a": "img0", "image_b": "img1",
            "ax": 9999, "ay": 10, "bx": 20, "by": 20,
        })
        self.assertEqual(r.status_code, 400)

    # ---------- 表单 PRG 通道 ----------
    def test_form_submit_redirects_to_run(self):
        d = DEMO_SOLVABLE
        r = self.client.post("/submit", data={
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn("/?run=", r.headers["Location"])
        follow = self.client.get(r.headers["Location"])
        self.assertEqual(follow.status_code, 200)
        self.assertIn("已采用新对位", follow.get_data(as_text=True))

    # ---------- 重置 ----------
    def test_reset_restores_seed(self):
        d = DEMO_SOLVABLE
        self.client.post("/api/submit", json={
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        })
        r = self.client.post("/api/reset")
        self.assertEqual(r.status_code, 200)
        st = r.get_json()["state"]
        img2 = next(i for i in st["images"] if i["id"] == "img2")
        self.assertAlmostEqual(img2["tx"], 830)
        self.assertEqual(len(st["alignments"]), 5)
        self.assertEqual(st["runs"], [])

    def test_form_reset_route(self):
        r = self.client.post("/reset")
        self.assertEqual(r.status_code, 302)


class VersionDeltaTests(unittest.TestCase):
    """增量协议 / 跨标签页版本冲突（本次不重载改造的后端契约）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_mural.db"
        self.app = create_app(database=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def _submit(self, version, payload=None):
        d = payload or DEMO_SOLVABLE
        body = {
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        }
        if version is not None:
            body["base_version"] = version
        return self.client.post("/api/submit", json=body)

    def test_state_starts_at_version_1(self):
        st = self.client.get("/api/state").get_json()
        self.assertEqual(st["version"], 1)
        v = self.client.get("/api/version").get_json()
        self.assertEqual(v["version"], 1)
        # 页面根节点也带版本
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="page-state"', html)
        self.assertIn('data-state-version="1"', html)

    def test_same_version_applied_returns_scoped_delta(self):
        r = self._submit(1)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["version"], 2)
        delta = body["delta"]
        self.assertIsNotNone(delta)

        # 只有 img2 真的移动；没动的样片不出现在增量图层里
        self.assertEqual([i["id"] for i in delta["images"]], ["img2"])
        img2 = delta["images"][0]
        self.assertAlmostEqual(img2["tx"], 800)
        self.assertAlmostEqual(img2["ty"], 0)
        self.assertNotIn("img0", [i["id"] for i in delta["images"]])

        # 撤下的 DW-02/DW-03（id 2/3）既要从标记层删除，也要在台账标撤
        self.assertEqual(sorted(delta["removed_alignment_ids"]), [2, 3])
        self.assertEqual(sorted(delta["alignment_marks_remove"]), [2, 3])

        # 新对位 DW-06 的标记需要新增；保留标记中没有任何一个端点样片移动，
        # 因此 upsert 只含新标记。
        self.assertEqual([m["code"] for m in delta["alignment_marks_upsert"]],
                         ["DW-06"])
        mark = delta["alignment_marks_upsert"][0]
        for key in ("axm", "aym", "bxm", "bym", "mx", "my"):
            self.assertIn(key, mark)

        # 随 img2 移位的两条裂缝下发新总图坐标
        crack_codes = {c["code"]: (c["master_x"], c["master_y"])
                       for c in delta["cracks"]}
        self.assertEqual(crack_codes["LF-03"], (960.0, 200.0))
        self.assertEqual(crack_codes["LF-04"], (1120.0, 90.0))

        # 台账新行 + 总数
        self.assertEqual(delta["alignment_total"], 6)
        self.assertEqual(
            [(a["code"], a["status"], a["reviewed"])
             for a in delta["alignments_upsert"]],
            [("DW-06", "active", 1)],
        )

    def test_stale_version_conflicts_with_full_state_and_writes_nothing(self):
        # 另一个标签页先提交：v1 -> v2
        self.assertEqual(self._submit(1).status_code, 200)

        # 当前页仍持 v1：必须 409 并回整份状态
        r = self._submit(1)
        self.assertEqual(r.status_code, 409)
        body = r.get_json()
        self.assertEqual(body["status"], "stale_state")
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["state"]["version"], 2)
        self.assertEqual(len(body["state"]["alignments"]), 6)
        self.assertEqual(len(body["state"]["alignment_marks"]), 4)

        # 冲突不写任何 run / alignment（这次提交没有真正发生）
        db = connect(self.db_path)
        try:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"], 1)
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM alignments").fetchone()["n"], 6)
        finally:
            db.close()

        # 补齐到 v2 后再提交即可成功（再 +1）
        r2 = self._submit(2)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["version"], 3)

    def test_no_solution_keeps_version_and_delta_null(self):
        d = DEMO_NO_SOLUTION
        r = self.client.post("/api/submit", json={
            "base_version": 1,
            "image_a": d["image_a"], "image_b": d["image_b"],
            "ax": d["ax"], "ay": d["ay"], "bx": d["bx"], "by": d["by"],
        })
        body = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body["status"], "no_solution")
        self.assertEqual(body["version"], 1)
        self.assertIsNone(body["delta"])
        # 审计记录仍写
        st = self.client.get("/api/state").get_json()
        self.assertEqual(st["version"], 1)
        self.assertEqual(len(st["runs"]), 1)

    def test_reset_bumps_version_and_stale_client_must_resync(self):
        self.assertEqual(self._submit(1).get_json()["version"], 2)
        r = self.client.post("/api/reset")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["version"], 3)
        self.assertEqual(r.get_json()["state"]["version"], 3)

        # 重置后旧客户端的 base_version=2 也已过期
        old = self._submit(2)
        self.assertEqual(old.status_code, 409)
        self.assertEqual(old.get_json()["status"], "stale_state")

        # 重取完整状态（5 条对位、无记录）后可正常提交
        st = self.client.get("/api/state").get_json()
        self.assertEqual(st["version"], 3)
        self.assertEqual(len(st["alignments"]), 5)
        self.assertEqual(st["runs"], [])
        ok = self._submit(3)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["version"], 4)

    def test_submit_without_version_still_supported(self):
        # 传统调用方/旧前端不带 base_version：不做冲突检查
        r = self._submit(None)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["version"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
