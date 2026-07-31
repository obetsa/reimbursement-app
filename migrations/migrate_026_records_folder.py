"""
Migration 026 (python, авто-запуск через runner.py): документи-вкладення
переносяться в підпапку records/, щоб не колізити з новою підпапкою cexp/
(вкладення "Витрати по компаніях").

Old: ReceiptsManager/{org_id}/{YYYY}/{MM}/{CompanyName}/{file}
New: ReceiptsManager/{org_id}/records/{YYYY}/{MM}/{CompanyName}/{file}

Ідемпотентно: шляхи що вже мають сегмент records/ пропускаються.
Викликається автоматично з migrations/runner.py при старті застосунку.
"""
import os
import shutil

UPLOAD_FOLDER = os.path.join('data', 'uploads')


def run(cur):
    cur.execute("""
        SELECT a.id, a.file_path, r.org_id
        FROM attachments a
        JOIN records r ON a.record_id = r.id
        WHERE a.file_path IS NOT NULL
    """)
    rows = cur.fetchall()

    moved = 0
    skipped = 0

    for att_id, file_path, org_id in rows:
        file_path = file_path.replace('\\', '/')
        parts = file_path.split('/')

        # Очікуємо: [ReceiptsManager, org_id, YYYY, MM, CompanyName, filename]
        if len(parts) < 2 or parts[1] != org_id:
            skipped += 1
            continue
        if len(parts) >= 3 and parts[2] == 'records':
            skipped += 1
            continue

        new_parts = [parts[0], parts[1], 'records'] + parts[2:]
        new_path = '/'.join(new_parts)

        old_abs = os.path.join(UPLOAD_FOLDER, *parts)
        new_abs = os.path.join(UPLOAD_FOLDER, *new_parts)

        if os.path.exists(old_abs):
            try:
                os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                shutil.move(old_abs, new_abs)
            except Exception as e:
                print(f'[migrate_026] move failed {old_abs} -> {new_abs}: {e}')
                continue
        else:
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)

        cur.execute("UPDATE attachments SET file_path=%s WHERE id=%s", (new_path, att_id))
        moved += 1

    # Прибрати спорожнілі старі каталоги YYYY/... на корені кожної org.
    # Тільки os.rmdir (не rmtree) — мовчки провалюється на непорожній директорії,
    # щоб точно нічого не видалити, якщо якийсь файл не вдалось перенести вище.
    root = os.path.join(UPLOAD_FOLDER, 'ReceiptsManager')
    if os.path.exists(root):
        for org_dir in os.listdir(root):
            org_path = os.path.join(root, org_dir)
            if not os.path.isdir(org_path):
                continue
            for year_dir in os.listdir(org_path):
                if not year_dir.isdigit():
                    continue
                year_path = os.path.join(org_path, year_dir)
                if not os.path.isdir(year_path):
                    continue
                for dirpath, _, _ in list(os.walk(year_path, topdown=False)):
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass

    print(f'[migrate_026] перенесено: {moved}, пропущено (вже нові): {skipped}')
