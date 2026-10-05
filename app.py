from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            return redirect('/admin-login')
        return f(*args, **kwargs)
    return decorated_function

from datetime import timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, render_template, request, redirect, session

from flask_wtf.csrf import CSRFProtect

import os

import stripe

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

csrf = CSRFProtect(app)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Session security settings
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/booking', methods=['GET', 'POST'])
def booking():

    if request.method == 'POST':

        full_name = request.form['full_name']
        phone = request.form['phone']
        email = request.form['email']
        booking_date = request.form['booking_date']
        booking_time = request.form['booking_time']
        lane = request.form['lane']
        duration = request.form['duration']

        from datetime import datetime, timedelta

        today = datetime.now().date()
        selected_date = datetime.strptime(booking_date, '%Y-%m-%d').date()

        if selected_date < today:
            return render_template(
                'booking.html',
                error="You cannot book a date in the past."
                )
        price_map = {
            '30 Minutes - $25': 2500,
            '1 Hour - $40': 4000,
            '2 Hours - $75': 7500
        }

        amount = price_map.get(duration)

        if amount is None:
            return "Invalid booking duration", 400
        
        member = request.form['member']

        players = int(request.form['players'])

        if players < 1 or players > 8:
            return render_template(
                'booking.html',
                error="A maximum of 8 players is allowed per lane."
            )

        # Check for overlapping bookings
        import sqlite3

        duration_minutes = {
            '30 Minutes - $25': 30,
            '1 Hour - $40': 60,
            '2 Hours - $75': 120
        }

        new_duration = duration_minutes.get(duration)

        if new_duration is None:
            return "Invalid booking duration", 400

        # Calculate requested booking start and end time
        new_start = datetime.strptime(
            f"{booking_date} {booking_time}",
            "%Y-%m-%d %H:%M"
        )

        new_end = new_start + timedelta(minutes=new_duration)

        conn = sqlite3.connect('indoor_cricket.db')
        cursor = conn.cursor()

        # Get every booking for this lane on this date
        cursor.execute("""
            SELECT booking_time, duration
            FROM bookings
            WHERE booking_date = ?
            AND lane = ?
        """, (booking_date, lane))

        existing_bookings = cursor.fetchall()
        conn.close()

        # Check if selected duration overlaps an existing booking
        for existing_time, existing_duration in existing_bookings:

            existing_minutes = duration_minutes.get(existing_duration)

            if existing_minutes is None:
                continue

            existing_start = datetime.strptime(
                f"{booking_date} {existing_time}",
                "%Y-%m-%d %H:%M"
            )

            existing_end = existing_start + timedelta(
                minutes=existing_minutes
            )

            # Check for overlap
            if new_start < existing_end and new_end > existing_start:

                # User selected a time inside an existing booking
                if new_start >= existing_start:
                    next_available = existing_end.strftime("%I:%M %p")

                    error_message = (
                        f"This lane is currently booked. "
                        f"Next available at {next_available}."
                    )

                # Starting time is free, but selected duration hits next booking
                else:
                    next_booking = existing_start.strftime("%I:%M %p")

                    error_message = (
                        f"Selected duration overlaps another booking "
                        f"starting at {next_booking}. "
                        f"Please choose a shorter duration."
                    )

                return render_template(
                    'booking.html',
                    error=error_message
                )
    
        session['pending_booking'] = {
            'full_name': full_name,
            'phone': phone,
            'email': email,
            'booking_date': booking_date,
            'booking_time': booking_time,
            'lane': lane,
            'duration': duration,
            'member': member,
            'players': players,
            'amount': amount
        }

        return redirect('/create-checkout-session')


    return render_template('booking.html')

@app.route('/check-availability')
def check_availability():
    booking_date = request.args.get('date')
    booking_time = request.args.get('time')
    lane = request.args.get('lane')

    if not booking_date or not booking_time or not lane:
        return {
            'available': False,
            'message': 'Please select lane, time and date.'
        }

    import sqlite3
    from datetime import datetime, timedelta

    selected_start = datetime.strptime(
        f"{booking_date} {booking_time}",
        "%Y-%m-%d %H:%M"
    )

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT booking_time, duration
        FROM bookings
        WHERE booking_date = ?
        AND lane = ?
    """, (booking_date, lane))

    existing_bookings = cursor.fetchall()
    conn.close()

    duration_minutes = {
        '30 Minutes - $25': 30,
        '1 Hour - $40': 60,
        '2 Hours - $75': 120
    }

    for existing_time, existing_duration in existing_bookings:

        minutes = duration_minutes.get(existing_duration)

        if minutes is None:
            continue

        existing_start = datetime.strptime(
            f"{booking_date} {existing_time}",
            "%Y-%m-%d %H:%M"
        )

        existing_end = existing_start + timedelta(minutes=minutes)

        # Selected time is inside an existing booking
        if existing_start <= selected_start < existing_end:

            next_available = existing_end.strftime("%I:%M %p")

            return {
                'available': False,
                'message': f'Lane is currently booked. Next available at {next_available}.'
            }

    return {
        'available': True,
        'message': 'Lane is available!'
    }

@app.route('/unavailable-dates')
def unavailable_dates():

    booking_time = request.args.get('time')
    lane = request.args.get('lane')

    if not booking_time or not lane:
        return {'unavailable_dates': []}

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT booking_date
        FROM bookings
        WHERE booking_time = ?
        AND lane = ?
    """, (booking_time, lane))

    rows = cursor.fetchall()
    conn.close()

    dates = [row[0] for row in rows]

    return {
        'unavailable_dates': dates
    }

@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

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
            session['user'] = email

            # Return to Shop if the user originally clicked Shop
            if request.form.get('next') == 'shop':
                return redirect('/shop')

            return redirect('/dashboard')
        
        else:
            return render_template('login.html', error=True)

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Password length check
    import re
    if (len(password) < 8
                or not re.search(r'[A-Za-z]', password)
                or not re.search(r'[0-9]', password)):
            return render_template(
                'register.html',
                error="Password must be at least 8 characters and include letters and numbers."
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

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=['card'],

        line_items=[
            {
                'price_data': {
                    'currency': 'aud',
                    'product_data': {
                        'name': f"Indoor Cricket Booking - {booking['duration']}"
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

    cursor.execute("""
        INSERT INTO bookings
        (full_name, phone, email, booking_date,
         booking_time, lane, duration, member, players)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        booking['full_name'],
        booking['phone'],
        booking['email'],
        booking['booking_date'],
        booking['booking_time'],
        booking['lane'],
        booking['duration'],
        booking['member'],
        booking['players']
    ))

    conn.commit()
    conn.close()

    session.pop('pending_booking', None)

    session.pop('checkout_session_id', None)

    return render_template('payment_success.html')

@app.route('/payment-cancel')
def payment_cancel():
    session.pop('pending_booking', None)
    session.pop('checkout_session_id', None)

    return render_template('payment_cancel.html')

@app.route('/membership')
def membership():
    if 'user' not in session:
        return redirect('/login')
    
    return render_template('membership.html')

@app.route('/contact')
def contact():
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
        payment_method_types=['card'],
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
def admin_login():

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Admin login details
        if email == os.getenv("ADMIN_EMAIL") and check_password_hash(os.getenv("ADMIN_PASSWORD_HASH"), password):
            session['admin'] = True
            return redirect('/admin')

        return render_template('admin_login.html', error=True)

    return render_template('admin_login.html')

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/admin-login')

@app.route('/admin')
@admin_required
def admin():

    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM bookings")
    bookings = cursor.fetchall()

    cursor.execute("SELECT * FROM tournaments")
    tournaments = cursor.fetchall()

    conn.close()

    return render_template('admin.html', bookings=bookings, tournaments=tournaments)
    
@app.route('/delete-booking/<int:id>')
@admin_required
def delete_booking(id):

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
    conn.close()

    if not user:
        session.pop('user', None)
        return redirect('/login')

    return render_template(
        'user_dashboard.html',
        user=user
    )

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
               lane, duration, players
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
def change_password():

    if 'user' not in session:
        return redirect('/login')

    if request.method == 'POST':

        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if len(new_password) < 8:
            return render_template(
                'change_password.html',
                error="New password must contain at least 8 characters."
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

        if not user or not check_password_hash(
            user[0], current_password
        ):
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

@app.route('/delete-tournament/<int:id>')
@admin_required
def delete_tournament(id):
    
    import sqlite3

    conn = sqlite3.connect('indoor_cricket.db')
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tournaments WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect('/admin')

@app.route('/logout')
def logout():

    # Remove the logged-in user's session
    session.pop('user', None)

    # Redirect to the login page
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=False)

