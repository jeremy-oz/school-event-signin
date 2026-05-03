# school-event-signin

A small FastAPI + SQLite mobile web app for signing students into events with a QR code.

## How it works

- Each student opens `/me` on their phone, types their name, and the page generates a random key stored in `localStorage` plus a QR code containing `{name, key}`. They bookmark the page.
- The teacher opens `/scan` on their phone, enters a shared password (saved on that device), and points the camera at the QR.
- First time a student is seen, the teacher confirms; the server locks that key to that name. Future scans by that student auto-sign-in. A scan with the right name but a different key is rejected (impostor protection).
- `/log` shows recent sign-ins and approved students.

QR codes are static (not rotating). Since the teacher is physically present to scan, a screenshot can't be abused remotely, and rotation would hurt reliability (clock skew, battery saver, no signal).

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

- `POST /api/signin` `{name, key}` — `200 {status: "ok"|"needs_approval"}` or `403` on key mismatch.
- `POST /api/approve` `{name, key}` (header `x-teacher-password`) — locks the key to the name.
- `GET /api/attendance` (header `x-teacher-password`) — recent sign-ins.
- `GET /api/students` (header `x-teacher-password`) — approved roster.
