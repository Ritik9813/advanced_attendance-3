from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="teacher")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    course = db.Column(db.String(120), nullable=False, default="General")
    active = db.Column(db.Boolean, nullable=False, default=True)
    # One normalized SFace embedding stored as JSON. Restrict access: this is biometric data.
    face_embedding = db.Column(db.JSON, nullable=True)
    consent_recorded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

class TimetableEntry(db.Model):
    """A recurring weekly class slot (e.g. Mondays 09:00-10:00, Room 101)."""
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(160), nullable=False)
    course = db.Column(db.String(120), nullable=False, index=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0 = Monday ... 6 = Sunday
    start_time = db.Column(db.Time, nullable=False)  # local wall-clock time (see TIMEZONE in config)
    end_time = db.Column(db.Time, nullable=False)
    room = db.Column(db.String(60), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    teacher = db.relationship("User", backref="timetable_entries")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

class ClassSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_by = db.relationship("User", backref="class_sessions")
    # Set when the session was started from the timetable (nullable: sessions can still be ad hoc).
    timetable_entry_id = db.Column(db.Integer, db.ForeignKey("timetable_entry.id"), nullable=True)
    timetable_entry = db.relationship("TimetableEntry", backref="class_sessions")

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("class_session.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="present")
    marked_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    method = db.Column(db.String(30), nullable=False, default="face_recognition")
    confidence = db.Column(db.Float, nullable=True)
    marked_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    student = db.relationship("Student", backref="attendance_records")
    session = db.relationship("ClassSession", backref="attendance_records")
    __table_args__ = (db.UniqueConstraint("student_id", "session_id", name="uq_attendance_student_session"),)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(80), nullable=True)
    entity_id = db.Column(db.String(80), nullable=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    actor = db.relationship("User", backref="audit_logs")

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
