"""
One-time database fix for the Indoor Cricket Centre website.

Adds what app.py needs but the database is missing:
  1. bookings.checked_in_at   (used by My Bookings and Gate Check)
  2. shop_orders table         (used by shop checkout)
  3. shop_order_items table    (used by shop checkout)

Safe to run more than once - it only adds what is missing
and never deletes or changes existing data.

Run from the project folder:   python fix_database.py
"""
import sqlite3

conn = sqlite3.connect('indoor_cricket.db')
cursor = conn.cursor()

# 1. Add checked_in_at to bookings (if it isn't there yet)
cursor.execute("PRAGMA table_info(bookings)")
booking_columns = {row[1] for row in cursor.fetchall()}

if 'checked_in_at' not in booking_columns:
    cursor.execute("ALTER TABLE bookings ADD COLUMN checked_in_at TEXT")
    print("Added column: bookings.checked_in_at")
else:
    print("OK: bookings.checked_in_at already exists")

if 'booking_code' not in booking_columns:
    cursor.execute("ALTER TABLE bookings ADD COLUMN booking_code TEXT")
    print("Added column: bookings.booking_code")

# 2. Shop orders
cursor.execute("""
CREATE TABLE IF NOT EXISTS shop_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    stripe_session_id TEXT NOT NULL UNIQUE,
    total REAL NOT NULL,
    payment_status TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# 3. Items in each shop order
cursor.execute("""
CREATE TABLE IF NOT EXISTS shop_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (order_id) REFERENCES shop_orders(id)
)
""")
print("OK: shop_orders and shop_order_items tables are ready")

conn.commit()
conn.close()

print("\nDatabase fixed! You can now restart the site with: python app.py")
