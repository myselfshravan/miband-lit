#!/usr/bin/env python3
"""Shared SQLite store between the band service and the Streamlit dashboard.

Two separate processes touch this DB, so we use WAL mode + a busy timeout to
keep concurrent reads/writes from stepping on each other.
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).with_name("miband.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS readings ("
            " ts REAL NOT NULL, bpm INTEGER NOT NULL)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS commands ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts REAL NOT NULL,"
            " kind TEXT NOT NULL,"
            " payload TEXT,"
            " status TEXT NOT NULL DEFAULT 'pending')"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS status ("
            " key TEXT PRIMARY KEY, value TEXT)"
        )


# --- Heart-rate readings ---------------------------------------------------
def add_reading(bpm: int, ts: float | None = None):
    with get_conn() as c:
        c.execute("INSERT INTO readings(ts, bpm) VALUES (?, ?)",
                  (ts if ts is not None else time.time(), int(bpm)))


def recent_readings(seconds: float = 300):
    cutoff = time.time() - seconds
    with get_conn() as c:
        rows = c.execute(
            "SELECT ts, bpm FROM readings WHERE ts >= ? ORDER BY ts", (cutoff,)
        ).fetchall()
    return [(r["ts"], r["bpm"]) for r in rows]


def latest_reading():
    with get_conn() as c:
        r = c.execute("SELECT ts, bpm FROM readings ORDER BY ts DESC LIMIT 1").fetchone()
    return (r["ts"], r["bpm"]) if r else None


# --- Commands (dashboard -> band service) ----------------------------------
def add_command(kind: str, payload: dict | None = None):
    with get_conn() as c:
        c.execute(
            "INSERT INTO commands(ts, kind, payload, status) VALUES (?, ?, ?, 'pending')",
            (time.time(), kind, json.dumps(payload or {})),
        )


def pending_commands():
    with get_conn() as c:
        rows = c.execute(
            "SELECT id, kind, payload FROM commands WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    return [(r["id"], r["kind"], json.loads(r["payload"] or "{}")) for r in rows]


def mark_command(cmd_id: int, status: str):
    with get_conn() as c:
        c.execute("UPDATE commands SET status = ? WHERE id = ?", (status, cmd_id))


def recent_commands(limit: int = 10):
    with get_conn() as c:
        rows = c.execute(
            "SELECT ts, kind, payload, status FROM commands ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [(r["ts"], r["kind"], json.loads(r["payload"] or "{}"), r["status"]) for r in rows]


# --- Service status (band service -> dashboard) ----------------------------
def set_status(key: str, value):
    with get_conn() as c:
        c.execute(
            "INSERT INTO status(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_status(key: str, default=None):
    with get_conn() as c:
        r = c.execute("SELECT value FROM status WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
