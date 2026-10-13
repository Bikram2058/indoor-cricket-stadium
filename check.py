import sqlite3
conn = sqlite3.connect('indoor_cricket.db')
rows = conn.execute(
    "SELECT user_email, plan, status, end_date FROM memberships "
    "WHERE user_email = 'r.gharti2004@gmail.com'"
).fetchall()
for r in rows:
    print(r)
conn.close()