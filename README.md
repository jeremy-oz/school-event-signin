# school-event-signin

A small FastAPI + SQLite mobile web app for signing students into events with a QR code.

## How it works

Two flows. The **event QR** is the default (faster — students self-serve in parallel); the **scan-students** flow is for first-time approvals or as a backup.

### Default: students scan an event QR (fast)

1. Student opens `/me` once, types their name. The page generates a random key in `localStorage` and shows their personal QR. They get the teacher to approve them once via `/scan` (one-time per student).
2. At each event, the teacher opens `/event`, enters the password, hits **Start new event**. The page displays a fresh QR encoding `https://your-domain/e/<token>`.
3. Students point their phone camera at the QR. Their browser opens the URL, reads their stored `{name, key}`, posts to the server with the event token, and shows "Signed in".
4. The teacher's `/event` page polls and shows the live attendance list.

Each event has a fresh token; ending the event (or starting a new one) invalidates it. Tokens are not rotating during an event — a forwarded link is reusable until the event ends. Since the teacher is in the room and sees the live list, an absent student appearing there is easy to spot.

### Backup: teacher scans student QRs

`/scan` opens the camera, scans student QRs (same `{name, key}` payload). First-time scans prompt the teacher to approve and lock the key. Useful for first-time approval or when a student can't scan themselves.

### Log

`/log` shows recent sign-ins and the approved roster.

## Run locally

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
TEACHER_PASSWORD=yourpassword .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<your-ip>:8000/`. Phone cameras require **HTTPS** (or `localhost`) — see deploy.

## Environment variables

- `TEACHER_PASSWORD` — required in production. Defaults to `changeme`.
- `DB_PATH` — path to the SQLite file. Defaults to `./attendance.db`.

## Deploy on Hetzner

1. Provision a small Cloud VM (CX11 is plenty). SSH in, install Python 3.11+ and `nginx`.
2. Clone this repo, create the venv, install requirements (steps above).
3. Create `/etc/systemd/system/signin.service`:
   ```
   [Unit]
   Description=school-event-signin
   After=network.target

   [Service]
   WorkingDirectory=/opt/school-event-signin
   Environment=TEACHER_PASSWORD=changeme-to-something-real
   Environment=DB_PATH=/var/lib/signin/attendance.db
   ExecStart=/opt/school-event-signin/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   Restart=always
   User=www-data

   [Install]
   WantedBy=multi-user.target
   ```
   Then `mkdir -p /var/lib/signin && chown www-data /var/lib/signin && systemctl enable --now signin`.
4. Point a domain at the VM, configure nginx to reverse-proxy `https://signin.example.com` to `127.0.0.1:8000`, and get a TLS cert with `certbot --nginx`. **HTTPS is required** — phone cameras refuse to start on plain HTTP.

## Backups

The whole app state is one file (`attendance.db`). A nightly `cp` to object storage is enough.

## API

- `POST /api/signin` `{name, key, event_token?}` — `200 {status: "ok"|"needs_approval"}`, `403` on key mismatch, `410` if `event_token` is given but no event with that token is active.
- `POST /api/approve` `{name, key}` (header `x-teacher-password`) — locks the key to the name; if an event is active, also records a sign-in for it.
- `POST /api/event/start` `{label?}` (header `x-teacher-password`) — ends any active event and starts a new one. Returns `{id, token, label, started_at}`.
- `POST /api/event/end` (header `x-teacher-password`) — ends the active event.
- `GET /api/event/active` (header `x-teacher-password`) — current active event or `null`.
- `GET /api/attendance?event_id=N` (header `x-teacher-password`) — recent sign-ins, optionally filtered by event.
- `GET /api/students` (header `x-teacher-password`) — approved roster.
