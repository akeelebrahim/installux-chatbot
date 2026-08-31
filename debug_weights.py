import sqlite3

c = sqlite3.connect('data/index.db')

# Check pages for hinge 560032 content
docs = c.execute('SELECT id, filename FROM documents').fetchall()
print('Documents:')
for d in docs:
    t = d[1] if d[1] else ""
    print(f"  {d[0]}: {t[:30] if t else 'None'}")

# Get pages for dtech
dtech_id = None
for did, df in docs:
    if 'dtech' in df.lower():
        dtech_id = did
        break

if dtech_id:
    pages = c.execute('SELECT page_num, text FROM pages WHERE doc_id = ? ORDER BY page_num', (dtech_id,)).fetchall()
    print(f'\ndtech pages:')
    for p in pages:
        t = p[1] if p[1] else ""
        print(f"\n--- Page {p[0]} ---")
        # Print just the relevant parts
        lines = t.split('\n')
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in ['560032', '120 kg', '90 kg', '80 kg', '150 kg', 'max. weight', 'three-leaf', 'two-leaf']):
                print(f"  {line[:200]}")
"