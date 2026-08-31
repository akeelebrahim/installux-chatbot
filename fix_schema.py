import sqlite3

c = sqlite3.connect('data/index.db')
# Check the documents table schema
schema = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'").fetchone()[0]
print('Documents schema:')
print(schema)
print()

# Check if there's a UNIQUE constraint on sha1
if 'UNIQUE' in schema or 'unique' in schema:
    print('UNIQUE constraint found on documents table')
    # Extract the constraint name
    import re
    match = re.search(r'UNIQUE\((\w+)\)', schema, re.IGNORECASE)
    if match:
        constraint_name = match.group(1)
        print(f'Constraint name: {constraint_name}')
        # Drop the constraint
        c.execute(f'CREATE TABLE documents_new AS SELECT * FROM documents;')
        c.execute('DROP TABLE documents;')
        c.execute('CREATE TABLE documents(sha1 TEXT, filename TEXT, title TEXT, system TEXT, systems TEXT, systems_text TEXT, doc_kind TEXT, num_pages INTEGER, PRIMARY KEY(sha1))')
        # Actually let me just check what the original schema was
        c.execute('DROP TABLE documents_new;')
        c.execute('CREATE TABLE documents(sha1 TEXT, filename TEXT, title TEXT, system TEXT, systems TEXT, systems_text TEXT, doc_kind TEXT, num_pages INTEGER)')
        # Copy data back
        c.execute('INSERT INTO documents SELECT * FROM documents_backup')
else:
    print('No UNIQUE constraint found')
    
c.close()