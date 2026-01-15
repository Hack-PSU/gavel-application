from gavel.models import db
import gavel.utils as utils
import gavel.crowd_bt as crowd_bt
from sqlalchemy.orm.exc import NoResultFound
from datetime import datetime

ignore_table = db.Table('ignore',
    db.Column('annotator_id', db.Integer, db.ForeignKey('annotator.id')),
    db.Column('applicant_id', db.Integer, db.ForeignKey('applicant.id'))
)


class Annotator(db.Model):
    """Represents a judge/reviewer in the ranking system."""
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    read_welcome = db.Column(db.Boolean, default=False, nullable=False)
    description = db.Column(db.Text, nullable=False, default='')

    # Firebase authentication fields
    firebase_uid = db.Column(db.String(128), unique=True, nullable=True)
    privilege_level = db.Column(db.Integer, default=2)  # 2=judge, 4=admin

    # Magic link secret (kept for backwards compatibility, nullable now)
    secret = db.Column(db.String(32), unique=True, nullable=True)

    # Current and previous applicant assignments (changed from Item)
    next_id = db.Column(db.Integer, db.ForeignKey('applicant.id'))
    next = db.relationship('Applicant', foreign_keys=[next_id], uselist=False)
    updated = db.Column(db.DateTime)
    prev_id = db.Column(db.Integer, db.ForeignKey('applicant.id'))
    prev = db.relationship('Applicant', foreign_keys=[prev_id], uselist=False)

    # Applicants this annotator has skipped (changed from Item)
    ignore = db.relationship('Applicant', secondary=ignore_table)

    # Bayesian parameters for judge reliability
    alpha = db.Column(db.Float)
    beta = db.Column(db.Float)

    def __init__(self, name, email, description=''):
        self.name = name
        self.email = email
        self.description = description
        self.alpha = crowd_bt.ALPHA_PRIOR
        self.beta = crowd_bt.BETA_PRIOR
        # Generate secret for backwards compatibility (magic links)
        self.secret = utils.gen_secret(32)

    def update_next(self, new_next):
        """Update the next applicant assignment."""
        if new_next is not None:
            new_next.prioritized = False  # Cancel prioritization once assigned
            self.updated = datetime.utcnow()
        self.next = new_next

    @classmethod
    def by_secret(cls, secret):
        """Find annotator by magic link secret."""
        if secret is None:
            return None
        try:
            annotator = cls.query.filter(cls.secret == secret).one()
        except NoResultFound:
            annotator = None
        return annotator

    @classmethod
    def by_id(cls, uid):
        """Find annotator by ID."""
        if uid is None:
            return None
        try:
            annotator = cls.query.get(uid)
        except NoResultFound:
            annotator = None
        return annotator

    @classmethod
    def by_email(cls, email):
        """Find annotator by email."""
        if email is None:
            return None
        try:
            return cls.query.filter(cls.email == email).first()
        except NoResultFound:
            return None

    @classmethod
    def by_firebase_uid(cls, firebase_uid):
        """Find annotator by Firebase UID."""
        if firebase_uid is None:
            return None
        try:
            return cls.query.filter(cls.firebase_uid == firebase_uid).first()
        except NoResultFound:
            return None
