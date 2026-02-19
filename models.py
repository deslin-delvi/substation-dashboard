from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='supervisor')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Violation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    violation_type = db.Column(db.String(100))
    missing_items = db.Column(db.String(200))
    image_path = db.Column(db.String(300))
    gate_action = db.Column(db.String(20))
    operator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    notes = db.Column(db.Text)             # System-generated notes
    supervisor_notes = db.Column(db.Text)  # User-editable supervisor notes

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'violation_type': self.violation_type,
            'missing_items': self.missing_items,
            'gate_action': self.gate_action,
            'notes': self.notes,
            'supervisor_notes': self.supervisor_notes,
        }

# ─────────────────────────────────────────────────────────────
# NEW: RTSP / CCTV camera registry
# ─────────────────────────────────────────────────────────────
class RTSPCamera(db.Model):
    """
    Stores RTSP camera configurations.
    Each row represents one CCTV / IP camera.
    """
    __tablename__ = 'rtsp_camera'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)   # e.g. "Gate A Cam"
    url         = db.Column(db.String(500), nullable=False)   # rtsp://user:pass@ip/stream
    location    = db.Column(db.String(200), default='')       # optional description
    enabled     = db.Column(db.Boolean, default=True)
    added_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':       self.id,
            'name':     self.name,
            'url':      self.url,
            'location': self.location,
            'enabled':  self.enabled,
            'added_at': self.added_at.strftime('%Y-%m-%d %H:%M'),
        }