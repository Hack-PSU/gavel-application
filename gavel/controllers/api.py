from gavel import app
from gavel.models import *
import gavel.utils as utils
from gavel.firebase_auth import hackpsu_admin_required
from flask import Response


@app.route('/api/applicants.csv')
@app.route('/api/items.csv')
@app.route('/api/projects.csv')
@hackpsu_admin_required
def applicant_dump():
    """Export ranked applicants as CSV."""
    applicants = Applicant.query.order_by(desc(Applicant.mu)).all()
    data = [[
        'Rank',
        'Mu',
        'Sigma Squared',
        'Name',
        'Email',
        'University',
        'Major',
        'Academic Year',
        'Coding Experience',
        'First Hackathon',
        'Project Idea',
        'Active'
    ]]
    data += [[
        str(idx + 1),
        str(a.mu),
        str(a.sigma_sq),
        a.full_name,
        a.email,
        a.university or '',
        a.major or '',
        a.academic_year or '',
        a.coding_experience or '',
        'Yes' if a.first_hackathon else 'No',
        a.project or '',
        'Yes' if a.active else 'No'
    ] for idx, a in enumerate(applicants)]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')


@app.route('/api/applicants-full.csv')
@hackpsu_admin_required
def applicant_full_dump():
    """Export full applicant details as CSV."""
    applicants = Applicant.query.order_by(desc(Applicant.mu)).all()
    data = [[
        'Rank',
        'Mu',
        'Sigma Squared',
        'HackPSU User ID',
        'First Name',
        'Last Name',
        'Email',
        'University',
        'Major',
        'Phone',
        'Country',
        'Gender',
        'Age',
        'Academic Year',
        'Institution Type',
        'Coding Experience',
        'First Hackathon',
        'Project Idea',
        'Expectations',
        'Excitement',
        'Resume URL',
        'LinkedIn',
        'Travel Reimbursement',
        'Driving',
        'Travel Method',
        'Travel Cost',
        'Active'
    ]]
    data += [[
        str(idx + 1),
        str(a.mu),
        str(a.sigma_sq),
        a.hackpsu_user_id,
        a.first_name or '',
        a.last_name or '',
        a.email,
        a.university or '',
        a.major or '',
        a.phone or '',
        a.country or '',
        a.gender or '',
        str(a.age) if a.age else '',
        a.academic_year or '',
        a.educational_institution_type or '',
        a.coding_experience or '',
        'Yes' if a.first_hackathon else 'No',
        a.project or '',
        a.expectations or '',
        a.excitement or '',
        a.resume or '',
        a.linkedin_url or '',
        'Yes' if a.travel_reimbursement else 'No',
        'Yes' if a.driving else 'No',
        a.travel_method or '',
        str(a.travel_cost) if a.travel_cost else '',
        'Yes' if a.active else 'No'
    ] for idx, a in enumerate(applicants)]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')


@app.route('/api/annotators.csv')
@app.route('/api/judges.csv')
@hackpsu_admin_required
def annotator_dump():
    """Export judges/annotators as CSV."""
    annotators = Annotator.query.all()
    data = [['Name', 'Email', 'Description', 'Active', 'Privilege Level']]
    data += [[
        str(a.name),
        a.email,
        a.description,
        'Yes' if a.active else 'No',
        str(a.privilege_level)
    ] for a in annotators]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')


@app.route('/api/decisions.csv')
@hackpsu_admin_required
def decisions_dump():
    """Export all pairwise comparison decisions as CSV."""
    decisions = Decision.query.all()
    data = [['Annotator ID', 'Annotator Name', 'Winner ID', 'Winner Name', 'Loser ID', 'Loser Name', 'Time']]
    data += [[
        str(d.annotator.id),
        d.annotator.name,
        str(d.winner.id),
        d.winner.full_name,
        str(d.loser.id),
        d.loser.full_name,
        str(d.time)
    ] for d in decisions]
    return Response(utils.data_to_csv_string(data), mimetype='text/csv')
