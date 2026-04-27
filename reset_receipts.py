"""
One-time cleanup: delete receipt files locally, on Drive, and clear attachments from DB.
Run: python reset_receipts.py
"""
import os, sqlite3, shutil, requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH       = os.path.join('data', 'local.db')
UPLOAD_FOLDER = os.path.join('data', 'uploads', 'ReceiptsManager')
DRIVE_ROOT    = 'ReceiptsManager'
CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID')
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')


def get_token(refresh_token):
    r = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token',
    })
    return r.json().get('access_token')


def drive_delete(token, file_id):
    requests.delete(f'https://www.googleapis.com/drive/v3/files/{file_id}',
                    headers={'Authorization': f'Bearer {token}'})


def drive_find_folder(token, name):
    r = requests.get('https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {token}'},
        params={'q': f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id)', 'spaces': 'drive'}).json()
    files = r.get('files', [])
    return files[0]['id'] if files else None


def drive_nuke(token, folder_id, name=''):
    items = requests.get('https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {token}'},
        params={'q': f"'{folder_id}' in parents and trashed=false",
                'fields': 'files(id,name,mimeType)', 'spaces': 'drive', 'pageSize': 100}
    ).json().get('files', [])
    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            drive_nuke(token, item['id'], item['name'])
        else:
            print(f'  файл: {item["name"]}')
            drive_delete(token, item['id'])
    print(f'  папка: {name or folder_id}')
    drive_delete(token, folder_id)


# 1. Локальні файли
print('=== 1. Локальні файли ===')
if os.path.exists(UPLOAD_FOLDER):
    shutil.rmtree(UPLOAD_FOLDER)
    print(f'  Видалено: {UPLOAD_FOLDER}')
else:
    print(f'  Не знайдено: {UPLOAD_FOLDER}')

# 2. Google Drive
print('\n=== 2. Google Drive ===')
conn = sqlite3.connect(DB_PATH)
row = conn.execute("select refresh_token from users where refresh_token is not null limit 1").fetchone()
conn.close()
if row and row[0]:
    token = get_token(row[0])
    if token:
        folder_id = drive_find_folder(token, DRIVE_ROOT)
        if folder_id:
            drive_nuke(token, folder_id, DRIVE_ROOT)
            print(f'  Папку {DRIVE_ROOT} видалено')
        else:
            print(f'  Папка {DRIVE_ROOT} не знайдена на Drive')
    else:
        print('  Не вдалося отримати токен')
else:
    print('  refresh_token відсутній')

# 3. База даних
print('\n=== 3. База даних ===')
conn = sqlite3.connect(DB_PATH)
a = conn.execute('delete from attachments').rowcount
u = conn.execute('delete from unprocessed_imports').rowcount
conn.commit()
conn.close()
print(f'  attachments: {a} рядків видалено')
print(f'  unprocessed_imports: {u} рядків видалено')

print('\n✅ Готово.')
