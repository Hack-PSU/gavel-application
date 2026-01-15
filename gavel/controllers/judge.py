from gavel import app
from gavel.models import *
from gavel.constants import *
import gavel.settings as settings
import gavel.utils as utils
import gavel.crowd_bt as crowd_bt
from gavel.firebase_auth import (
    verify_hackpsu_session,
    sync_annotator_from_auth_server,
    hackpsu_auth_required,
)
from flask import (
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from numpy.random import choice, random, shuffle
from functools import wraps
from datetime import datetime


def requires_open(redirect_to):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if Setting.value_of(SETTING_CLOSED) == SETTING_TRUE:
                return redirect(url_for(redirect_to))
            else:
                return f(*args, **kwargs)
        return decorated
    return decorator


def requires_active_annotator(redirect_to):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            annotator = get_current_annotator()
            if annotator is None or not annotator.active:
                return redirect(url_for(redirect_to))
            else:
                return f(*args, **kwargs)
        return decorated
    return decorator


@app.route('/')
def index():
    # Check Firebase session first (new auth method)
    firebase_user = verify_hackpsu_session()
    if firebase_user:
        annotator = sync_annotator_from_auth_server(firebase_user)
        if annotator:
            session[ANNOTATOR_ID] = annotator.id

    annotator = get_current_annotator()
    if annotator is None:
        return render_template(
            'logged_out.html',
            content=utils.render_markdown(settings.LOGGED_OUT_MESSAGE)
        )
    else:
        if Setting.value_of(SETTING_CLOSED) == SETTING_TRUE:
            return render_template(
                'closed.html',
                content=utils.render_markdown(settings.CLOSED_MESSAGE)
            )
        if not annotator.active:
            return render_template(
                'disabled.html',
                content=utils.render_markdown(settings.DISABLED_MESSAGE)
            )
        if not annotator.read_welcome:
            return redirect(url_for('welcome'))
        maybe_init_annotator()
        if annotator.next is None:
            return render_template(
                'wait.html',
                content=utils.render_markdown(settings.WAIT_MESSAGE)
            )
        elif annotator.prev is None:
            # Pass as both 'item' and 'applicant' for template compatibility
            return render_template('begin.html', item=annotator.next, applicant=annotator.next)
        else:
            # Pass as both 'prev/next' and with 'applicant' suffix for compatibility
            return render_template(
                'vote.html',
                prev=annotator.prev,
                next=annotator.next,
                prev_applicant=annotator.prev,
                next_applicant=annotator.next
            )


@app.route('/vote', methods=['POST'])
@requires_open(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def vote():
    def tx():
        annotator = get_current_annotator()
        if annotator.prev.id == int(request.form['prev_id']) and annotator.next.id == int(request.form['next_id']):
            if request.form['action'] == 'Skip':
                annotator.ignore.append(annotator.next)
            else:
                # ignore things that were deactivated in the middle of judging
                if annotator.prev.active and annotator.next.active:
                    if request.form['action'] == 'Previous':
                        perform_vote(annotator, next_won=False)
                        decision = Decision(annotator, winner=annotator.prev, loser=annotator.next)
                    elif request.form['action'] == 'Current':
                        perform_vote(annotator, next_won=True)
                        decision = Decision(annotator, winner=annotator.next, loser=annotator.prev)
                    db.session.add(decision)
                annotator.next.viewed.append(annotator)  # counted as viewed even if deactivated
                annotator.prev = annotator.next
                annotator.ignore.append(annotator.prev)
            annotator.update_next(choose_next(annotator))
            db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))


@app.route('/begin', methods=['POST'])
@requires_open(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def begin():
    def tx():
        annotator = get_current_annotator()
        # Accept both 'item_id' and 'applicant_id' for backwards compatibility
        applicant_id = request.form.get('applicant_id') or request.form.get('item_id')
        if annotator.next.id == int(applicant_id):
            annotator.ignore.append(annotator.next)
            if request.form['action'] == 'Continue':
                annotator.next.viewed.append(annotator)
                annotator.prev = annotator.next
                annotator.update_next(choose_next(annotator))
            elif request.form['action'] == 'Skip':
                annotator.next = None  # will be reset in index
            db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop(ANNOTATOR_ID, None)
    return redirect(url_for('index'))


@app.route('/login/<secret>/')
def login(secret):
    """Magic link login (kept for backwards compatibility)."""
    annotator = Annotator.by_secret(secret)
    if annotator is None:
        session.pop(ANNOTATOR_ID, None)
        session.modified = True
    else:
        session[ANNOTATOR_ID] = annotator.id
    return redirect(url_for('index'))


@app.route('/welcome/')
@requires_open(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def welcome():
    return render_template(
        'welcome.html',
        content=utils.render_markdown(settings.WELCOME_MESSAGE)
    )


@app.route('/welcome/done', methods=['POST'])
@requires_open(redirect_to='index')
@requires_active_annotator(redirect_to='index')
def welcome_done():
    def tx():
        annotator = get_current_annotator()
        if request.form['action'] == 'Continue':
            annotator.read_welcome = True
        db.session.commit()
    with_retries(tx)
    return redirect(url_for('index'))


def get_current_annotator():
    return Annotator.by_id(session.get(ANNOTATOR_ID, None))


def preferred_applicants(annotator):
    '''
    Return a list of preferred applicants for the given annotator to review next.

    This method uses a variety of strategies to try to select good candidate
    applicants for pairwise comparison.
    '''
    applicants = []
    ignored_ids = {a.id for a in annotator.ignore}

    if ignored_ids:
        available_applicants = Applicant.query.filter(
            (Applicant.active == True) & (~Applicant.id.in_(ignored_ids))
        ).all()
    else:
        available_applicants = Applicant.query.filter(Applicant.active == True).all()

    prioritized_applicants = [a for a in available_applicants if a.prioritized]

    applicants = prioritized_applicants if prioritized_applicants else available_applicants

    # Check for busy applicants (recently assigned to other judges)
    annotators = Annotator.query.filter(
        (Annotator.active == True) & (Annotator.next != None) & (Annotator.updated != None)
    ).all()
    busy = {a.next.id for a in annotators if
            (datetime.utcnow() - a.updated).total_seconds() < settings.TIMEOUT * 60}
    nonbusy = [a for a in applicants if a.id not in busy]
    preferred = nonbusy if nonbusy else applicants

    # Prefer applicants with fewer views
    less_seen = [a for a in preferred if len(a.viewed) < settings.MIN_VIEWS]

    return less_seen if less_seen else preferred


# Alias for backwards compatibility
preferred_items = preferred_applicants


def maybe_init_annotator():
    def tx():
        annotator = get_current_annotator()
        if annotator.next is None:
            applicants = preferred_applicants(annotator)
            if applicants:
                annotator.update_next(choice(applicants))
                db.session.commit()
    with_retries(tx)


def choose_next(annotator):
    applicants = preferred_applicants(annotator)

    shuffle(applicants)  # useful for argmax case as well in the case of ties
    if applicants:
        if random() < crowd_bt.EPSILON:
            return applicants[0]
        else:
            return crowd_bt.argmax(lambda a: crowd_bt.expected_information_gain(
                annotator.alpha,
                annotator.beta,
                annotator.prev.mu,
                annotator.prev.sigma_sq,
                a.mu,
                a.sigma_sq), applicants)
    else:
        return None


def perform_vote(annotator, next_won):
    if next_won:
        winner = annotator.next
        loser = annotator.prev
    else:
        winner = annotator.prev
        loser = annotator.next
    u_alpha, u_beta, u_winner_mu, u_winner_sigma_sq, u_loser_mu, u_loser_sigma_sq = crowd_bt.update(
        annotator.alpha,
        annotator.beta,
        winner.mu,
        winner.sigma_sq,
        loser.mu,
        loser.sigma_sq
    )
    annotator.alpha = u_alpha
    annotator.beta = u_beta
    winner.mu = u_winner_mu
    winner.sigma_sq = u_winner_sigma_sq
    loser.mu = u_loser_mu
    loser.sigma_sq = u_loser_sigma_sq
