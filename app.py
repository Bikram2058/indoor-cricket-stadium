from dbm import sqlite3
from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            return redirect('/admin-login')
        return f(*args, **kwargs)
    return decorated_function

from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, render_template, request, redirect, session

from flask_wtf.csrf import CSRFProtect

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import os

import stripe

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

csrf = CSRFProtect(app)

limiter = Limiter(app=app, key_func=get_remote_address)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
   # Audit logging: record security events in security.log
import logging
audit_logger = logging.getLogger('audit')
audit_logger.setLevel(logging.INFO)
audit_handler = logging.FileHandler('security.log')
audit_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
audit_logger.addHandler(audit_handler)

def audit(event, detail=''):
       audit_logger.info(f"{event} | IP={request.remote_addr} | {detail}")

# Booking ticket: random code + confirmation email
import smtplib
import secrets
from email.message import EmailMessage

def generate_booking_code():
    # e.g. ICC-7F3A-9B21-C4D0 (random, cannot be guessed)
    parts = [secrets.token_hex(2).upper() for _ in range(3)]
    return "ICC-" + "-".join(parts)

def send_booking_email(to_email, booking, code):
    msg = EmailMessage()
    msg['Subject'] = f"Booking Confirmed - {code} - Indoor Cricket Centre"
    msg['From'] = os.getenv("MAIL_USERNAME")
    msg['To'] = to_email
    msg.set_content(f"""Hi {booking['full_name']},

Your booking is confirmed! Show this code at the stadium gate:

    BOOKING CODE: {code}

    Lane:      {booking['lane']}
    Date:      {booking['booking_date']}
    Time:      {booking['booking_time']}
    Duration:  {booking['duration']}
    Players:   {booking['players']}
    Paid:      ${booking['amount'] / 100:.2f} AUD

This code can only be used once at the gate.
If you did not make this booking, please contact us immediately.

Indoor Cricket Centre
""")
    try:
            with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD"))
                smtp.send_message(msg)
            return True
    except Exception as e:
            audit("EMAIL_FAILED", f"to={to_email} error={type(e).__name__}")
            return False

def send_login_email(to_email):
    from email.mime.text import MIMEText
    from datetime import datetime

    msg = MIMEText(
        f"Hello,\n\n"
        f"A login to your Indoor Cricket Centre account was just detected.\n\n"
        f"Time: {datetime.now().strftime('%d %b %Y, %I:%M %p')}\n\n"
        f"If this was you, no action is needed.\n"
        f"If you did not log in, please change your password immediately.\n\n"
        f"Indoor Cricket Centre"
    )
    msg['Subject'] = 'New login to your account'
    msg['From'] = os.getenv("MAIL_USERNAME")
    msg['To'] = to_email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD"))
            smtp.send_message(msg)
        return True
    except Exception as e:
        audit("LOGIN_EMAIL_FAILED", f"to={to_email} error={type(e).__name__}")
        return False

def send_reset_email(to_email, reset_link):
    from email.mime.text import MIMEText
    msg = MIMEText(
        "Hello,\n\n"
        "We received a request to reset your Indoor Cricket Centre password.\n\n"
        "Click the link below to set a new password (valid for 1 hour):\n"
        f"{reset_link}\n\n"
        "If you did not request this, you can safely ignore this email.\n\n"
        "Indoor Cricket Centre"
    )
    msg['Subject'] = 'Reset your password'
    msg['From'] = os.getenv("MAIL_USERNAME")
    msg['To'] = to_email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD"))
            smtp.send_message(msg)
        return True
    except Exception as e:
        audit("RESET_EMAIL_FAILED", f"to={to_email} error={type(e).__name__}")
        return False


# Session security settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Brute force protection: lock an account after too many failed logins
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_TIME = timedelta(minutes=15)
failed_logins = {}

def is_locked_out(key):
    record = failed_logins.get(key)
    return bool(record and record['locked_until'] and datetime.now() < record['locked_until'])

def record_failed_login(key):
    record = failed_logins.setdefault(key, {'count': 0, 'locked_until': None})
    record['count'] += 1
    if record['count'] >= MAX_FAILED_ATTEMPTS:
        record['locked_until'] = datetime.now() + LOCKOUT_TIME
        record['count'] = 0

def reset_failed_logins(key):
    failed_logins.pop(key, None)

@app.errorhandler(429)
def too_many_requests(e):
    audit("RATE_LIMITED", f"path={request.path}")
    wait_msg = "Too many attempts. Please wait a minute and try again."
    if request.path == '/admin-login':
        return render_template('admin_login.html', rate_limited=True), 429
    if request.path == '/register':
        return render_template('register.html', error=wait_msg, rate_limited=True), 429
    if request.path == '/change-password':
        return render_template('change_password.html', error=wait_msg), 429
    return render_template('login.html', rate_limited=True), 429

# Security headers: tell the browser to block common attacks
@app.after_request
def add_security_headers(response):
       # Stop other websites showing our site in a hidden frame (clickjacking)
       response.headers['X-Frame-Options'] = 'DENY'
       # Stop the browser guessing file types (MIME sniffing)
       response.headers['X-Content-Type-Options'] = 'nosniff'
       # Don't leak full page URLs to other websites
       response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
       # Block camera, microphone and location access
       response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
       # Only load scripts, styles and images from trusted places
       response.headers['Content-Security-Policy'] = (
           "default-src 'self'; "
           "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://js.stripe.com; "
           "style-src 'self' 'unsafe-inline' https:; "
           "font-src 'self' https: data:; "
           "img-src 'self' https: data:; "
           "frame-ancestors 'none'; "
           "form-action 'self' https://checkout.stripe.com"
       )
       return response



@app.route('/')
def home():
    return render_template('index.html')

# ============================================================
# BOOKING SYSTEM (slot grid)
# Change these settings to suit the centre.
# ============================================================
LANES = ['Lane 1', 'Lane 2', 'Lane 3', 'Lane 4']
OPEN_HOUR = 9          # first slot starts 9:00 am
CLOSE_HOUR = 22        # everything must finish by 10:00 pm
SLOT_MINUTES = 30      # start times every 30 minutes
MAX_PLAYERS = 8
BOOK_AHEAD_DAYS = 365

# Duration label (saved in the database) -> (minutes, price in cents)
DURATIONS = {
    '30 Minutes - $25': (30, 2500),
    '1 Hour - $40': (60, 4000),
    '2 Hours - $75': (120, 7500),
}

# Discount (%) for members with an active membership. 0 = no discount.
MEMBER_DISCOUNT_PERCENT = {
    'Bronze': 0,
    'Silver': 0,
    'Gold': 0,
}


def get_active_membership(email):
    """Return the user's active membership plan name, or None."""
    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT plan FROM memberships
        WHERE user_email = ?
          AND status = 'Active'
          AND start_date <= ?
          AND end_date >= ?
        ORDER BY end_date DESC
        LIMIT 1
    """, (email, datetime.now().date().isoformat(),
          datetime.now().date().isoformat()))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def booking_price(duration, plan):
    """Price in cents for a duration, after any member discount."""
    base = DURATIONS[duration][1]
    discount = MEMBER_DISCOUNT_PERCENT.get(plan, 0) if plan else 0
    return round(base * (100 - discount) / 100)


def slot_start_times():
    """All possible start times in a day, e.g. ['09:00', '09:30', ...]."""
    times = []
    t = datetime(2000, 1, 1, OPEN_HOUR, 0)
    end = datetime(2000, 1, 1, CLOSE_HOUR, 0)
    while t < end:
        times.append(t.strftime('%H:%M'))
        t += timedelta(minutes=SLOT_MINUTES)
    return times


def get_booked_ranges(booking_date):
    """Return {lane: [(start, end), ...]} for every booking on a date."""
    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lane, booking_time, duration
        FROM bookings
        WHERE booking_date = ?
    """, (booking_date,))
    rows = cursor.fetchall()
    conn.close()

    booked = {lane: [] for lane in LANES}
    for lane, time_text, duration in rows:
        try:
            start = datetime.strptime(f"{booking_date} {time_text}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        minutes = DURATIONS.get(duration, (60, 0))[0]
        booked.setdefault(lane, []).append((start, start + timedelta(minutes=minutes)))
    return booked


def slot_status(booking_date, time_text, minutes, lane_ranges, now):
    """'free', 'booked', 'past' or 'closed' for one lane + start time."""
    start = datetime.strptime(f"{booking_date} {time_text}", "%Y-%m-%d %H:%M")
    end = start + timedelta(minutes=minutes)

    if start <= now:
        return 'past'
    if end > start.replace(hour=CLOSE_HOUR, minute=0):
        return 'closed'
    for booked_start, booked_end in lane_ranges:
        if start < booked_end and end > booked_start:
            return 'booked'
    return 'free'


def parse_booking_date(text):
    """Return a date if it is valid and inside the booking window, else None."""
    try:
        chosen = datetime.strptime(text or '', '%Y-%m-%d').date()
    except ValueError:
        return None
    today = datetime.now().date()
    if chosen < today or chosen > today + timedelta(days=BOOK_AHEAD_DAYS):
        return None
    return chosen


@app.route('/slots')
def slots():
    """Availability grid for one date + duration (used by booking.html)."""
    if 'user' not in session:
        return {'error': 'Please log in.'}, 401

    booking_date = request.args.get('date', '')
    duration = request.args.get('duration', '')

    if not parse_booking_date(booking_date):
        return {'error': 'Please choose a valid date.'}, 400
    if duration not in DURATIONS:
        return {'error': 'Please choose a duration.'}, 400

    minutes = DURATIONS[duration][0]
    booked = get_booked_ranges(booking_date)
    now = datetime.now()

    grid = {}
    for time_text in slot_start_times():
        grid[time_text] = {
            lane: slot_status(booking_date, time_text, minutes, booked[lane], now)
            for lane in LANES
        }

    plan = get_active_membership(session['user'])

    return {
        'lanes': LANES,
        'times': slot_start_times(),
        'grid': grid,
        'price_cents': booking_price(duration, plan),
        'minutes': minutes,
    }


@app.route('/booking', methods=['GET', 'POST'])
def booking():
    if 'user' not in session:
        return redirect('/login')

    import sqlite3

    email = session['user']
    plan = get_active_membership(email)

    # Pre-fill name and phone from the user's profile
    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, phone FROM users WHERE email = ?", (email,))
    profile = cursor.fetchone() or ('', '')
    conn.close()

    def show_form(error=None):
        return render_template(
            'booking.html',
            error=error,
            form=request.form if request.method == 'POST' else {},
            profile_name=profile[0] or '',
            profile_phone=profile[1] or '',
            member_plan=plan,
            durations=[
                {'label': label, 'minutes': mins,
                 'price': booking_price(label, plan) / 100,
                 'base_price': cents / 100}
                for label, (mins, cents) in DURATIONS.items()
            ],
            max_players=MAX_PLAYERS,
            book_ahead_days=BOOK_AHEAD_DAYS,
        )

    if request.method == 'POST':

        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        booking_date = request.form.get('booking_date', '')
        booking_time = request.form.get('booking_time', '')
        lane = request.form.get('lane', '')
        duration = request.form.get('duration', '')

        # Validate every field on the server (never trust the browser)
        if not full_name or len(full_name) > 100:
            return show_form("Please enter your full name.")

        if not phone.isascii() or not phone.isdigit() or not 8 <= len(phone) <= 15:
            return show_form("Please enter a valid phone number.")

        if not parse_booking_date(booking_date):
            return show_form("Please choose a valid date.")

        if duration not in DURATIONS:
            return show_form("Please choose a duration.")

        if lane not in LANES:
            return show_form("Please choose a lane.")

        if booking_time not in slot_start_times():
            return show_form("Please choose a time slot from the grid.")

        try:
            players = int(request.form.get('players', ''))
        except ValueError:
            return show_form("Please enter the number of players.")

        if players < 1 or players > MAX_PLAYERS:
            return show_form(f"A maximum of {MAX_PLAYERS} players is allowed per lane.")

        # Check the slot is still free right now
        minutes = DURATIONS[duration][0]
        status = slot_status(
            booking_date, booking_time, minutes,
            get_booked_ranges(booking_date)[lane], datetime.now()
        )

        if status != 'free':
            messages = {
                'booked': "Sorry, that slot has just been taken. Please pick another time.",
                'past': "That time has already passed. Please pick a later time.",
                'closed': "That booking would finish after closing time. Please pick an earlier time or a shorter duration.",
            }
            return show_form(messages[status])

        # Same keys as before, so Stripe checkout works unchanged
        session['pending_booking'] = {
            'full_name': full_name,
            'phone': phone,
            'email': email,
            'booking_date': booking_date,
            'booking_time': booking_time,
            'lane': lane,
            'duration': duration,
            'member': 'Yes' if plan else 'No',
            'players': players,
            'amount': booking_price(duration, plan)
        }

        return redirect('/create-checkout-session')

    return show_form()

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def login():

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        lockout_key = 'user:' + email.strip().lower()

        if is_locked_out(lockout_key):
            audit("LOGIN_BLOCKED_LOCKED", f"user={email}")
            return render_template('login.html', locked=True)

        import sqlite3

        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user[3], password):
            reset_failed_logins(lockout_key)
            session['user'] = email
            session.permanent = True
            audit("LOGIN_SUCCESS", f"user={email}")
            send_login_email(email)

            # Return to Shop if the user originally clicked Shop
            if request.form.get('next') == 'shop':
                return redirect('/shop')

            return redirect('/')
        
        else:
            audit("LOGIN_FAILED", f"user={email}")
            record_failed_login(lockout_key)
            return render_template('login.html', error=True)

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def register():

       if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Password strength check
                # Password strength check
        import re
        if (len(password) < 8
                or not re.search(r'[A-Z]', password)
                or not re.search(r'[a-z]', password)
                or not re.search(r'[0-9]', password)
                or not re.search(r'[^A-Za-z0-9]', password)):
            return render_template(
                'register.html',
                error="Password must be 8+ characters with uppercase, lowercase, number, and special character."
            )

        # Email validation
        if '@' not in email or '.' not in email:
            return render_template(
                'register.html',
                error="Please enter a valid email address."
            )

        # Password confirmation
        if password != confirm_password:
            return render_template(
                'register.html',
                error="Passwords do not match."
            )

        # Hash password
        hashed_password = generate_password_hash(password)

        import sqlite3
        conn = sqlite3.connect('indoor_cricket.db', timeout=10)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO users (full_name, email, password)
                VALUES (?, ?, ?)
            """, (full_name, email, hashed_password))
            conn.commit()
            conn.close()

            return render_template(
                'register.html',
                success=True
            )

        except sqlite3.IntegrityError:
            conn.close()
            return render_template(
                'register.html',
                error="Email already registered."
            )

       return render_template('register.html')
@app.route('/create-checkout-session', methods=['GET'])
def create_checkout_session():

    booking = session.get('pending_booking')

    if not booking:
        return redirect('/booking')
       
    # Build product name, show membership discount if the price was reduced
    product_name = f"Indoor Cricket Booking - {booking['duration']}"
    if 'user' in session:
        import sqlite3 as member_db
        member_conn = member_db.connect('indoor_cricket.db')
        member_row = member_conn.execute(
            "SELECT plan FROM memberships WHERE user_email = ? "
            "AND status = 'Active' AND end_date >= date('now') "
            "ORDER BY id DESC LIMIT 1",
            (session['user'],)
        ).fetchone()
        member_conn.close()
        if member_row:
            product_name = f"Indoor Cricket Booking - {booking['duration']}  —  {member_row[0]} Member 20% OFF"
    checkout_session = stripe.checkout.Session.create(

        line_items=[
            {
                'price_data': {
                    'currency': 'aud',
                    'product_data': {
                                    'name': product_name
                    },
                    'unit_amount': booking['amount']
                },
                'quantity': 1
            }
        ],

        mode='payment',

        success_url='http://127.0.0.1:5000/payment-success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url='http://127.0.0.1:5000/payment-cancel'
    )

    session['checkout_session_id'] = checkout_session.id

    return redirect(checkout_session.url)

@app.route('/payment-success')
def payment_success():

    booking = session.get('pending_booking')
    session_id = request.args.get('session_id')

    # Verify that this payment belongs to the current booking
    stored_session_id = session.get('checkout_session_id')

    if not booking or not session_id or not stored_session_id:
        return redirect('/booking')

    if session_id != stored_session_id:
        return "Invalid payment session.", 403

    # Check that booking details and Stripe session exist
    if not booking or not session_id:
        return redirect('/booking')

    try:
        # Retrieve payment information directly from Stripe
        checkout_session = stripe.checkout.Session.retrieve(
            session_id
        )

        # Verify payment and amount
        if (
            checkout_session.payment_status != 'paid'
            or checkout_session.amount_total != booking['amount']
            or checkout_session.currency != 'aud'
        ):
            return "Payment verification failed.", 403

    except stripe.StripeError:
        return "Unable to verify payment. Please contact support.", 400

    # Save verified booking
    import sqlite3

    conn = sqlite3.connect(
        'indoor_cricket.db',
        timeout=10
    )

    cursor = conn.cursor()
    booking_code = generate_booking_code()

    cursor.execute("""
        INSERT INTO bookings
        (full_name, phone, email, booking_date,
        booking_time, lane, duration, member, players, booking_code, stripe_session_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        booking['full_name'],
        booking['phone'],
        booking['email'],
        booking['booking_date'],
        booking['booking_time'],
        booking['lane'],
        booking['duration'],
        booking['member'],
        booking['players'],
        booking_code,
        session_id
    ))

    conn.commit()
    conn.close()

    audit("BOOKING_CONFIRMED", f"code={booking_code} user={booking['email']}")
    email_sent = send_booking_email(booking['email'], booking, booking_code)

    session.pop('pending_booking', None)

    session.pop('checkout_session_id', None)

    return render_template('payment_success.html', booking_code=booking_code, email_sent=email_sent)

@app.route('/payment-cancel')
def payment_cancel():
    session.pop('pending_booking', None)
    session.pop('checkout_session_id', None)

    return render_template('payment_cancel.html')

@app.route('/membership')
def membership():
    if 'user' not in session:
        return redirect('/login')
    
    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT plan, end_date, status FROM memberships "
        "WHERE user_email = ? ORDER BY id DESC LIMIT 1",
        (session['user'],)
    )
    membership = cursor.fetchone()
    conn.close()
    return render_template('membership.html', membership=membership)
# Membership plans - prices set on the server (cents), never trusted from the browser
MEMBERSHIP_PLANS = {
    'Bronze': 2500,
    'Silver': 4000,
    'Gold': 5500
}

@app.route('/create-membership-checkout', methods=['POST'])
def create_membership_checkout():

    if 'user' not in session:
        return redirect('/login')

    plan = request.form.get('plan')

    if plan not in MEMBERSHIP_PLANS:
        return "Invalid membership plan", 400

    amount = MEMBERSHIP_PLANS[plan]

    checkout_session = stripe.checkout.Session.create(
        line_items=[{
            'price_data': {
                'currency': 'aud',
                'product_data': {'name': f"{plan} Membership - 1 Month"},
                'unit_amount': amount
            },
            'quantity': 1
        }],
        mode='payment',
        success_url='http://127.0.0.1:5000/membership-payment-success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url='http://127.0.0.1:5000/membership',
        client_reference_id=session['user']
    )

    session['pending_membership'] = {
        'plan': plan,
        'stripe_session_id': checkout_session.id
    }

    return redirect(checkout_session.url, code=303)


@app.route('/membership-payment-success')
def membership_payment_success():

    if 'user' not in session:
        return redirect('/login')

    stripe_session_id = request.args.get('session_id')
    pending = session.get('pending_membership')

    if not stripe_session_id or not pending:
        return redirect('/membership')

    if pending['stripe_session_id'] != stripe_session_id:
        return "Invalid payment session.", 403

    try:
        payment = stripe.checkout.Session.retrieve(stripe_session_id)
    except stripe.StripeError:
        return "Unable to verify payment.", 400

    plan = pending['plan']
    expected_amount = MEMBERSHIP_PLANS.get(plan)

    # Verify the payment with Stripe before saving anything
    if (
        payment.payment_status != 'paid'
        or payment.client_reference_id != session['user']
        or payment.amount_total != expected_amount
        or payment.currency != 'aud'
    ):
        return "Payment verification failed.", 403

    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db', timeout=10)
    cursor = conn.cursor()

    # Stop the same payment creating two memberships
    cursor.execute(
        "SELECT id FROM memberships WHERE stripe_session_id = ?",
        (stripe_session_id,)
    )

    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=30)

    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO memberships
            (user_email, plan, price, start_date, end_date, status, stripe_session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session['user'],
            plan,
            expected_amount / 100,
            start_date.isoformat(),
            end_date.isoformat(),
            'Active',
            stripe_session_id
        ))
        conn.commit()
        audit("MEMBERSHIP_PURCHASED", f"user={session['user']} plan={plan}")

    conn.close()
    session.pop('pending_membership', None)

    return render_template(
        'membership_payment_success.html',
        plan=plan,
        price=expected_amount / 100,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        subject = request.form.get('subject', '')
        message = request.form['message']

        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contact_messages (name, email, subject, message, submitted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, email, subject, message, datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()
        audit("CONTACT_MESSAGE", f"from={email}")
        return render_template('contact.html', success=True)

    return render_template('contact.html')

@app.route('/shop')
def shop():

    if 'user' not in session:
        return redirect('/login?next=shop')
    
    return render_template('shop.html')

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():

    # Only registered users can add products
    if 'user' not in session:
        return redirect('/login')

    product_id = request.form.get('product_id', type=int)

    if product_id is None:
        return "Invalid product", 400

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    # Check whether the product exists
    cursor.execute(
        "SELECT id, stock FROM products WHERE id = ?",
        (product_id,)
    )

    product = cursor.fetchone()
    conn.close()

    if not product:
        return "Product not found", 404

    if product[1] <= 0:
        return "Product is out of stock", 400

    # Retrieve the existing shopping cart
    cart = session.get('cart', {})

    product_key = str(product_id)
    current_quantity = cart.get(product_key, 0)

    if current_quantity >= product[1]:
        return "Not enough stock available", 400

    # Add the product or increase its quantity
    cart[product_key] = current_quantity + 1

    session['cart'] = cart

    return redirect('/shop')

@app.route('/cart')
def view_cart():

    if 'user' not in session:
        return redirect('/login?next=shop')

    import sqlite3

    cart = session.get('cart', {})

    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cart_items = []
    total = 0

    for product_id, quantity in cart.items():

        cursor.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        )

        product = cursor.fetchone()

        if product:
            subtotal = product['price'] * quantity

            cart_items.append({
                'id': product['id'],
                'name': product['name'],
                'price': product['price'],
                'image': product['image'],
                'quantity': quantity,
                'subtotal': subtotal
            })

            total += subtotal

    conn.close()

    return render_template(
        'cart.html',
        cart_items=cart_items,
        total=total
    )

@app.route('/update-cart', methods=['POST'])
def update_cart():

    if 'user' not in session:
        return redirect('/login')

    product_id = request.form.get('product_id')
    action = request.form.get('action')

    cart = session.get('cart', {})

    if product_id not in cart:
        return redirect('/cart')

    if action == 'remove':
        cart.pop(product_id)

    elif action in ('increase', 'decrease'):

        import sqlite3

        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()

        cursor.execute(
            "SELECT stock FROM products WHERE id = ?",
            (product_id,)
        )

        product = cursor.fetchone()
        conn.close()

        if not product:
            return redirect('/cart')

        if action == 'increase':
            if cart[product_id] < product[0]:
                cart[product_id] += 1

        elif action == 'decrease':
            if cart[product_id] > 1:
                cart[product_id] -= 1

    session['cart'] = cart

    return redirect('/cart')

@app.route('/shop-checkout', methods=['POST'])
def shop_checkout():

    # Check whether the customer is logged in
    if 'user' not in session:
        return redirect('/login')

    cart = session.get('cart', {})

    if not cart:
        return redirect('/cart')

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    line_items = []

    # Retrieve actual product prices from the database
    for product_id, quantity in cart.items():

        cursor.execute(
            "SELECT name, price, stock FROM products WHERE id = ?",
            (product_id,)
        )

        product = cursor.fetchone()

        if not product:
            conn.close()
            return "Product not found", 404

        name, price, stock = product

        if quantity < 1 or quantity > stock:
            conn.close()
            return "Insufficient stock available", 400

        line_items.append({
            'price_data': {
                'currency': 'aud',
                'product_data': {
                    'name': name
                },
                'unit_amount': round(price * 100)
            },
            'quantity': quantity
        })

    conn.close()

    checkout_session = stripe.checkout.Session.create(
        line_items=line_items,
        mode='payment',
        success_url=(
            'http://127.0.0.1:5000/shop-payment-success'
            '?session_id={CHECKOUT_SESSION_ID}'
        ),
        cancel_url='http://127.0.0.1:5000/cart',
        client_reference_id=session['user']
    )

    # Save the cart associated with this payment
    session['shop_pending_order'] = {
        'stripe_session_id': checkout_session.id,
        'user_email': session['user'],
        'items': [
            {
                'product_id': int(product_id),
                'quantity': quantity
            }
            for product_id, quantity in cart.items()
        ]
    }

    return redirect(checkout_session.url, code=303)
@app.route('/shop-payment-success')
def shop_payment_success():

    if 'user' not in session:
        return redirect('/login')

    stripe_session_id = request.args.get('session_id')

    if not stripe_session_id:
        return redirect('/cart')

    import sqlite3

    # Retrieve the payment information directly from Stripe.
    try:
        payment = stripe.checkout.Session.retrieve(stripe_session_id)
    except stripe.error.StripeError:
        return "Unable to verify payment.", 400

    if payment.payment_status != 'paid':
        return "Payment has not been completed.", 400

    if payment.client_reference_id != session['user']:
        return "This payment does not belong to your account.", 403

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    # Prevent the same payment from creating multiple orders.
    cursor.execute(
        "SELECT id FROM shop_orders WHERE stripe_session_id = ?",
        (stripe_session_id,)
    )

    existing_order = cursor.fetchone()

    if existing_order:
        conn.close()
        return render_template(
            'shop_payment_success.html',
            order_id=existing_order[0]
        )

    pending_order = session.get('shop_pending_order')

    if (
        not pending_order
        or pending_order['stripe_session_id'] != stripe_session_id
        or pending_order['user_email'] != session['user']
    ):
        conn.close()
        return "Order details could not be verified.", 400

    items = pending_order['items']

    if not items:
        conn.close()
        return "Your order is empty.", 400

    try:
        # Check the actual items and prices recorded by Stripe.
        stripe_items = stripe.checkout.Session.list_line_items(
            stripe_session_id,
            limit=100
        )

        if stripe_items.has_more:
            conn.close()
            return "Too many order items to verify.", 400

        conn.execute("BEGIN IMMEDIATE")

        verified_items = []
        total_cents = 0

        if len(stripe_items.data) != len(items):
            raise ValueError("Order items do not match Stripe.")

        for index, item in enumerate(items):

            product_id = item['product_id']
            quantity = item['quantity']

            cursor.execute(
                """
                SELECT name, price, stock
                FROM products
                WHERE id = ?
                """,
                (product_id,)
            )

            product = cursor.fetchone()

            if not product:
                raise ValueError("Product not found.")

            name, price, stock = product

            if quantity < 1 or stock < quantity:
                raise ValueError("Insufficient product stock.")

            stripe_item = stripe_items.data[index]
            expected_amount = round(price * 100)

            if (
                stripe_item.quantity != quantity
                or stripe_item.price.unit_amount != expected_amount
                or stripe_item.price.currency.lower() != 'aud'
                or stripe_item.description != name
            ):
                raise ValueError("Stripe order details do not match.")

            total_cents += expected_amount * quantity

            verified_items.append(
                (product_id, name, price, quantity)
            )

        if (
            payment.currency.lower() != 'aud'
            or payment.amount_total != total_cents
        ):
            raise ValueError("Payment amount does not match.")

        # Save the completed order.
        cursor.execute(
            """
            INSERT INTO shop_orders
            (user_email, stripe_session_id, total, payment_status)
            VALUES (?, ?, ?, ?)
            """,
            (
                session['user'],
                stripe_session_id,
                total_cents / 100,
                'paid'
            )
        )

        order_id = cursor.lastrowid

        # Save purchased products and reduce stock.
        for product_id, name, price, quantity in verified_items:

            cursor.execute(
                """
                INSERT INTO shop_order_items
                (order_id, product_id, product_name, price, quantity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, product_id, name, price, quantity)
            )

            cursor.execute(
                """
                UPDATE products
                SET stock = stock - ?
                WHERE id = ?
                """,
                (quantity, product_id)
            )

        conn.commit()

    except (ValueError, sqlite3.Error) as error:
        conn.rollback()
        conn.close()
        return f"Unable to complete order: {error}", 400

    finally:
        conn.close()

    # Clear the shopping cart after successfully saving the order.
    session.pop('cart', None)
    session.pop('shop_pending_order', None)

    return render_template(
        'shop_payment_success.html',
        order_id=order_id
    )

@app.route('/tournament', methods=['GET', 'POST'])
def tournament():

    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

        team_name = request.form['team_name']
        captain_name = request.form['captain_name']
        phone = request.form['phone']
        players = request.form['players']
        tournament_date = request.form['tournament_date']
        tournament_type = request.form['tournament_type']
        entry_fee = request.form['entry_fee']

        import sqlite3

        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO tournaments
        (team_name, captain_name, phone, players, tournament_date, tournament_type, entry_fee)

        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (team_name, captain_name, phone, players, tournament_date, tournament_type, entry_fee))

        conn.commit()
        conn.close()

        return render_template('tournament.html', success=True)

    return render_template('tournament.html')

@app.route('/admin-login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def admin_login():

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if is_locked_out('admin'):
            audit("ADMIN_LOGIN_BLOCKED_LOCKED", f"email={email}")
            return render_template('admin_login.html', locked=True)

        # Admin login details
        if email == os.getenv("ADMIN_EMAIL") and check_password_hash(os.getenv("ADMIN_PASSWORD_HASH"), password):
            reset_failed_logins('admin')
            session['admin'] = True
            session.permanent = True
            audit("ADMIN_LOGIN_SUCCESS", f"email={email}")
            return redirect('/admin')
        audit("ADMIN_LOGIN_FAILED", f"email={email}")
        record_failed_login('admin')
        return render_template('admin_login.html', error=True)

    return render_template('admin_login.html')

@app.route('/admin-logout')
def admin_logout():
    session.clear()
    return redirect('/admin-login')

@app.route('/admin')
@admin_required
def admin():

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM bookings ORDER BY id DESC")
    bookings = cursor.fetchall()

    cursor.execute("SELECT * FROM tournaments ORDER BY id DESC")
    tournaments = cursor.fetchall()
    cursor.execute("SELECT * FROM contact_messages ORDER BY id DESC")
    messages = cursor.fetchall()
        # Dashboard stats (real numbers)
    duration_prices = {'30 Minutes - $25': 25, '1 Hour - $40': 40, '2 Hours - $75': 75}
    cursor.execute("SELECT duration FROM bookings")
    booking_revenue = sum(duration_prices.get(r[0], 0) for r in cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM memberships")
    total_members = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(price), 0) FROM memberships")
    membership_revenue = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(total), 0) FROM shop_orders")
    shop_revenue = cursor.fetchone()[0]

    total_bookings = len(bookings)
    total_revenue = booking_revenue + membership_revenue + shop_revenue

    conn.close()

    return render_template('admin.html', bookings=bookings, tournaments=tournaments, messages=messages, total_bookings=total_bookings, total_members=total_members, total_revenue=total_revenue)
    
@app.route('/delete-booking/<int:id>', methods=['POST'])
@admin_required
def delete_booking(id):

    audit("ADMIN_DELETE_BOOKING", f"booking_id={id}")
    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("DELETE FROM bookings WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect('/admin')

@app.route('/dashboard')
def user_dashboard():

    if 'user' not in session:
        return redirect('/login')

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT full_name, email FROM users WHERE email = ?",
        (session['user'],)
    )

    user = cursor.fetchone()
    cursor.execute(
            "SELECT plan, end_date, status FROM memberships "
            "WHERE user_email = ? ORDER BY id DESC LIMIT 1",
            (session['user'],)
        )
    membership = cursor.fetchone()
    conn.close()

    if not user:
        session.pop('user', None)
        return redirect('/login')

    return render_template(
        'user_dashboard.html',
        user=user,
        membership=membership

    )
@app.route('/cancel-booking/<int:id>', methods=['POST'])
def cancel_booking(id):
    if 'user' not in session:
        return redirect('/login')

    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute(
        "SELECT stripe_session_id FROM bookings WHERE id = ? AND email = ?",
        (id, session['user'])
    )
    row = cursor.fetchone()

    refunded = False
    if row and row[0]:
        try:
            cs = stripe.checkout.Session.retrieve(row[0])
            if cs.payment_intent:
                stripe.Refund.create(payment_intent=cs.payment_intent)
                refunded = True
                audit("BOOKING_REFUNDED", f"user={session['user']} booking_id={id}")

        except stripe.StripeError as e:
         audit("REFUND_FAILED", f"user={session['user']} booking_id={id} err={e}")

    cursor.execute(
        "DELETE FROM bookings WHERE id = ? AND email = ?",
        (id, session['user'])
    )
    conn.commit()
    conn.close()

    audit("BOOKING_CANCELLED", f"user={session['user']} booking_id={id}")
    if refunded:
        return redirect('/my-bookings?msg=refunded')
    return redirect('/my-bookings?msg=cancelled')
  
    if 'user' not in session:
        return redirect('/login')

    import sqlite3
    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    # Only cancel a booking that belongs to the logged-in user
    cursor.execute(
        "DELETE FROM bookings WHERE id = ? AND email = ?",
        (id, session['user'])
    )
    conn.commit()
    conn.close()

    audit("BOOKING_CANCELLED", f"user={session['user']} booking_id={id}")
    return redirect('/my-bookings')


@app.route('/my-bookings')
def my_bookings():

    # Check whether the user is logged in
    if 'user' not in session:
        return redirect('/login')

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Retrieve bookings associated with the user's email
    cursor.execute("""
        SELECT id, booking_date, booking_time,
              lane, duration, players, booking_code, checked_in_at
        FROM bookings
        WHERE email = ?
        ORDER BY booking_date DESC, booking_time DESC
    """, (session['user'],))

    bookings = cursor.fetchall()
    conn.close()

    from datetime import datetime, timedelta

    now = datetime.now()

    booking_list = []

    for booking in bookings:
        booking_data = dict(booking)

        booking_datetime = datetime.strptime(
            booking_data['booking_date'] + ' ' +
            booking_data['booking_time'],
            '%Y-%m-%d %H:%M'
        )

        duration_map = {
            '30 Minutes - $25': 30,
            '1 Hour - $40': 60,
            '2 Hours - $75': 120
        }

        duration_minutes = duration_map.get(
            booking_data['duration'], 60
        )

        end_time = booking_datetime + timedelta(
            minutes=duration_minutes
        )

        if now < booking_datetime:
            booking_data['status'] = 'Upcoming'

        elif now < end_time:
            booking_data['status'] = 'In Progress'

        else:
            booking_data['status'] = 'Completed'

        booking_list.append(booking_data)

    return render_template(
        'my_bookings.html',
        bookings=booking_list
    )


@app.route('/profile')
def user_profile():

    if 'user' not in session:
        return redirect('/login')

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT full_name, email, phone,
               date_of_birth, gender, address
        FROM users
        WHERE email = ?
    """, (session['user'],))

    user = cursor.fetchone()
    conn.close()

    if not user:
        session.pop('user', None)
        return redirect('/login')

    return render_template('profile.html', user=user)

@app.route('/edit-profile', methods=['GET', 'POST'])
def edit_profile():

    if 'user' not in session:
        return redirect('/login')

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    email = session['user']

    if request.method == 'POST':

        full_name = request.form['full_name'].strip()
        phone = request.form['phone'].strip()
        date_of_birth = request.form['date_of_birth']
        gender = request.form['gender']
        address = request.form['address'].strip()

        # Validate the name and phone number
        if not full_name:
            conn.close()
            return "Full name is required.", 400

        if phone and (not phone.isascii() or not phone.isdigit()
                      or len(phone) > 15):
            conn.close()
            return "Please enter a valid phone number.", 400

        cursor.execute("""
            UPDATE users
            SET full_name = ?,
                phone = ?,
                date_of_birth = ?,
                gender = ?,
                address = ?
            WHERE email = ?
        """, (
            full_name,
            phone,
            date_of_birth,
            gender,
            address,
            email
        ))

        conn.commit()
        conn.close()

        return redirect('/profile')

    cursor.execute("""
        SELECT full_name, email, phone,
               date_of_birth, gender, address
        FROM users
        WHERE email = ?
    """, (email,))

    user = cursor.fetchone()
    conn.close()

    if not user:
        session.pop('user', None)
        return redirect('/login')

    return render_template('edit_profile.html', user=user)

@app.route('/change-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def change_password():

    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        import re
        if (len(new_password) < 8
                or not re.search(r'[A-Z]', new_password)
                or not re.search(r'[a-z]', new_password)
                or not re.search(r'[0-9]', new_password)
                or not re.search(r'[^A-Za-z0-9]', new_password)):
            return render_template(
                'change_password.html',
                error="Password must be 8+ characters with uppercase, lowercase, number, and special character."
            )

        if new_password != confirm_password:
            return render_template(
                'change_password.html',
                error="New passwords do not match."
            )

        import sqlite3
        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()

        cursor.execute(
            "SELECT password FROM users WHERE email = ?",
            (session['user'],)
        )

        user = cursor.fetchone()

        if not user or not check_password_hash(user[0], current_password):
            conn.close()
            return render_template(
                'change_password.html',
                error="Current password is incorrect."
            )

        hashed_password = generate_password_hash(new_password)

        cursor.execute(
            "UPDATE users SET password = ? WHERE email = ?",
            (hashed_password, session['user'])
        )

        conn.commit()
        conn.close()

        return render_template(
            'change_password.html',
            success="Password changed successfully!"
        )

    return render_template('change_password.html')

@app.route('/delete-tournament/<int:id>', methods=['POST'])
@admin_required
def delete_tournament(id):
    
    audit("ADMIN_DELETE_TOURNAMENT", f"tournament_id={id}")
    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tournaments WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect('/admin')

@app.route('/gate-check', methods=['GET', 'POST'])
@admin_required
def gate_check():
    result = None

    if request.method == 'POST':
        code = request.form.get('booking_code', '').strip().upper()

        import sqlite3
        conn = sqlite3.connect('indoor_cricket.db', timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookings WHERE booking_code = ?", (code,))
        booking = cursor.fetchone()

        today = datetime.now().strftime('%Y-%m-%d')

        if not booking:
            result = {'status': 'invalid',
                      'message': 'Booking not found. Do NOT allow entry.'}
            audit("GATE_INVALID_CODE", f"code={code}")

        elif booking['checked_in_at']:
            result = {'status': 'used',
                      'message': f"Already checked in at {booking['checked_in_at']}. Do NOT allow entry.",
                      'booking': dict(booking)}
            audit("GATE_CODE_REUSED", f"code={code}")

        elif booking['booking_date'] != today:
            result = {'status': 'wrong_date',
                      'message': f"This booking is for {booking['booking_date']}, not today.",
                      'booking': dict(booking)}
            audit("GATE_WRONG_DATE", f"code={code}")

        else:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "UPDATE bookings SET checked_in_at = ? WHERE id = ? AND checked_in_at IS NULL",
                (now, booking['id'])
            )
            conn.commit()
            result = {'status': 'valid',
                      'message': 'Valid ticket. Allow entry.',
                      'booking': dict(booking)}
            audit("GATE_CHECK_IN", f"code={code}")

        conn.close()

    return render_template('gate_check.html', result=result)

@app.route('/logout')
def logout():

    # Remove the logged-in user's session
    session.clear()
    # Redirect to the login page
    return redirect('/login')

if __name__ == '__main__':
      # ===== DEMO TOGGLE =====
    # Test 1 - HTTP (insecure, password visible):
    app.run(debug=False, threaded=True)

    # Test 2 - HTTPS (secure, encrypted):
   #app.run(debug=False, ssl_context=('cert.pem', 'key.pem'), threaded=True)