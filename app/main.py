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
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                label TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );
            CREATE TABLE IF NOT EXISTS signins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ts TEXT NOT NULL,
                event_id INTEGER REFERENCES events(id)
            );
            CREATE INDEX IF NOT EXISTS signins_ts ON signins(ts);
            CREATE INDEX IF NOT EXISTS signins_event ON signins(event_id);
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
    event_token: str | None = Field(default=None, max_length=64)


class ApproveIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=8, max_length=128)


class EventStartIn(BaseModel):
    label: str | None = Field(default=None, max_length=100)


def get_active_event(conn) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM events WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.post("/api/signin")
def signin(body: SigninIn):
    name = body.name.strip()
    with db() as conn:
        event_id: int | None = None
        if body.event_token:
            ev = conn.execute(
                "SELECT id FROM events WHERE token = ? AND ended_at IS NULL",
                (body.event_token,),
            ).fetchone()
            if ev is None:
                raise HTTPException(status_code=410, detail="event is not active")
            event_id = ev["id"]
        row = conn.execute("SELECT key FROM students WHERE name = ?", (name,)).fetchone()
        if row is None:
            return {"status": "needs_approval", "name": name}
        if not secrets.compare_digest(row["key"], body.key):
            raise HTTPException(status_code=403, detail="key does not match this name")
        ts = now_iso()
        conn.execute(
            "INSERT INTO signins(name, ts, event_id) VALUES(?, ?, ?)",
            (name, ts, event_id),
        )
        return {"status": "ok", "name": name, "ts": ts, "event_id": event_id}


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
        ev = get_active_event(conn)
        event_id = ev["id"] if ev else None
        conn.execute(
            "INSERT INTO signins(name, ts, event_id) VALUES(?, ?, ?)",
            (name, ts, event_id),
        )
        return {"status": "approved", "name": name, "ts": ts}


@app.get("/api/attendance", dependencies=[Depends(require_teacher)])
def attendance(limit: int = 200, event_id: int | None = None):
    limit = max(1, min(limit, 1000))
    with db() as conn:
        if event_id is None:
            rows = conn.execute(
                "SELECT name, ts FROM signins ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, ts FROM signins WHERE event_id = ? ORDER BY id DESC LIMIT ?",
                (event_id, limit),
            ).fetchall()
        return {"signins": [dict(r) for r in rows]}


@app.post("/api/event/start", dependencies=[Depends(require_teacher)])
def event_start(body: EventStartIn):
    ts = now_iso()
    with db() as conn:
        conn.execute("UPDATE events SET ended_at = ? WHERE ended_at IS NULL", (ts,))
        token = secrets.token_urlsafe(12)
        cur = conn.execute(
            "INSERT INTO events(token, label, started_at) VALUES(?, ?, ?)",
            (token, body.label, ts),
        )
        return {"id": cur.lastrowid, "token": token, "label": body.label, "started_at": ts}


@app.post("/api/event/end", dependencies=[Depends(require_teacher)])
def event_end():
    with db() as conn:
        conn.execute("UPDATE events SET ended_at = ? WHERE ended_at IS NULL", (now_iso(),))
        return {"status": "ended"}


@app.get("/api/event/active", dependencies=[Depends(require_teacher)])
def event_active():
    with db() as conn:
        ev = get_active_event(conn)
        return {"active": dict(ev) if ev else None}


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


@app.get("/event")
def event_page():
    return FileResponse(STATIC_DIR / "event.html")


@app.get("/e/{token}")
def event_signin_page(token: str):
    return FileResponse(STATIC_DIR / "signin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
