import sqlite3

products = [
    # (id, name, price, image, stock)
    (5, 'Cricket Helmet',        125, 'helmet.png', 25),
    (6, 'Stumps Set',            75,  'stumps.png', 20),
    (7, 'Cricket Kit Combo',     300, 'combo.png',  10),
    (8, 'Cricket Australia Cap', 35,  'cap.png',    40),
]

conn = sqlite3.connect('indoor_cricket.db')
cur = conn.cursor()
cur.executemany(
    "INSERT OR REPLACE INTO products (id, name, price, image, stock) VALUES (?, ?, ?, ?, ?)",
    products,
)
conn.commit()
for row in cur.execute("SELECT id, name, price, stock FROM products ORDER BY id").fetchall():
    print(" ", row)
conn.close()