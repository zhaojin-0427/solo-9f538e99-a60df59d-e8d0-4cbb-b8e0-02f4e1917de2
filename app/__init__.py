# -*- coding: utf-8 -*-
"""Flask 应用工厂与路由。"""

from __future__ import annotations

from pathlib import Path

from flask import (
    Flask, jsonify, redirect, render_template, request, url_for,
)

from .db import get_db, init_app, init_db
from .seed_data import reset_all
from .services import (
    ValidationError, get_run, load_state, submit_alignment,
)
from .scene import ensure_sample_files


def create_app(database: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "mural-alignment-local"
    if database is None:
        from .db import default_db_path
        database = default_db_path()
    app.config["DATABASE"] = str(database)

    init_app(app)
    init_db(app.config["DATABASE"])
    ensure_sample_files()

    @app.template_filter("num")
    def _num(v):
        """整数显示为整数，浮点保留一位。"""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return v
        if abs(f - round(f)) < 1e-6:
            return str(int(round(f)))
        return f"{f:.1f}"

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/")
    def index():
        db = get_db()
        state = load_state(db)
        run_id = request.args.get("run", type=int)
        current_run = get_run(db, run_id) if run_id else (
            state["runs"][0] if state["runs"] else None
        )
        return render_template(
            "index.html",
            state=state,
            run=current_run,
            active_nav="operate",
        )

    # ---------- 传统表单提交（无 JS 也可用，PRG） ----------
    @app.post("/submit")
    def submit_form():
        db = get_db()
        try:
            run = submit_alignment(db, request.form)
        except ValidationError as exc:
            return render_template(
                "index.html",
                state=load_state(db),
                run=None,
                form_error=str(exc),
                form_values=request.form,
            ), 400
        return redirect(url_for("index", run=run["id"]))

    @app.post("/reset")
    def reset_form():
        db = get_db()
        reset_all(db)
        return redirect(url_for("index"))

    # ---------- JSON API ----------
    @app.get("/api/state")
    def api_state():
        return jsonify(load_state(get_db()))

    @app.post("/api/submit")
    def api_submit():
        db = get_db()
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()
        try:
            run = submit_alignment(db, data)
        except ValidationError as exc:
            return jsonify(status="invalid", error=str(exc)), 400
        return jsonify(_api_run(run))

    @app.post("/api/reset")
    def api_reset():
        db = get_db()
        reset_all(db)
        return jsonify(ok=True, state=load_state(db))

    @app.get("/api/runs/<int:run_id>")
    def api_run_detail(run_id: int):
        run = get_run(get_db(), run_id)
        if not run:
            return jsonify(error="run not found"), 404
        return jsonify(_api_run(run))

    return app


def _api_run(run: dict) -> dict:
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "status": run["status"],
        "summary": run["summary"],
        "submission": {
            "image_a": run["image_a"], "image_b": run["image_b"],
            "ax": run["ax"], "ay": run["ay"],
            "bx": run["bx"], "by": run["by"],
        },
        **run["result"],
        # 无解诊断放在 reason 字段（若有）
        "reason": run["result"].get("reason", ""),
    }
