ANNOTATOR_ID = 'annotator_id'
TELEMETRY_URL = 'https://telemetry.anish.io/api/v1/submit'
TELEMETRY_DELTA = 20 * 60 # seconds
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

# Setting
# keys
SETTING_CLOSED = 'closed' # boolean
SETTING_TELEMETRY_LAST_SENT = 'telemetry_sent_time' # integer
# values
SETTING_TRUE = 'true'
SETTING_FALSE = 'false'

# Defaults
# these can be overridden via the config file
DEFAULT_WELCOME_MESSAGE = '''
Welcome to the HackPSU Applicant Review System.

**Please read this important message carefully before continuing.**

This system uses pairwise comparison to help rank hackathon applicants. You'll
start by reviewing a single applicant, then for each subsequent applicant,
you'll decide if they are a stronger or weaker candidate than the one you
reviewed **immediately beforehand**.

When comparing applicants, consider factors such as:
- Their project idea and creativity
- Coding experience and technical background
- Expectations and what they hope to gain
- Overall enthusiasm and fit for HackPSU

If you have a **conflict of interest** with an applicant (you know them
personally, they attend your school, etc.), click **Skip** to be assigned
a new applicant.

Please review each application thoroughly before voting. **Once you make a
decision, you cannot change it**.
'''.strip()

DEFAULT_EMAIL_SUBJECT = 'HackPSU Applicant Review - Your Access Link'

DEFAULT_EMAIL_BODY = '''
Hi {name},

You've been invited to help review HackPSU applicants. This email contains your
personal access link to the review system.

DO NOT SHARE this email with others, as it contains your personal access link.

To access the system, visit {link}.

Once you're in, please take the time to read the welcome message and
instructions before continuing. Your reviews help us select the best candidates
for HackPSU!

Thank you for volunteering your time.
'''.strip()

DEFAULT_CLOSED_MESSAGE = '''
The applicant review system is currently closed. Reload the page to try again.
'''.strip()

DEFAULT_DISABLED_MESSAGE = '''
Your reviewer account is currently disabled. Please contact an admin if you
believe this is an error.
'''.strip()

DEFAULT_LOGGED_OUT_MESSAGE = '''
You are not currently logged in.

To access the applicant review system, please log in through the HackPSU
authentication system. If you were given a magic link, you can use that instead.
'''.strip()

DEFAULT_WAIT_MESSAGE = '''
There are no more applicants available for review at this time.

Please wait a moment and reload the page to try again. If you've reviewed all
the applicants already, then you're done. Thank you for your help!
'''.strip()
