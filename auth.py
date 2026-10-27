from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from extensions import db
from models import User
from audit import log_action

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email))
        if user and user.active and user.check_password(password):
            login_user(user, remember=False, fresh=True)
            log_action("login_success", "user", user.id)
            db.session.commit()
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        log_action("login_failed", "user", details={"email_provided": bool(email)})
        db.session.commit()
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@auth_bp.post("/logout")
@login_required
def logout():
    log_action("logout", "user", current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
