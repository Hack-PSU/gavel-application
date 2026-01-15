from gavel.models import db
from datetime import datetime
from sqlalchemy.orm.exc import NoResultFound


class Hackathon(db.Model):
    """Represents a HackPSU hackathon event."""
    id = db.Column(db.String(64), primary_key=True)  # HackPSU API ID
    name = db.Column(db.String(255), nullable=False)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    last_synced = db.Column(db.DateTime)

    def __init__(self, id, name, start_time=None, end_time=None, is_active=False):
        self.id = id
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.is_active = is_active

    @classmethod
    def get_active(cls):
        """Get the currently active hackathon."""
        try:
            return cls.query.filter(cls.is_active == True).first()
        except NoResultFound:
            return None

    @classmethod
    def by_id(cls, hackathon_id):
        """Get hackathon by ID."""
        if hackathon_id is None:
            return None
        try:
            return cls.query.get(hackathon_id)
        except NoResultFound:
            return None

    def mark_synced(self):
        """Update the last_synced timestamp."""
        self.last_synced = datetime.utcnow()
