import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("T2CAD_DATA", ROOT / "data")).resolve()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "t2cad.sqlite3", timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT, created TEXT, current_revision TEXT);
        CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, project_id TEXT, created TEXT, design TEXT, result TEXT, folder TEXT, parent TEXT);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, role TEXT, content TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project_id TEXT, status TEXT, created TEXT, base_revision TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, type TEXT, data TEXT, created TEXT);
        """)
        db.execute("UPDATE jobs SET status='interrupted', error='服务重启，任务已中断；可以重新提交。' WHERE status IN ('queued','running')")


def query(sql, args=(), one=False):
    with connection() as db:
        rows = db.execute(sql, args).fetchall()
    values = [dict(row) for row in rows]
    return (values[0] if values else None) if one else values


def execute(sql, args=()):
    with connection() as db:
        cur = db.execute(sql, args)
        return cur.lastrowid


def event(job_id, kind, data):
    return execute("INSERT INTO events(job_id,type,data,created) VALUES(?,?,?,?)", (job_id, kind, json.dumps(data, ensure_ascii=False), now()))


def message(project_id, role, content):
    execute("INSERT INTO messages(project_id,role,content,created) VALUES(?,?,?,?)", (project_id, role, content, now()))


def revision(rid):
    row = query("SELECT * FROM revisions WHERE id=?", (rid,), one=True)
    if row:
        row["design"] = json.loads(row["design"])
        row["result"] = json.loads(row["result"])
    return row
