from datetime import datetime, timezone
from extensions import db
from models import User, Student, ClassSession, Attendance


def make_user(app, email="teacher@example.com", role="teacher"):
    with app.app_context():
        user = User(name="Test User", email=email, role=role)
        user.set_password("CorrectHorseBattery12!")
        db.session.add(user)
        db.session.commit()


def login(client, email="teacher@example.com"):
    return client.post("/login", data={"email": email, "password": "CorrectHorseBattery12!"}, follow_redirects=True)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_login_and_dashboard(client, app):
    make_user(app)
    response = login(client)
    assert response.status_code == 200
    assert b"Dashboard overview" in response.data


def test_bad_login_is_rejected(client, app):
    make_user(app)
    response = client.post("/login", data={"email": "teacher@example.com", "password": "wrong"})
    assert b"Invalid email or password" in response.data


def test_student_and_session_can_be_created_in_database(app):
    with app.app_context():
        user = User(name="Teacher", email="t@example.com", role="teacher")
        user.set_password("CorrectHorseBattery12!")
        db.session.add(user)
        db.session.flush()
        student = Student(student_code="S001", name="Example Student", course="CSE-AIML", face_embedding=[0.1, 0.2])
        session = ClassSession(title="AI Lecture 1", course="Artificial Intelligence", created_by_id=user.id)
        db.session.add_all([student, session])
        db.session.commit()
        assert db.session.get(Student, student.id).student_code == "S001"
        assert db.session.get(ClassSession, session.id).is_open is True


def test_attendance_duplicate_constraint(app):
    with app.app_context():
        user = User(name="Teacher", email="dup@example.com", role="teacher")
        user.set_password("CorrectHorseBattery12!")
        db.session.add(user)
        db.session.flush()
        student = Student(student_code="S002", name="Another Student", course="CSE")
        session = ClassSession(title="Test", course="CSE", created_by_id=user.id)
        db.session.add_all([student, session])
        db.session.flush()
        db.session.add(Attendance(student_id=student.id, session_id=session.id, marked_by_id=user.id))
        db.session.commit()
        db.session.add(Attendance(student_id=student.id, session_id=session.id, marked_by_id=user.id))
        from sqlalchemy.exc import IntegrityError
        try:
            db.session.commit()
            assert False, "Expected uniqueness constraint to reject duplicate attendance"
        except IntegrityError:
            db.session.rollback()


# ---------------------------------------------------------------- timetable
from datetime import time as dtime
from models import TimetableEntry


def slot(**overrides):
    data = {"subject": "Maths", "course": "CSE-A", "day_of_week": 0, "start_time": "09:00",
            "end_time": "10:00", "room": "101", "teacher_id": ""}
    data.update(overrides)
    return data


def test_admin_can_add_slot_and_teacher_cannot(client, app):
    make_user(app, "admin@example.com", "admin")
    make_user(app, "teacher@example.com", "teacher")
    login(client, "admin@example.com")
    assert client.post("/timetable", data=slot(), follow_redirects=True).status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(TimetableEntry.id))) == 1
    client.post("/logout")
    login(client, "teacher@example.com")
    assert client.post("/timetable", data=slot(subject="Physics", room="202", course="CSE-B")).status_code == 403
    assert client.get("/timetable").status_code == 200


def test_timetable_rejects_clashes_and_bad_times(client, app):
    make_user(app, "admin@example.com", "admin")
    login(client, "admin@example.com")
    client.post("/timetable", data=slot())
    # same room, overlapping time -> rejected
    client.post("/timetable", data=slot(subject="Chem", course="CSE-B", start_time="09:30", end_time="10:30"))
    # end before start -> rejected
    client.post("/timetable", data=slot(subject="Bio", course="CSE-C", room="9", start_time="11:00", end_time="10:00"))
    # back-to-back in the same room is fine
    client.post("/timetable", data=slot(subject="Art", course="CSE-D", start_time="10:00", end_time="11:00"))
    with app.app_context():
        subjects = sorted(e.subject for e in db.session.scalars(db.select(TimetableEntry)))
        assert subjects == ["Art", "Maths"]


def test_start_session_from_today_slot_only_once(client, app):
    from datetime import datetime
    from main import local_tz
    make_user(app, "admin@example.com", "admin")
    login(client, "admin@example.com")
    with app.app_context():
        today = datetime.now(local_tz()).weekday()
        entry = TimetableEntry(subject="Maths", course="CSE-A", day_of_week=today,
                               start_time=dtime(0, 0), end_time=dtime(23, 59))
        other_day = TimetableEntry(subject="Later", course="CSE-A", day_of_week=(today + 1) % 7,
                                   start_time=dtime(8, 0), end_time=dtime(9, 0))
        db.session.add_all([entry, other_day])
        db.session.commit()
        entry_id, other_id = entry.id, other_day.id
    assert client.get("/").status_code == 200  # dashboard renders today's panel
    client.post(f"/timetable/{entry_id}/start-session")
    client.post(f"/timetable/{entry_id}/start-session")  # duplicate is ignored
    client.post(f"/timetable/{other_id}/start-session")  # not today -> refused
    with app.app_context():
        sessions = db.session.scalars(db.select(ClassSession)).all()
        assert len(sessions) == 1 and sessions[0].timetable_entry_id == entry_id


def test_removed_slot_is_hidden(client, app):
    make_user(app, "admin@example.com", "admin")
    login(client, "admin@example.com")
    client.post("/timetable", data=slot())
    with app.app_context():
        entry_id = db.session.scalar(db.select(TimetableEntry.id))
    client.post(f"/timetable/{entry_id}/delete")
    assert b"Maths" not in client.get("/timetable").data
