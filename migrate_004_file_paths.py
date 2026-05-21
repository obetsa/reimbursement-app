"""
Migration 004: add org_id to file paths in data/uploads/

Old: ReceiptsManager/{YYYY}/{MM}/{CompanyName}/{file}
New: ReceiptsManager/{org_id}/{YYYY}/{MM}/{CompanyName}/{file}

Run: python migrate_004_file_paths.py
"""
import os
import shutil
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

UPLOAD_FOLDER = os.path.join('data', 'uploads')
DRIVE_ROOT    = 'ReceiptsManager'

conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.cursor_factory = psycopg2.extras.RealDictCursor
cur  = conn.cursor()

# Get all attachments with old-style paths (no org_id segment)
# Old path: ReceiptsManager/2026/05/CompanyName/file.pdf
# Detect: parts[1] is a 4-digit year → old path
cur.execute("""
    SELECT a.id, a.file_path, r.org_id
    FROM attachments a
    JOIN records r ON a.record_id = r.id
    WHERE a.file_path IS NOT NULL
""")
rows = cur.fetchall()

moved   = 0
skipped = 0
errors  = []

for row in rows:
    file_path = row['file_path'].replace('\\', '/')
    org_id    = row['org_id']
    parts     = file_path.split('/')

    # Skip if already migrated (parts[1] is org_id, not a year)
    if len(parts) >= 2 and not parts[1].isdigit():
        skipped += 1
        continue

    # Old path: ReceiptsManager/YYYY/MM/CompanyName/filename
    if len(parts) < 5:
        errors.append(f'Unexpected path format: {file_path}')
        continue

    # Build new path: ReceiptsManager/org_id/YYYY/MM/CompanyName/filename
    new_parts    = [parts[0], org_id] + parts[1:]
    new_path     = '/'.join(new_parts)

    old_abs = os.path.join(UPLOAD_FOLDER, *parts)
    new_abs = os.path.join(UPLOAD_FOLDER, *new_parts)

    # Move file on disk
    if os.path.exists(old_abs):
        try:
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)
            shutil.move(old_abs, new_abs)
        except Exception as e:
            errors.append(f'Move failed {old_abs} → {new_abs}: {e}')
            continue
    else:
        # File missing on disk — still update DB path
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)

    # Update DB
    cur.execute("UPDATE attachments SET file_path=%s WHERE id=%s", (new_path, row['id']))
    moved += 1

conn.commit()

# Clean up empty old directories
old_root = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT)
if os.path.exists(old_root):
    for year_dir in os.listdir(old_root):
        year_path = os.path.join(old_root, year_dir)
        if os.path.isdir(year_path) and year_dir.isdigit():
            try:
                shutil.rmtree(year_path)
                print(f'  Removed old dir: {year_path}')
            except Exception as e:
                print(f'  Could not remove {year_path}: {e}')

conn.close()

print(f'\nМіграція завершена:')
print(f'  Переміщено:  {moved}')
print(f'  Вже нові:    {skipped}')
if errors:
    print(f'  Помилки ({len(errors)}):')
    for e in errors:
        print(f'    {e}')
else:
    print(f'  Помилок:     0')
