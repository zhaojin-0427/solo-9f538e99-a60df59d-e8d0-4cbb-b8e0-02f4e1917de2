# -*- coding: utf-8 -*-
"""SQLite 连接、建表与初始化。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import current_app, g

from .seed_data import seed_if_empty

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    file        TEXT NOT NULL,
    w           INTEGER NOT NULL,
    h           INTEGER NOT NULL,
    is_base     INTEGER NOT NULL DEFAULT 0,
    tx          REAL NOT NULL,
    ty          REAL NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE,
    image_a     TEXT NOT NULL REFERENCES images(id),
    image_b     TEXT NOT NULL REFERENCES images(id),
    ax          REAL NOT NULL,
    ay          REAL NOT NULL,
    bx          REAL NOT NULL,
    by          REAL NOT NULL,
    reviewed    INTEGER NOT NULL DEFAULT 0,   -- 1 已复核
    status      TEXT NOT NULL DEFAULT 'active', -- active / withdrawn
    origin      TEXT NOT NULL DEFAULT 'seed',   -- seed / submitted
    note        TEXT,
    run_id      INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS cracks (
    id          TEXT PRIMARY KEY,
    image_id    TEXT NOT NULL REFERENCES images(id),
    code        TEXT NOT NULL,
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    tagged      INTEGER NOT NULL DEFAULT 0,     -- 1 已贴签
    note        TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    status       TEXT NOT NULL,                 -- applied / no_solution
    image_a      TEXT,
    image_b      TEXT,
    ax           REAL, ay REAL, bx REAL, by REAL,
    payload_json TEXT,
    result_json  TEXT,
    summary      TEXT
);

CREATE INDEX IF NOT EXISTS idx_align_status ON alignments(status);
CREATE INDEX IF NOT EXISTS idx_cracks_image ON cracks(image_id);
"""


def default_db_path() -> Path:
    env = os.environ.get("MURAL_DB")
    if env:
        return Path(env)
    # 仓库根/data/mural.db（app/ 的上一级）
    return Path(__file__).resolve().parent.parent / "data" / "mural.db"


def connect(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    path = Path(db_path or current_app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path: str | os.PathLike | None = None) -> Path:
    """建表并在空库时写入种子数据。返回数据库路径。"""
    path = Path(db_path or default_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10)
    try:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        db.commit()
        seed_if_empty(db)
    finally:
        db.close()
    return path


def init_app(app):
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def _init_db_command():  # pragma: no cover
        p = init_db(app.config["DATABASE"])
        print("initialized", p)
