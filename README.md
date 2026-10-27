# AttendAI — Advanced Attendance System

A final-year project starter built with Flask, PostgreSQL, OpenCV YuNet/SFace face recognition, SQLAlchemy, Flask-Login, and a responsive dashboard.

## What is included

- Teacher/admin login with Werkzeug password hashing and role checks
- Student registration with explicit biometric-consent confirmation
- Face detection using YuNet and face embeddings using SFace
- Live browser camera capture and server-side face matching
- Open/close class sessions and prevent duplicate student/session attendance
- Weekly timetable: recurring class slots with room/teacher/course clash detection, a "Today's timetable" dashboard panel, and one-click session start from a slot
- Attendance summary, percentage table, CSV export, and admin-only audit trail
- CSRF protection, secure cookie defaults, upload limits, and server-side validation
- Tests for login, health check, database entities, and duplicate attendance constraint

## Important limitations and responsible use

This is an educational prototype, not a certified biometric access-control product. Face matching can make false matches and false rejections. SFace cosine similarity is a model score, not a calibrated probability. The default threshold (`FACE_MATCH_THRESHOLD=0.42`) is a starting point only; validate it using consented representative data and document false-accept/false-reject rates before any real deployment. Lighting, camera quality, pose, demographic variation, and enrollment-image quality can change performance.

**Liveness / anti-spoofing is not implemented.** A photo or replayed video may be accepted if it matches an enrolled face. Do not use this prototype as proof of physical presence or for high-stakes disciplinary decisions. Provide a teacher override/manual fallback and an appeal process. Obtain informed consent, offer a non-biometric alternative, define retention/deletion periods, restrict access, encrypt backups and traffic, and follow your institution's privacy rules and applicable law. Face embeddings are biometric data even if the original photo is not stored.

The app does not save uploaded enrollment photos; it extracts and stores a face embedding. This is not a guarantee of privacy by itself. Database backups, logs, administrator access, and host security still matter.

## Requirements

- Python 3.11 or 3.12 recommended
- PostgreSQL 14+ (or a compatible current version)
- Webcam and a modern browser; camera permission generally works on `localhost` or HTTPS
- Internet access once to download the OpenCV Zoo ONNX models

## 1. Create PostgreSQL database

Using `psql` as a PostgreSQL administrator:

```sql
CREATE USER attendance_user WITH PASSWORD 'replace_with_a_long_password';
CREATE DATABASE attendance_db OWNER attendance_user;
```

If your database password contains characters such as `@`, `:`, `/`, or `#`, URL-encode those characters in `DATABASE_URL`.

## 2. Set up Python

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\\Scripts\\activate    # Windows PowerShell
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`. Generate a strong secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Set at least:

```dotenv
SECRET_KEY=paste-a-random-secret-here
DATABASE_URL=postgresql+psycopg://attendance_user:URL_ENCODED_PASSWORD@localhost:5432/attendance_db
BOOTSTRAP_ADMIN_EMAIL=admin@your-university.edu
BOOTSTRAP_ADMIN_PASSWORD=use-a-unique-password-of-at-least-12-characters
FACE_MATCH_THRESHOLD=0.42
SESSION_COOKIE_SECURE=false
```

Use `SESSION_COOKIE_SECURE=true` behind HTTPS in deployment. Never commit `.env` or real biometric data.

## 3. Download face models

```bash
python scripts/download_models.py
```

This downloads the YuNet detector and SFace recognizer ONNX files into `models/`. If the upstream GitHub URL changes, get the official files from the OpenCV Zoo repositories and place them under the exact filenames shown by the script. Review the model/repository licenses before redistribution or commercial use. Model files are not included in the source ZIP.

## 4. Initialize database and run

```bash
flask --app app.py init-db
flask --app app.py check-db
flask --app app.py run --host 127.0.0.1 --port 5000
```

Open <http://127.0.0.1:5000>. Sign in using the bootstrap admin credentials from `.env`. After the first admin is created, change/remove bootstrap credentials in `.env`; they will not overwrite an existing admin. Create additional users using:

```bash
flask --app app.py create-user
```

The command prompts for name, email, role, and password. Use a password of at least 12 characters.

## 5. Use the app

1. Sign in as an administrator.
2. Open **Students** and register a student with a clear, consented image showing only one face.
3. Create a class under **Class sessions**. A newly created session is open.
4. Open **Take attendance**, select the session, start the camera, and click **Scan & mark attendance**.
5. Review the match message and score. Uncertain matches should be handled manually by authorized staff.
6. View **Analytics & reports** and export CSV.
7. Administrators can view the **Audit trail**.

The web browser captures a single frame only after the scan button is clicked. The app does not continuously upload video.

## Timetable

- **Timetable** (sidebar) shows the weekly grid. Administrators add and remove slots (subject, course, day, start/end time, room, teacher); teachers can view it, filter by course or "My classes", and start sessions.
- Saving a slot is refused if it overlaps another slot in the same room, with the same teacher, or for the same course.
- On the current day, **Start session** creates a normal class session linked to the slot (once per slot per day) and opens it for attendance. The dashboard lists today's slots with the same button.
- Slot times are wall-clock times in the `TIMEZONE` setting in `.env` (default `Asia/Kolkata`).
- **Upgrading an existing database:** run `flask --app app.py init-db` once. It creates the new `timetable_entry` table and adds `class_session.timetable_entry_id`; existing data is kept.

## 6. Run tests

Tests use an isolated in-memory SQLite database and do not need PostgreSQL or model files:

```bash
pytest -q
```

For a database connection check in your configured environment:

```bash
flask --app app.py check-db
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session and CSRF secret | development fallback; replace it |
| `DATABASE_URL` | SQLAlchemy database connection | local SQLite fallback |
| `FACE_MATCH_THRESHOLD` | Minimum SFace cosine score | `0.42` (must be validated) |
| `MAX_CONTENT_LENGTH_MB` | Maximum request size | `8` |
| `SESSION_COOKIE_SECURE` | Require HTTPS for session cookie | `false` for localhost |
| `BOOTSTRAP_ADMIN_EMAIL` | Initial admin email | blank |
| `BOOTSTRAP_ADMIN_PASSWORD` | Initial admin password | blank |

## Database design

- `user`: staff identities, role, password hash, active status
- `student`: student ID, name, course, consent timestamp, optional face embedding
- `class_session`: class title, course, open/closed status, creator
- `attendance`: student/session relation, timestamp, method, similarity score; unique `(student_id, session_id)` constraint
- `audit_log`: actor, action, entity, limited event metadata, IP, timestamp

## Security checklist before deployment

- Serve only over HTTPS; set `SESSION_COOKIE_SECURE=true`.
- Replace the development secret and rotate credentials; use a secret manager in deployment.
- Use a least-privilege PostgreSQL role, firewall database access, encrypt backups, and test restore/deletion procedures.
- Add rate limiting and monitoring for login/API abuse; consider reverse-proxy request limits.
- Do not expose the database, debug server, model files, or `.env` publicly.
- Validate face threshold on a held-out dataset. Log outcomes without storing raw frames or face embeddings in audit logs.
- Implement and validate liveness/anti-spoofing if required; this project does not provide it.
- Have a human verification path, alternative attendance method, retention schedule, consent process, and documented privacy assessment.
- Consider a migration tool (e.g. Flask-Migrate/Alembic) rather than `create_all()` for production schema changes.

## Troubleshooting

- **Face models missing:** run `python scripts/download_models.py`.
- **No face detected:** use a brighter room, a frontal face, and a higher-resolution image.
- **Multiple faces detected:** upload a single-person enrollment image and scan one person at a time.
- **Camera blocked:** allow browser permission and use `localhost` or HTTPS.
- **PostgreSQL connection failed:** confirm service is running, credentials/database exist, and `DATABASE_URL` is correct; then run `flask --app app.py check-db`.
- **Recognition misses a student:** do not blindly lower the threshold. Collect consented validation examples, review false-match risk, and calibrate a threshold; use manual verification as a fallback.
- **CSRF error:** refresh the page to obtain a fresh token and ensure browser cookies are enabled.

## Suggested extensions for a stronger capstone

- Multi-image enrollment and template quality checks
- Verified liveness detection evaluated against print/replay attacks
- Manual attendance and correction workflow with reason + audit entry
- Student self-service view with privacy-safe access controls
- Course enrollment and per-course denominator for accurate attendance percentages
- Database migrations, rate limiting, alerting, deployment with Gunicorn + Nginx, and CI
- Evaluation report: precision, recall, false acceptance rate, false rejection rate, latency, and performance across lighting conditions
