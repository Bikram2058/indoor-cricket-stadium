import sqlite3
c = sqlite3.connect('indoor_cricket.db')
n = c.execute('DELETE FROM memberships WHERE user_email=?', ('r.gharti2004@gmail.com',)).rowcount
c.commit()
print('Removed', n)