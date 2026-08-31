import sqlite3

c = sqlite3.connect('data/index.db')
docs = c.execute('SELECT filename FROM documents ORDER BY filename').fetchall()
pages = c.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
figures = c.execute('SELECT COUNT(*) FROM figures').fetchone()[0]
ocr_result = c.execute("SELECT COUNT(*) FROM pages WHERE ocr != ''").fetchone()[0]
print(f'Documents: {len(docs)}')
print(f'Pages: {pages}')
print(f'Figures: {figures}')
print(f'Pages with OCR: {ocr_result}')
c.close()