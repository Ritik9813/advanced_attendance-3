
import os

import click
from flask import Flask, jsonify
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from extensions import db, login_manager, csrf
from models import User
from auth import auth_bp
from main import main_bp


def create_app(test_config=None):
    app = Flask(
        __name__,
        template_folder="app/templates",
        static_folder="app/static",
        static_url_path="/static",
    )

    # Load application configuration
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # Make the CSRF token generator available to templates
    @app.context_processor
    def inject_globals():
        from flask_wtf.csrf import generate_csrf

        return {"csrf_token": generate_csrf}

    # Handle requests exceeding the upload limit
    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(
            ok=False,
            message=(
                "Upload is too large. Maximum request size "
                "is configured in the environment."
            ),
        ), 413

    # Initialize tables and migrate the timetable column
    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and safely add the timetable link column."""

        try:
            db.create_all()

            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())

            if "class_session" not in tables:
                raise click.ClickException(
                    "The class_session table was not created. "
                    "Check that its SQLAlchemy model is imported "
                    "and registered in db.metadata."
                )

            columns = {
                column["name"]
                for column in inspector.get_columns("class_session")
            }

            if "timetable_entry_id" not in columns:

                # Add a foreign key only when its target table exists.
                if "timetable_entry" in tables:
                    db.session.execute(
                        text(
                            """
                            ALTER TABLE class_session
                            ADD COLUMN timetable_entry_id INTEGER
                            REFERENCES timetable_entry (id)
                            """
                        )
                    )
                    click.echo(
                        "Added timetable_entry_id with a foreign key."
                    )
                else:
                    # This fixes the missing-column error without
                    # creating a reference to a nonexistent table.
                    db.session.execute(
                        text(
                            """
                            ALTER TABLE class_session
                            ADD COLUMN timetable_entry_id INTEGER
                            """
                        )
                    )
                    click.echo(
                        "Added timetable_entry_id without a foreign key "
                        "because timetable_entry does not exist."
                    )

                db.session.commit()

            else:
                click.echo(
                    "timetable_entry_id already exists."
                )

            # Bootstrap an administrator if configured
            email = (
                app.config.get("BOOTSTRAP_ADMIN_EMAIL", "")
                .strip()
                .lower()
            )
            password = app.config.get(
                "BOOTSTRAP_ADMIN_PASSWORD", ""
            )

            existing_admin = None

            if email:
                existing_admin = db.session.scalar(
                    db.select(User.id).where(User.email == email)
                )

            if email and password and not existing_admin:
                admin = User(
                    name="System Administrator",
                    email=email,
                    role="admin",
                )
                admin.set_password(password)

                db.session.add(admin)
                db.session.commit()

                click.echo(
                    f"Created bootstrap admin: {email}"
                )
            else:
                click.echo(
                    "Database initialization complete. "
                    "Admin unchanged (already exists or "
                    "bootstrap values not set)."
                )

        except click.ClickException:
            db.session.rollback()
            raise

        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException(
                f"Database initialization failed: {error}"
            ) from error

    # Create an administrator or teacher account
    @app.cli.command("create-user")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option(
        "--role",
        type=click.Choice(["admin", "teacher"]),
        default="teacher",
        prompt=True,
    )
    @click.password_option()
    def create_user(name, email, role, password):
        email = email.strip().lower()

        if len(password) < 12:
            raise click.ClickException(
                "Use a password of at least 12 characters."
            )

        try:
            existing_user = db.session.scalar(
                db.select(User.id).where(User.email == email)
            )

            if existing_user:
                raise click.ClickException(
                    "That email already exists."
                )

            user = User(
                name=name.strip(),
                email=email,
                role=role,
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            click.echo(f"Created {role} user: {email}")

        except click.ClickException:
            db.session.rollback()
            raise

        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException(
                f"Could not create user: {error}"
            ) from error

    # Verify the database connection
    @app.cli.command("check-db")
    def check_db():
        try:
            db.session.execute(text("SELECT 1"))
            click.echo("Database connection OK")
        except SQLAlchemyError as error:
            db.session.rollback()
            raise click.ClickException(
                f"Database connection failed: {error}"
            ) from error

    return app


app = create_app()


if __name__ == "__main__":
    debug_mode = (
        os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )

    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5001")),
        debug=debug_mode,
    )
