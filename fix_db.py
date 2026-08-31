import sqlite3

c = sqlite3.connect('data/index.db')

# Step 1: Create new table without UNIQUE constraint
c.execute("CREATE TABLE documents_new(id INTEGER PRIMARY KEY, sha1 TEXT NOT NULL, filename TEXT, title TEXT, system TEXT, systems TEXT, systems_text TEXT, doc_kind TEXT, num_pages INTEGER, indexed_at TEXT)")

# Step 2: Copy data from old table
c.execute("INSERT INTO documents_new SELECT * FROM documents")

# Step 3: Drop old table
c.execute("DROP TABLE documents")

# Step 4: Rename new table
c.execute("ALTER TABLE documents_new RENAME TO documents")

# Step 5: Verify
rows = c.execute("SELECT * FROM documents").fetchall()
print(f"Documents after fix: {len(rows)} rows")
print(f"Sample rows: {rows[:3]}")

c.commit()
c.close()
print("Done!")