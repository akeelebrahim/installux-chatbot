import sqlite3

c = sqlite3.connect('data/index.db')
docs = c.execute("SELECT id FROM documents WHERE filename LIKE '%dtech%'").fetchall()
dtech_id = docs[0][0]
pages = c.execute("SELECT page_num, text FROM pages WHERE doc_id = ? AND page_num IN (8, 9)", (dtech_id,)).fetchall()
for p in pages:
    t = (p[1] or '')[:800]
    print(f'Page {p[0]}: {t}')
    print()
c.close()