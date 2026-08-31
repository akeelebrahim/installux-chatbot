import sqlite3

c = sqlite3.connect('data/index.db')
# Check pages table schema
schema = c.execute('PRAGMA table_info(pages)').fetchall()
print('Pages table schema:')
for s in schema:
    print(f'  {s}')

# Count pages
total = c.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
print(f'\nTotal pages: {total}')

# Check if ocr column exists and has data
try:
    with_ocr = c.execute("SELECT COUNT(*) FROM pages WHERE ocr IS NOT NULL AND length(ocr) > 0").fetchone()[0]
    print(f'Pages with ocr text: {with_ocr}')
except Exception as e:
    print(f'Error checking ocr: {e}')

# Check text column instead
try:
    with_text = c.execute("SELECT COUNT(*) FROM pages WHERE text IS NOT NULL AND length(text) > 0").fetchone()[0]
    print(f'Pages with text: {with_text}')
except Exception as e:
    print(f'Error checking text: {e}')

c.close()