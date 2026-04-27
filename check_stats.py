"""
Статистика файлів: БД / локально / Google Drive
Run: python check_stats.py
"""
import os, sqlite3, requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH       = os.path.join('data', 'local.db')
UPLOAD_FOLDER = os.path.join('data', 'uploads')
DRIVE_ROOT    = 'ReceiptsManager'
CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID')
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')


def get_token(refresh_token):
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token',
    })
    return r.json().get('access_token')


SKIP_FOLDERS = {'Backup'}

def drive_count(token, folder_id, depth=0):
    if depth > 5:
        return 0
    r = requests.get('https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {token}'},
        params={'q': f"'{folder_id}' in parents and trashed=false",
                'fields': 'files(id,name,mimeType)', 'pageSize': 1000}).json()
    files = r.get('files', [])
    total = 0
    for f in files:
        if f['mimeType'] == 'application/vnd.google-apps.folder':
            if f['name'] not in SKIP_FOLDERS:
                total += drive_count(token, f['id'], depth + 1)
        else:
            total += 1
    return total


def drive_find_folder(token, name):
    r = requests.get('https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {token}'},
        params={'q': f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id)'}).json()
    files = r.get('files', [])
    return files[0]['id'] if files else None


# ── БД ──
conn = sqlite3.connect(DB_PATH)
att_total   = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
att_local   = conn.execute("SELECT COUNT(*) FROM attachments WHERE file_path IS NOT NULL AND (drive_id IS NULL OR storage_type='local')").fetchone()[0]
att_drive   = conn.execute("SELECT COUNT(*) FROM attachments WHERE drive_id IS NOT NULL AND storage_type='drive'").fetchone()[0]
att_both    = conn.execute("SELECT COUNT(*) FROM attachments WHERE file_path IS NOT NULL AND drive_id IS NOT NULL").fetchone()[0]
unprocessed = conn.execute("SELECT COUNT(*) FROM unprocessed_imports").fetchone()[0]
row = conn.execute("SELECT refresh_token FROM users WHERE refresh_token IS NOT NULL LIMIT 1").fetchone()
conn.close()

# ── Локально ──
local_count = 0
if os.path.exists(UPLOAD_FOLDER):
    for _, _, files in os.walk(UPLOAD_FOLDER):
        local_count += len(files)

drive_files = '?'
if row and row[0]:
    try:
        token = get_token(row[0])
        if token:
            folder_id = drive_find_folder(token, DRIVE_ROOT)
            drive_files = drive_count(token, folder_id) if folder_id else 0
    except Exception:
        pass

print(f'БД:       {att_total}')
print(f'Локально: {local_count}')
print(f'Drive:    {drive_files}')
