from gavel.models import db
import gavel.crowd_bt as crowd_bt
from sqlalchemy.orm.exc import NoResultFound

view_table = db.Table('applicant_view',
    db.Column('applicant_id', db.Integer, db.ForeignKey('applicant.id')),
    db.Column('annotator_id', db.Integer, db.ForeignKey('annotator.id'))
)


class Applicant(db.Model):
    """Represents a HackPSU applicant (user with registration)."""
    id = db.Column(db.Integer, primary_key=True, nullable=False)

    # HackPSU User fields
    hackpsu_user_id = db.Column(db.String(64), unique=True, nullable=False)
    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    email = db.Column(db.String(255), nullable=False)
    university = db.Column(db.String(255))
    major = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    country = db.Column(db.String(100))
    gender = db.Column(db.String(50))
    shirt_size = db.Column(db.String(10))
    dietary_restriction = db.Column(db.Text)
    allergies = db.Column(db.Text)
    race = db.Column(db.String(100))
    resume = db.Column(db.Text)  # URL to resume
    linkedin_url = db.Column(db.Text)

    # Registration data
    hackathon_id = db.Column(db.String(64), db.ForeignKey('hackathon.id'))
    hackathon = db.relationship('Hackathon', backref='applicants')
    travel_reimbursement = db.Column(db.Boolean, default=False)
    driving = db.Column(db.Boolean, default=False)
    first_hackathon = db.Column(db.Boolean)
    academic_year = db.Column(db.String(50))
    educational_institution_type = db.Column(db.String(100))
    coding_experience = db.Column(db.Text)
    age = db.Column(db.Integer)
    referral = db.Column(db.Text)
    project = db.Column(db.Text)  # Project idea/description
    expectations = db.Column(db.Text)
    excitement = db.Column(db.Text)  # What excites them about hackathon
    zip_code = db.Column(db.String(20))
    travel_cost = db.Column(db.Float)
    travel_method = db.Column(db.String(100))
    travel_additional = db.Column(db.Text)
    veteran = db.Column(db.String(50))
    registration_time = db.Column(db.Integer)  # Unix timestamp from API

    # Ranking fields (preserved from Item model for Bayesian algorithm)
    active = db.Column(db.Boolean, default=True, nullable=False)
    viewed = db.relationship('Annotator', secondary=view_table)
    prioritized = db.Column(db.Boolean, default=False, nullable=False)
    mu = db.Column(db.Float)
    sigma_sq = db.Column(db.Float)

    def __init__(self, hackpsu_user_id, email, first_name=None, last_name=None, **kwargs):
        self.hackpsu_user_id = hackpsu_user_id
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.mu = crowd_bt.MU_PRIOR
        self.sigma_sq = crowd_bt.SIGMA_SQ_PRIOR
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @property
    def full_name(self):
        """Return full name or email if name not available."""
        name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return name if name else self.email.split('@')[0]

    @property
    def name(self):
        """Alias for full_name for compatibility."""
        return self.full_name

    @property
    def location(self):
        """Return university as location for compatibility."""
        return self.university or ''

    @property
    def description(self):
        """Return project idea as description for compatibility."""
        return self.project or ''

    @classmethod
    def by_id(cls, uid):
        """Get applicant by internal ID."""
        if uid is None:
            return None
        try:
            applicant = cls.query.get(uid)
        except NoResultFound:
            applicant = None
        return applicant

    @classmethod
    def by_hackpsu_id(cls, hackpsu_user_id):
        """Get applicant by HackPSU user ID."""
        if hackpsu_user_id is None:
            return None
        try:
            return cls.query.filter(cls.hackpsu_user_id == hackpsu_user_id).first()
        except NoResultFound:
            return None

    def update_from_api(self, user_data, registration_data=None):
        """Update applicant fields from HackPSU API response."""
        # User fields
        self.first_name = user_data.get('firstName', self.first_name)
        self.last_name = user_data.get('lastName', self.last_name)
        self.email = user_data.get('email', self.email)
        self.university = user_data.get('university', self.university)
        self.major = user_data.get('major', self.major)
        self.phone = user_data.get('phone', self.phone)
        self.country = user_data.get('country', self.country)
        self.gender = user_data.get('gender', self.gender)
        self.shirt_size = user_data.get('shirtSize', self.shirt_size)
        self.dietary_restriction = user_data.get('dietaryRestriction', self.dietary_restriction)
        self.allergies = user_data.get('allergies', self.allergies)
        self.race = user_data.get('race', self.race)
        self.resume = user_data.get('resume', self.resume)
        self.linkedin_url = user_data.get('linkedinUrl', self.linkedin_url)

        if registration_data:
            self.travel_reimbursement = registration_data.get('travelReimbursement', self.travel_reimbursement)
            self.driving = registration_data.get('driving', self.driving)
            self.first_hackathon = registration_data.get('firstHackathon', self.first_hackathon)
            self.academic_year = registration_data.get('academicYear', self.academic_year)
            self.educational_institution_type = registration_data.get('educationalInstitutionType', self.educational_institution_type)
            self.coding_experience = registration_data.get('codingExperience', self.coding_experience)
            
            # Sanitize age
            age_raw = registration_data.get('age')
            if age_raw is False or age_raw is True:
                 self.age = None
            else:
                 try:
                     self.age = int(age_raw) if age_raw is not None else self.age
                 except (ValueError, TypeError):
                     self.age = None

            self.referral = registration_data.get('referral', self.referral)
            self.project = registration_data.get('project', self.project)
            self.expectations = registration_data.get('expectations', self.expectations)
            self.excitement = registration_data.get('excitement', self.excitement)
            
            # Metadata fields - try both snake_case (current API) and camelCase (potential legacy/future)
            self.zip_code = registration_data.get('zip_code') or registration_data.get('zipCode', self.zip_code)
            self.travel_cost = registration_data.get('travel_cost') or registration_data.get('travelCost', self.travel_cost)
            self.travel_method = registration_data.get('travel_method') or registration_data.get('travelMethod', self.travel_method)
            self.travel_additional = registration_data.get('travel_additional') or registration_data.get('travelAdditional', self.travel_additional)
            
            self.veteran = registration_data.get('veteran', self.veteran)
            
            # Sanitize registration_time (handle milliseconds vs seconds)
            reg_time = registration_data.get('time')
            if reg_time:
                try:
                    reg_time_int = int(reg_time)
                    # If timestamp is in milliseconds (greater than max 32-bit int ~2e9), convert to seconds
                    if reg_time_int > 2147483647:
                        reg_time_int = int(reg_time_int / 1000)
                    self.registration_time = reg_time_int
                except (ValueError, TypeError):
                    pass
