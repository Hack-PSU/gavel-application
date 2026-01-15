from gavel import app
from gavel.models import *
from gavel.constants import *
import gavel.settings as settings
import gavel.utils as utils
import gavel.stats as stats
from gavel.firebase_auth import hackpsu_admin_required, get_session_token, get_id_token_for_api
from gavel.hackpsu_api import sync_hackathon, sync_applicants
from flask import (
    redirect,
    render_template,
    request,
    url_for,
    flash,
)
import urllib.parse
import xlrd

ALLOWED_EXTENSIONS = set(['csv', 'xlsx', 'xls'])


@app.route('/admin/')
@hackpsu_admin_required
def admin():
    stats.check_send_telemetry()
    annotators = Annotator.query.order_by(Annotator.id).all()
    applicants = Applicant.query.order_by(desc(Applicant.mu)).all()
    hackathon = Hackathon.get_active()
    decisions = Decision.query.all()

    # Count votes per annotator and applicant
    counts = {}
    applicant_counts = {}
    for d in decisions:
        a = d.annotator_id
        w = d.winner_id
        l = d.loser_id
        counts[a] = counts.get(a, 0) + 1
        applicant_counts[w] = applicant_counts.get(w, 0) + 1
        applicant_counts[l] = applicant_counts.get(l, 0) + 1

    # Calculate viewed and skipped counts
    viewed = {a.id: {ann.id for ann in a.viewed} for a in applicants}
    skipped = {}
    for ann in annotators:
        for a in ann.ignore:
            if a.id in viewed and ann.id not in viewed[a.id]:
                skipped[a.id] = skipped.get(a.id, 0) + 1

    # Settings
    setting_closed = Setting.value_of(SETTING_CLOSED) == SETTING_TRUE

    return render_template(
        'admin.html',
        annotators=annotators,
        counts=counts,
        applicant_counts=applicant_counts,
        item_counts=applicant_counts,  # Backwards compatibility
        skipped=skipped,
        applicants=applicants,
        items=applicants,  # Backwards compatibility
        hackathon=hackathon,
        votes=len(decisions),
        setting_closed=setting_closed,
    )


@app.route('/admin/sync', methods=['POST'])
@hackpsu_admin_required
def sync():
    """Handle HackPSU API sync actions."""
    action = request.form.get('action')

    # Get API token - prefers HACKPSU_SERVICE_TOKEN, falls back to session token
    session_token = get_session_token()
    auth_token = get_id_token_for_api(session_token)
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Admin Sync Action: {action}")
    logger.info(f"Status: auth_token={'Present' if auth_token else 'None'}, HACKPSU_API_KEY={'Present' if settings.HACKPSU_API_KEY else 'None'}")
    if settings.HACKPSU_API_KEY:
        logger.info(f"API Key First 4 chars: {settings.HACKPSU_API_KEY[:4]}")

    # Check validity: Need either an auth token OR a configured API Key
    if not auth_token and not settings.HACKPSU_API_KEY:
        return utils.server_error(
            'No API token or API Key available. Please set HACKPSU_API_KEY or HACKPSU_SERVICE_TOKEN.'
        )

    if action == 'sync_hackathon':
        hackathon = sync_hackathon(auth_token)
        if hackathon:
            return redirect(url_for('admin'))
        return utils.server_error('Failed to sync hackathon from HackPSU API. Check the server logs for details.')

    elif action == 'sync_applicants':
        hackathon = Hackathon.get_active()
        if not hackathon:
            return utils.user_error('No active hackathon. Please sync hackathon first.')
        synced, errors = sync_applicants(hackathon.id, auth_token)
        if errors > 0:
            return utils.server_error(f'Sync completed with errors. Synced: {synced}, Errors: {errors}')
        return redirect(url_for('admin'))

    return redirect(url_for('admin'))


@app.route('/admin/applicant', methods=['POST'])
@hackpsu_admin_required
def applicant_action():
    """Handle applicant management actions."""
    action = request.form['action']
    applicant_id = request.form.get('applicant_id') or request.form.get('item_id')

    if action == 'Prioritize' or action == 'Cancel':
        target_state = action == 'Prioritize'
        def tx():
            Applicant.by_id(applicant_id).prioritized = target_state
            db.session.commit()
        with_retries(tx)

    elif action == 'Disable' or action == 'Enable':
        target_state = action == 'Enable'
        def tx():
            Applicant.by_id(applicant_id).active = target_state
            db.session.commit()
        with_retries(tx)

    elif action == 'Delete':
        try:
            def tx():
                db.session.execute(ignore_table.delete(ignore_table.c.applicant_id == applicant_id))
                Applicant.query.filter_by(id=applicant_id).delete()
                db.session.commit()
            with_retries(tx)
        except IntegrityError as e:
            if isinstance(e.orig, psycopg2.errors.ForeignKeyViolation):
                return utils.server_error("Applicants can't be deleted once they have been voted on by a judge. You can use the 'disable' functionality instead.")
            else:
                return utils.server_error(str(e))

    return redirect(url_for('admin'))


# Keep /admin/item route for backwards compatibility
@app.route('/admin/item', methods=['POST'])
@hackpsu_admin_required
def item():
    """Backwards compatible route - redirects to applicant_action."""
    return applicant_action()


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_upload_form():
    f = request.files.get('file')
    data = []
    if f and allowed_file(f.filename):
        extension = str(f.filename.rsplit('.', 1)[1].lower())
        if extension == "xlsx" or extension == "xls":
            workbook = xlrd.open_workbook(file_contents=f.read())
            worksheet = workbook.sheet_by_index(0)
            data = list(utils.cast_row(worksheet.row_values(rx, 0, 3)) for rx in range(worksheet.nrows) if worksheet.row_len(rx) == 3)
        elif extension == "csv":
            data = utils.data_from_csv_string(f.read().decode("utf-8"))
    else:
        csv = request.form['data']
        data = utils.data_from_csv_string(csv)
    return data


@app.route('/admin/annotator', methods=['POST'])
@hackpsu_admin_required
def annotator():
    action = request.form['action']
    if action == 'Submit':
        data = parse_upload_form()
        added = []
        if data:
            # validate data
            for index, row in enumerate(data):
                if len(row) != 3:
                    return utils.user_error('Bad data: row %d has %d elements (expecting 3)' % (index + 1, len(row)))
            def tx():
                for row in data:
                    ann = Annotator(*row)
                    added.append(ann)
                    db.session.add(ann)
                db.session.commit()
            with_retries(tx)
            try:
                email_invite_links(added)
            except Exception as e:
                return utils.server_error(str(e))
    elif action == 'Email':
        annotator_id = request.form['annotator_id']
        try:
            email_invite_links(Annotator.by_id(annotator_id))
        except Exception as e:
            return utils.server_error(str(e))
    elif action == 'Disable' or action == 'Enable':
        annotator_id = request.form['annotator_id']
        target_state = action == 'Enable'
        def tx():
            Annotator.by_id(annotator_id).active = target_state
            db.session.commit()
        with_retries(tx)
    elif action == 'Delete':
        annotator_id = request.form['annotator_id']
        try:
            def tx():
                db.session.execute(ignore_table.delete(ignore_table.c.annotator_id == annotator_id))
                Annotator.query.filter_by(id=annotator_id).delete()
                db.session.commit()
            with_retries(tx)
        except IntegrityError as e:
            if isinstance(e.orig, psycopg2.errors.ForeignKeyViolation):
                return utils.server_error("Judges can't be deleted once they have voted on an applicant. You can use the 'disable' functionality instead.")
            else:
                return utils.server_error(str(e))
    return redirect(url_for('admin'))


@app.route('/admin/setting', methods=['POST'])
@hackpsu_admin_required
def setting():
    key = request.form['key']
    if key == 'closed':
        action = request.form['action']
        new_value = SETTING_TRUE if action == 'Close' else SETTING_FALSE
        Setting.set(SETTING_CLOSED, new_value)
        db.session.commit()
    return redirect(url_for('admin'))


@app.route('/admin/applicant/<applicant_id>/')
@hackpsu_admin_required
def applicant_detail(applicant_id):
    applicant = Applicant.by_id(applicant_id)
    if not applicant:
        return utils.user_error('Applicant %s not found' % applicant_id)
    else:
        assigned = Annotator.query.filter(Annotator.next == applicant).all()
        viewed_ids = {a.id for a in applicant.viewed}
        if viewed_ids:
            skipped = Annotator.query.filter(
                Annotator.ignore.contains(applicant) & ~Annotator.id.in_(viewed_ids)
            )
        else:
            skipped = Annotator.query.filter(Annotator.ignore.contains(applicant))
        return render_template(
            'admin_applicant.html',
            applicant=applicant,
            item=applicant,  # Backwards compatibility
            assigned=assigned,
            skipped=skipped
        )


# Keep /admin/item/<item_id>/ route for backwards compatibility
@app.route('/admin/item/<item_id>/')
@hackpsu_admin_required
def item_detail(item_id):
    """Backwards compatible route - redirects to applicant_detail."""
    return applicant_detail(item_id)


@app.route('/admin/annotator/<annotator_id>/')
@hackpsu_admin_required
def annotator_detail(annotator_id):
    ann = Annotator.by_id(annotator_id)
    if not ann:
        return utils.user_error('Annotator %s not found' % annotator_id)
    else:
        seen = Applicant.query.filter(Applicant.viewed.contains(ann)).all()
        ignored_ids = {a.id for a in ann.ignore}
        if ignored_ids:
            skipped = Applicant.query.filter(
                Applicant.id.in_(ignored_ids) & ~Applicant.viewed.contains(ann)
            )
        else:
            skipped = []
        return render_template(
            'admin_annotator.html',
            annotator=ann,
            login_link=annotator_link(ann),
            seen=seen,
            skipped=skipped
        )


def annotator_link(ann):
    if ann.secret:
        return url_for('login', secret=ann.secret, _external=True)
    return None


def email_invite_links(annotators):
    if settings.DISABLE_EMAIL or annotators is None:
        return
    if not isinstance(annotators, list):
        annotators = [annotators]

    emails = []
    for ann in annotators:
        link = annotator_link(ann)
        if link:
            raw_body = settings.EMAIL_BODY.format(name=ann.name, link=link)
            body = '\n\n'.join(utils.get_paragraphs(raw_body))
            emails.append((ann.email, settings.EMAIL_SUBJECT, body))

    if settings.USE_SENDGRID and settings.SENDGRID_API_KEY != None:
        utils.send_sendgrid_emails(emails)
    else:
        utils.send_emails.delay(emails)
