import sqlite3

conn = sqlite3.connect("indoor_cricket.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    booking_date TEXT NOT NULL,
    booking_time TEXT NOT NULL,
    lane TEXT NOT NULL,
    duration TEXT NOT NULL,
    member TEXT NOT NULL,
    players INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name TEXT NOT NULL,
    captain_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    players INTEGER NOT NULL,
    tournament_date TEXT NOT NULL,
    tournament_type TEXT NOT NULL,
    entry_fee TEXT NOT NULL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    image TEXT,
    stock INTEGER NOT NULL DEFAULT 0
)
""")

conn.commit()
conn.close()

print("Database and bookings table created successfully!")

import sqlite3

conn = sqlite3.connect('indoor_cricket.db')
cursor = conn.cursor()

new_columns = {
    'phone': 'TEXT',
    'date_of_birth': 'TEXT',
    'gender': 'TEXT',
    'address': 'TEXT',
    'registration_date': 'TEXT'
}

cursor.execute("PRAGMA table_info(users)")
existing_columns = {
    column[1] for column in cursor.fetchall()
}

for column, data_type in new_columns.items():
    if column not in existing_columns:
        cursor.execute(
            f"ALTER TABLE users ADD COLUMN {column} {data_type}"
        )

conn.commit()
conn.close()

print("User profile database updated successfully!")

