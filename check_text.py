import sqlite3

c = sqlite3.connect('data/index.db')

# Get the dtech document ID
docs = c.execute("SELECT id, filename FROM documents WHERE filename LIKE '%dtech%'").fetchall()
print(f'dtech documents: {docs}')

if docs:
    dtech_id = docs[0][0]
    # Get pages for this document
    pages = c.execute("SELECT page_num, text, ocr_text FROM pages WHERE doc_id = ?", (dtech_id,)).fetchall()
    print(f'dtech pages ({len(pages)} total pages)')
    
    # Just count pages with content - don't try to print unicode
    pages_with_text = 0
    pages_with_ocr = 0
    for p in pages:
        t = str(p[1]) if p[1] else ''
        o = str(p[2]) if p[2] else ''
        if len(t.strip()) > 50:
            pages_with_text += 1
        if len(o.strip()) > 50:
            pages_with_ocr += 1
    
    print(f'Pages with substantial text: {pages_with_text}/{len(pages)}')
    print(f'Pages with substantial OCR: {pages_with_ocr}/{len(pages)}')
    
    # Show a few page numbers that have content
    print('\nSample pages with content:')
    for p in pages[:10]:
        t = str(p[1]) if p[1] else ''
        o = str(p[2]) if p[2] else ''
        t_len = len(t.strip())
        o_len = len(o.strip())
        print(f'  Page {p[0]}: text_len={t_len}, ocr_len={o_len}')
    
    # Also check all pages for specific keywords
    all_text = ' '.join(str(p[1] or '') for p in pages)
    all_ocr = ' '.join(str(p[2] or '') for p in pages)
    
    keywords = ['560032', '560011', 'A5025', 'A5086', '120 kg', '90 kg', '70 kg', '80 kg', 
                'MAX. WEIGHT', 'leaf height', 'leaf width', 'Slot-and-clamp', 'SURFACE-MOUNTING']
    
    print('\nKeyword searches in all text:')
    for kw in keywords:
        count = all_text.lower().count(kw.lower())
        if count > 0:
            print(f'  {kw}: {count} occurrences')
    
    all_ocr_count = 0
    for kw in keywords:
        count = all_ocr.lower().count(kw.lower())
        if count > 0:
            all_ocr_count += 1
    print(f'Keywords found in OCR text: {all_ocr_count}/{len(keywords)}')

c.close()