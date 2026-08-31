import sqlite3

c = sqlite3.connect('data/index.db')

# Check FTS for hinge 560032
print('Searching for hinge 560032 in FTS...')
result = c.execute("""
    SELECT p.page_num, p.text, p.ocr_text
    FROM pages p 
    JOIN documents d ON d.id = p.doc_id
    WHERE d.filename = 'dtech_comete_70th_installux_en.pdf'
    AND (p.text LIKE '%560032%' OR p.ocr_text LIKE '%560032%')
    ORDER BY p.page_num
""").fetchall()
for r in result:
    t1 = r[1] or ""
    t2 = r[2] or ""
    has560032_text = "560032" in t1
    has560032_ocr = "560032" in t2
    print(f'Page {r[0]}: text has 560032={has560032_text}, ocr has 560032={has560032_ocr}')

# Now check for weight values
print('\nSearching for weight values...')
result2 = c.execute("""
    SELECT p.page_num, p.text
    FROM pages p 
    JOIN documents d ON d.id = p.doc_id
    WHERE d.filename = 'dtech_comete_70th_installux_en.pdf'
    AND (p.text LIKE '%120 kg%' OR p.text LIKE '%150 kg%' OR p.text LIKE '%90 kg%' OR p.text LIKE '%80 kg%')
    ORDER BY p.page_num
""").fetchall()
for r in result2:
    print(f'Page {r[0]}: has weight values: {r[1][:150]}...')
" 2>&1