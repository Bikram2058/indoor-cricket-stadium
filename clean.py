import sqlite3
conn = sqlite3.connect('indoor_cricket.db')
conn.execute("DELETE FROM users WHERE email = 'admin@indoorcricket.com'")
conn.commit()
count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
print("Deleted. Remaining users:", count)
conn.close()