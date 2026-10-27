from flask import request
from flask_login import current_user
from extensions import db
from models import AuditLog

def log_action(action, entity_type=None, entity_id=None, details=None):
    actor_id = current_user.id if getattr(current_user, "is_authenticated", False) else None
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    ip = forwarded or request.remote_addr
    # Never log passwords, raw face images, or face embeddings.
    db.session.add(AuditLog(
        actor_user_id=actor_id, action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {}, ip_address=ip[:64] if ip else None,
    ))
