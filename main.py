import csv
import io
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import User, Student, ClassSession, Attendance, AuditLog, TimetableEntry
from audit import log_action
from face_engine import FaceEngine, FaceEngineError

main_bp = Blueprint("main", __name__)


def require_staff():
    return current_user.is_authenticated and current_user.role in ("admin", "teacher")


def face_engine():
    # Lazy-load so login and reporting work even before model files are downloaded.
    if "_face_engine" not in current_app.extensions:
        current_app.extensions["_face_engine"] = FaceEngine(current_app.config["MODEL_DIR"])
    return current_app.extensions["_face_engine"]


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def local_tz():
    try:
        return ZoneInfo(current_app.config.get("TIMEZONE", "UTC"))
    except Exception:
        return timezone.utc


def sessions_today_by_entry(entry_ids, tz):
    """Map timetable_entry_id -> the ClassSession already started for it today (local date)."""
    if not entry_ids:
        return {}
    start_local = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = (start_local + timedelta(days=1)).astimezone(timezone.utc)
    rows = db.session.scalars(db.select(ClassSession).where(
        ClassSession.timetable_entry_id.in_(entry_ids),
        ClassSession.starts_at >= start_utc, ClassSession.starts_at < end_utc)).all()
    return {row.timetable_entry_id: row for row in rows}


def todays_classes():
    """Today's timetable entries with a live status: upcoming / now / done."""
    tz = local_tz()
    now_local = datetime.now(tz)
    entries = db.session.scalars(db.select(TimetableEntry).where(
        TimetableEntry.active.is_(True), TimetableEntry.day_of_week == now_local.weekday()
    ).order_by(TimetableEntry.start_time)).all()
    started = sessions_today_by_entry([e.id for e in entries], tz)
    now_t = now_local.time().replace(tzinfo=None)
    result = []
    for entry in entries:
        if entry.start_time <= now_t < entry.end_time:
            state = "now"
        elif now_t >= entry.end_time:
            state = "done"
        else:
            state = "upcoming"
        result.append({"entry": entry, "state": state, "session": started.get(entry.id)})
    return result


def parse_clock(value):
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").time()
    except ValueError:
        return None


def timetable_conflicts(day, start, end, room, teacher_id, course, exclude_id=None):
    """Return human-readable clashes with existing active entries on the same day."""
    stmt = db.select(TimetableEntry).where(
        TimetableEntry.active.is_(True), TimetableEntry.day_of_week == day,
        TimetableEntry.start_time < end, TimetableEntry.end_time > start)
    if exclude_id:
        stmt = stmt.where(TimetableEntry.id != exclude_id)
    problems = []
    for other in db.session.scalars(stmt).all():
        span = f"{other.subject} ({other.start_time:%H:%M}-{other.end_time:%H:%M})"
        if room and other.room and other.room.lower() == room.lower():
            problems.append(f"Room {other.room} is already used by {span}.")
        if teacher_id and other.teacher_id == teacher_id:
            problems.append(f"That teacher is already teaching {span}.")
        if other.course.lower() == course.lower():
            problems.append(f"Course {other.course} already has {span} at that time.")
    return problems


@main_bp.before_request
def staff_only():
    if request.endpoint and request.endpoint.startswith("main.") and request.endpoint not in ("main.health",):
        if not current_user.is_authenticated:
            return None  # @login_required handles the redirect on the route.
        if not require_staff():
            return ("Forbidden", 403)


@main_bp.get("/")
@login_required
def dashboard():
    today = datetime.now(timezone.utc).date()
    students_count = db.session.scalar(db.select(func.count(Student.id)).where(Student.active.is_(True))) or 0
    open_sessions = db.session.scalar(db.select(func.count(ClassSession.id)).where(ClassSession.is_open.is_(True))) or 0
    today_count = db.session.scalar(db.select(func.count(Attendance.id)).join(ClassSession).where(func.date(Attendance.marked_at) == today)) or 0
    recent = db.session.scalars(db.select(Attendance).order_by(Attendance.marked_at.desc()).limit(8)).all()
    sessions = db.session.scalars(db.select(ClassSession).order_by(ClassSession.starts_at.desc()).limit(10)).all()
    return render_template("dashboard.html", students_count=students_count, open_sessions=open_sessions,
                           today_count=today_count, recent=recent, sessions=sessions,
                           today_classes=todays_classes(), today_label=datetime.now(local_tz()).strftime("%A, %d %b"))


@main_bp.route("/students", methods=["GET", "POST"])
@login_required
def students():
    if request.method == "POST":
        code = request.form.get("student_code", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower() or None
        course = request.form.get("course", "General").strip() or "General"
        consent = request.form.get("biometric_consent") == "yes"
        upload = request.files.get("face_image")
        if not code or not name:
            flash("Student ID and name are required.", "danger")
        elif not consent:
            flash("Record informed consent before storing biometric data.", "danger")
        elif not upload or not upload.filename:
            flash("Upload a clear photo containing only the student's face.", "danger")
        elif db.session.scalar(db.select(Student.id).where(Student.student_code == code)):
            flash("That student ID already exists.", "danger")
        else:
            try:
                embedding = face_engine().embedding_from_bytes(upload.read())
                student = Student(student_code=code, name=name, email=email, course=course,
                                  face_embedding=embedding, consent_recorded_at=datetime.now(timezone.utc))
                db.session.add(student)
                db.session.flush()
                log_action("student_created_with_face", "student", student.id, {"student_code": code, "consent": True})
                db.session.commit()
                flash("Student registered and face embedding saved.", "success")
                return redirect(url_for("main.students"))
            except FaceEngineError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Student registration failed")
                flash("Could not register student. Check the server logs.", "danger")
    students_list = db.session.scalars(db.select(Student).order_by(Student.name.asc())).all()
    return render_template("students.html", students=students_list)


@main_bp.post("/students/<int:student_id>/deactivate")
@login_required
def deactivate_student(student_id):
    student = db.get_or_404(Student, student_id)
    student.active = False
    # Remove biometric template when deactivating, preserving only the attendance history.
    student.face_embedding = None
    log_action("student_deactivated_and_biometric_removed", "student", student.id)
    db.session.commit()
    flash("Student deactivated and stored face embedding removed.", "success")
    return redirect(url_for("main.students"))


@main_bp.route("/sessions", methods=["GET", "POST"])
@login_required
def sessions():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        course = request.form.get("course", "").strip()
        if not title or not course:
            flash("Session title and course are required.", "danger")
        else:
            session = ClassSession(title=title, course=course, created_by_id=current_user.id)
            db.session.add(session)
            db.session.flush()
            log_action("class_session_created", "class_session", session.id, {"title": title, "course": course})
            db.session.commit()
            flash("Class session created and opened.", "success")
            return redirect(url_for("main.sessions"))
    all_sessions = db.session.scalars(db.select(ClassSession).order_by(ClassSession.starts_at.desc())).all()
    return render_template("sessions.html", sessions=all_sessions)


@main_bp.post("/sessions/<int:session_id>/toggle")
@login_required
def toggle_session(session_id):
    session = db.get_or_404(ClassSession, session_id)
    session.is_open = not session.is_open
    if not session.is_open:
        session.ends_at = datetime.now(timezone.utc)
    else:
        session.ends_at = None
    log_action("class_session_toggled", "class_session", session.id, {"is_open": session.is_open})
    db.session.commit()
    flash("Session status updated.", "success")
    return redirect(url_for("main.sessions"))


@main_bp.route("/timetable", methods=["GET", "POST"])
@login_required
def timetable():
    form = {}
    if request.method == "POST":
        if not current_user.is_admin:
            return ("Forbidden: only administrators can edit the timetable", 403)
        form = request.form
        subject = form.get("subject", "").strip()
        course = form.get("course", "").strip()
        room = form.get("room", "").strip() or None
        day = form.get("day_of_week", type=int)
        teacher_id = form.get("teacher_id", type=int) or None
        start, end = parse_clock(form.get("start_time")), parse_clock(form.get("end_time"))
        teacher = db.session.get(User, teacher_id) if teacher_id else None
        error = None
        if not subject or not course:
            error = "Subject and course are required."
        elif day is None or not 0 <= day <= 6:
            error = "Choose a day of the week."
        elif not start or not end:
            error = "Enter valid start and end times."
        elif end <= start:
            error = "End time must be after the start time."
        elif teacher_id and (not teacher or not teacher.active):
            error = "Choose a valid teacher."
        if error:
            flash(error, "danger")
        else:
            problems = timetable_conflicts(day, start, end, room, teacher_id, course)
            if problems:
                for message in problems:
                    flash(message, "danger")
                flash("Slot not saved because of the clashes above.", "warning")
            else:
                entry = TimetableEntry(subject=subject, course=course, day_of_week=day, start_time=start,
                                       end_time=end, room=room, teacher_id=teacher_id)
                db.session.add(entry)
                db.session.flush()
                log_action("timetable_entry_created", "timetable_entry", entry.id, {
                    "subject": subject, "course": course, "day": DAY_NAMES[day],
                    "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
                db.session.commit()
                flash("Timetable slot added.", "success")
                return redirect(url_for("main.timetable"))

    course_filter = request.args.get("course", "").strip()
    mine = request.args.get("mine") == "1"
    stmt = db.select(TimetableEntry).where(TimetableEntry.active.is_(True)).order_by(
        TimetableEntry.day_of_week, TimetableEntry.start_time)
    if course_filter:
        stmt = stmt.where(TimetableEntry.course == course_filter)
    if mine:
        stmt = stmt.where(TimetableEntry.teacher_id == current_user.id)
    entries = db.session.scalars(stmt).all()
    courses = db.session.scalars(db.select(TimetableEntry.course).where(
        TimetableEntry.active.is_(True)).distinct().order_by(TimetableEntry.course)).all()
    teachers = db.session.scalars(db.select(User).where(User.active.is_(True)).order_by(User.name)).all()

    tz = local_tz()
    today_idx = datetime.now(tz).weekday()
    by_day = {i: [] for i in range(7)}
    for entry in entries:
        by_day[entry.day_of_week].append(entry)
    visible_days = [i for i in range(7) if i < 6 or by_day[i]]  # Sunday only when used
    started_today = sessions_today_by_entry([e.id for e in by_day[today_idx]], tz)
    return render_template("timetable.html", day_names=DAY_NAMES, visible_days=visible_days, by_day=by_day,
                           today_idx=today_idx, started_today=started_today, courses=courses,
                           teachers=teachers, course_filter=course_filter, mine=mine, form=form,
                           total=len(entries))


@main_bp.post("/timetable/<int:entry_id>/delete")
@login_required
def delete_timetable_entry(entry_id):
    if not current_user.is_admin:
        return ("Forbidden: only administrators can edit the timetable", 403)
    entry = db.get_or_404(TimetableEntry, entry_id)
    entry.active = False  # soft delete keeps links from past class sessions intact
    log_action("timetable_entry_removed", "timetable_entry", entry.id, {"subject": entry.subject})
    db.session.commit()
    flash("Timetable slot removed.", "success")
    return redirect(url_for("main.timetable"))


@main_bp.post("/timetable/<int:entry_id>/start-session")
@login_required
def start_timetable_session(entry_id):
    entry = db.get_or_404(TimetableEntry, entry_id)
    tz = local_tz()
    if not entry.active or entry.day_of_week != datetime.now(tz).weekday():
        flash("Only today's timetable slots can be started.", "danger")
        return redirect(url_for("main.timetable"))
    existing = sessions_today_by_entry([entry.id], tz).get(entry.id)
    if existing:
        flash("A session for this slot was already started today.", "warning")
        return redirect(url_for("main.take_attendance") if existing.is_open else url_for("main.sessions"))
    today_label = datetime.now(tz).strftime("%d %b %Y")
    session = ClassSession(title=f"{entry.subject} - {today_label}", course=entry.course,
                           created_by_id=current_user.id, timetable_entry_id=entry.id)
    db.session.add(session)
    db.session.flush()
    log_action("class_session_started_from_timetable", "class_session", session.id,
               {"timetable_entry_id": entry.id, "subject": entry.subject})
    db.session.commit()
    flash("Session started from the timetable. You can take attendance now.", "success")
    return redirect(url_for("main.take_attendance"))


@main_bp.get("/take-attendance")
@login_required
def take_attendance():
    open_sessions = db.session.scalars(db.select(ClassSession).where(ClassSession.is_open.is_(True)).order_by(ClassSession.starts_at.desc())).all()
    students = db.session.scalars(db.select(Student).where(Student.active.is_(True)).order_by(Student.name.asc())).all()
    return render_template("take_attendance.html", sessions=open_sessions, students=students)


@main_bp.post("/api/recognize")
@login_required
def recognize_and_mark():
    payload = request.get_json(silent=True) or {}
    try:
        session_id = int(payload.get("session_id", 0))
        image_bytes = FaceEngine.decode_data_url(payload.get("image", ""))
        embedding = face_engine().embedding_from_bytes(image_bytes)
    except (ValueError, TypeError):
        return jsonify(ok=False, message="Select a valid class session."), 400
    except FaceEngineError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    except Exception as exc:
        current_app.logger.exception("Face recognition initialization failed")
        return jsonify(ok=False, message="Face recognition is unavailable. Verify model files are installed."), 503

    session = db.session.get(ClassSession, session_id)
    if not session or not session.is_open:
        return jsonify(ok=False, message="This class session is not open."), 400
    candidates = db.session.scalars(db.select(Student).where(Student.active.is_(True), Student.face_embedding.is_not(None))).all()
    if not candidates:
        return jsonify(ok=False, message="No active students have enrolled face data."), 404
    engine = face_engine()
    best_student, best_score = None, -1.0
    for student in candidates:
        try:
            score = engine.similarity(embedding, student.face_embedding)
        except Exception:
            continue
        if score > best_score:
            best_student, best_score = student, score
    threshold = current_app.config["FACE_MATCH_THRESHOLD"]
    if best_student is None or best_score < threshold:
        log_action("face_match_unrecognized", "class_session", session.id, {"best_score": round(best_score, 4)})
        db.session.commit()
        return jsonify(ok=False, message="No confident match. Ask the teacher to verify manually.", score=round(best_score, 3)), 404

    existing = db.session.scalar(db.select(Attendance.id).where(
        Attendance.student_id == best_student.id, Attendance.session_id == session.id))
    if existing:
        return jsonify(ok=True, duplicate=True, message=f"{best_student.name} is already marked present.",
                       student=best_student.name, score=round(best_score, 3))
    record = Attendance(student_id=best_student.id, session_id=session.id, status="present",
                        method="face_recognition", confidence=best_score, marked_by_id=current_user.id)
    db.session.add(record)
    log_action("attendance_marked_by_face", "attendance", details={
        "student_id": best_student.id, "session_id": session.id, "score": round(best_score, 4)})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=True, duplicate=True, message="Attendance was already recorded for this session."), 200
    return jsonify(ok=True, duplicate=False, message=f"Attendance marked for {best_student.name}.",
                   student=best_student.name, score=round(best_score, 3)), 200


@main_bp.post("/attendance/manual")
@login_required
def manual_attendance():
    session_id = request.form.get("session_id", type=int)
    student_id = request.form.get("student_id", type=int)
    reason = request.form.get("reason", "").strip()
    session = db.session.get(ClassSession, session_id) if session_id else None
    student = db.session.get(Student, student_id) if student_id else None
    if not session or not session.is_open:
        flash("Choose an open class session.", "danger")
    elif not student or not student.active:
        flash("Choose an active student.", "danger")
    elif len(reason) < 8:
        flash("Enter a short verification reason (at least 8 characters).", "danger")
    else:
        existing = db.session.scalar(db.select(Attendance.id).where(
            Attendance.student_id == student.id, Attendance.session_id == session.id))
        if existing:
            flash("An attendance record already exists for this student and session.", "warning")
        else:
            record = Attendance(student_id=student.id, session_id=session.id, status="present",
                                method="manual_verified", confidence=None, marked_by_id=current_user.id)
            db.session.add(record)
            db.session.flush()
            log_action("attendance_marked_manually", "attendance", record.id, {
                "student_id": student.id, "session_id": session.id, "reason": reason[:500]})
            try:
                db.session.commit()
                flash(f"Manual attendance recorded for {student.name}.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("An attendance record already exists for this student and session.", "warning")
    return redirect(url_for("main.take_attendance"))


@main_bp.get("/reports")
@login_required
def reports():
    session_id = request.args.get("session_id", type=int)
    stmt = db.select(Attendance).join(Student).join(ClassSession).order_by(Attendance.marked_at.desc())
    if session_id:
        stmt = stmt.where(Attendance.session_id == session_id)
    records = db.session.scalars(stmt.limit(1000)).all()
    all_sessions = db.session.scalars(db.select(ClassSession).order_by(ClassSession.starts_at.desc())).all()
    # Student-level attendance percentage is based on all sessions created, including closed sessions.
    total_sessions = db.session.scalar(db.select(func.count(ClassSession.id))) or 0
    summary = []
    students = db.session.scalars(db.select(Student).where(Student.active.is_(True)).order_by(Student.name)).all()
    for student in students:
        present = db.session.scalar(db.select(func.count(Attendance.id)).where(
            Attendance.student_id == student.id, Attendance.status == "present")) or 0
        summary.append({"student": student, "present": present,
                        "total": total_sessions,
                        "percentage": round((present / total_sessions) * 100, 1) if total_sessions else 0})
    return render_template("reports.html", records=records, sessions=all_sessions,
                           selected_session_id=session_id, summary=summary, total_sessions=total_sessions)


@main_bp.get("/reports/export.csv")
@login_required
def export_csv():
    session_id = request.args.get("session_id", type=int)
    stmt = db.select(Attendance).join(Student).join(ClassSession).order_by(Attendance.marked_at.desc())
    if session_id:
        stmt = stmt.where(Attendance.session_id == session_id)
    records = db.session.scalars(stmt.limit(10000)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Student Name", "Course", "Session", "Status", "Marked At (UTC)", "Method", "Match Score"])
    for row in records:
        writer.writerow([row.student.student_code, row.student.name, row.session.course, row.session.title,
                         row.status, row.marked_at.isoformat(), row.method,
                         f"{row.confidence:.4f}" if row.confidence is not None else ""])
    log_action("attendance_csv_exported", "attendance", details={"session_id": session_id, "row_count": len(records)})
    db.session.commit()
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})


@main_bp.get("/audit")
@login_required
def audit():
    if not current_user.is_admin:
        return ("Forbidden: administrators only", 403)
    logs = db.session.scalars(db.select(AuditLog).order_by(AuditLog.created_at.desc()).limit(300)).all()
    return render_template("audit.html", logs=logs)


@main_bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok", database="ok")
    except Exception:
        return jsonify(status="degraded", database="unavailable"), 503
