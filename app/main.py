import os
import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "attendance.db"))
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

app = FastAPI(title="School Event Sign-In")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                name TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                approved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS signins_ts ON signins(ts);
            """
        )


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def require_teacher(x_teacher_password: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_teacher_password, TEACHER_PASSWORD):
        raise HTTPException(status_code=401, detail="bad teacher password")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SigninIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=8, max_length=128)


class ApproveIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=8, max_length=128)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.post("/api/signin")
def signin(body: SigninIn):
    name = body.name.strip()
    with db() as conn:
        row = conn.execute("SELECT key FROM students WHERE name = ?", (name,)).fetchone()
        if row is None:
            return {"status": "needs_approval", "name": name}
        if not secrets.compare_digest(row["key"], body.key):
            raise HTTPException(status_code=403, detail="key does not match this name")
        conn.execute("INSERT INTO signins(name, ts) VALUES(?, ?)", (name, now_iso()))
        return {"status": "ok", "name": name, "ts": now_iso()}


@app.post("/api/approve", dependencies=[Depends(require_teacher)])
def approve(body: ApproveIn):
    name = body.name.strip()
    with db() as conn:
        existing = conn.execute("SELECT key FROM students WHERE name = ?", (name,)).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="name already locked to a key")
        ts = now_iso()
        conn.execute(
            "INSERT INTO students(name, key, approved_at) VALUES(?, ?, ?)",
            (name, body.key, ts),
        )
        conn.execute("INSERT INTO signins(name, ts) VALUES(?, ?)", (name, ts))
        return {"status": "approved", "name": name, "ts": ts}


@app.get("/api/attendance", dependencies=[Depends(require_teacher)])
def attendance(limit: int = 200):
    limit = max(1, min(limit, 1000))
    with db() as conn:
        rows = conn.execute(
            "SELECT name, ts FROM signins ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"signins": [dict(r) for r in rows]}


@app.get("/api/students", dependencies=[Depends(require_teacher)])
def students():
    with db() as conn:
        rows = conn.execute(
            "SELECT name, approved_at FROM students ORDER BY name"
        ).fetchall()
        return {"students": [dict(r) for r in rows]}


STATIC_DIR = ROOT / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/me")
def me_page():
    return FileResponse(STATIC_DIR / "student.html")


@app.get("/scan")
def scan_page():
    return FileResponse(STATIC_DIR / "teacher.html")


@app.get("/log")
def log_page():
    return FileResponse(STATIC_DIR / "log.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
