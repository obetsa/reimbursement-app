# Reimbursement App — CLAUDE.md

## Що це

Веб-застосунок для відстеження витрат та відшкодувань. Два сценарії: приватні платежі (з кишені, очікується відшкодування) та корпоративна картка (для звітності). Підтримує кілька мов (UA/DE/EN) і мобільний UI.

## Стек

- **Backend:** Python Flask, PostgreSQL (psycopg2-binary), порт 5500
- **Frontend:** Vanilla JS + HTML + CSS (без фреймворків)
- **Auth:** email+password (SHA256) + Google OAuth
- **Deploy:** Docker Hub `obetsa/reimbursement-app:latest`, docker-compose

## Запуск локально

```bash
python api.py           # сервер на http://localhost:5500
python test_api.py      # тести (потрібна змінна SESSION_COOKIE або аргумент)
python test_hierarchy.py
```

PostgreSQL має бути запущений локально. `DATABASE_URL` береться з `.env`.

## Структура файлів

```
api.py                          # весь backend (~2000+ рядків)
index.html                      # SPA, один файл
js/
  app.js                        # весь frontend JS
  auth.js                       # авторизація (login/register/OAuth)
  config.js                     # конфіг (DRIVE_ENABLED тощо)
  i18n.js                       # переклади UA/DE/EN
  db.js                         # DB helpers (frontend)
css/
  style.css                     # основні стилі
  components.css                # компоненти
  mobile.css                    # мобільна адаптація
schema_pg.sql                   # схема PostgreSQL (всі таблиці)
migrate_001_org_hierarchy.sql   # міграція: organizations, org_members
migrate_002_seed_orgs.py        # seed: 3 org для існуючих юзерів
test_api.py                     # API тести
test_hierarchy.py               # тести ієрархії org
requirements.txt
Dockerfile
docker-compose.yaml
docs/                           # нотатки, план, story.md (.gitignore)
```

## Таблиці БД

- `users` — юзери (email, password_hash, google_id)
- `organizations` — org (name, invite_code, owner_id)
- `org_members` — членство (org_id, user_id, role: admin/manager/user)
- `org_member_companies` — доступ юзера до компаній в межах org
- `companies` — компанії (org_id)
- `payment_instruments` — картки/рахунки (org_id)
- `records` — записи витрат (org_id, user_id)
- `attachments` — вкладення до записів
- `return_events` — події повернення коштів

## Ролі в організації

| Роль      | Права                                        |
|-----------|----------------------------------------------|
| `admin`   | все: члени, компанії, всі записи             |
| `manager` | свої записи + компанії, які має доступ       |
| `user`    | тільки перегляд (viewer)                     |

## Поточний стан (станом на 20.05.2026)

**Гілка `feature/org-roles`** — активна розробка.

Зроблено:
- SQLite → PostgreSQL (psycopg2, `schema_pg.sql`)
- Реєстрація/логін (email+password + Google OAuth)
- Ієрархія org: organizations, org_members
- Onboarding: створити/приєднатись до org (invite token 24год)
- Сторінка членів org (тільки для admin): ролі, company access
- API оновлено під org_id: всі ендпоінти фільтрують по org
- Ролі: user → manager, viewer → user
- Company access: org_member_companies, фільтрація по юзеру
- i18n для auth/onboarding/org (uk/de/en)
- Тести: 16/16 ✅

Відкладено / наступне:
- Supabase cloud (КРОК 13)
- Вихід з організації
- Email верифікація
- Фінальні тести перед деплоєм

## Важливі правила

### 1. Ніколи не видаляти код
Тільки коментувати (`//`, `/* */`) або додавати guard (`if (!FLAG) return`).
Якщо треба "вимкнути" фічу — використовувати флаг (`DRIVE_ENABLED = False`).
Видаляти тільки якщо юзер **явно** написав "видали".

### 2. Пояснювати перед змінами
Перед початком будь-яких змін у коді — пояснити що саме буде зроблено.
Якщо завдання незрозуміле — перепитати. Тільки після підтвердження — виконувати.

### 3. Не додавати зайвого
Не додавати поля, фічі або "покращення" яких не просив юзер.
Якщо є готовий зразок (функція, файл) — копіювати логіку 1-в-1, без розширень.

### 4. index.html — тільки через Edit/PyCharm
Ніколи не завантажувати `index.html` через Claude.ai — Cloudflare CDN інжектить `email-decode.min.js`, що псує файл.

### 5. Не писати в docs/story.md
Юзер веде журнал вручну. Не чіпати цей файл.

## Форма запису — валідація

**Обов'язкові:** дата, сума, заголовок, тип оплати (private/company), спосіб оплати (card/cash).

**Необов'язкові:** конкретна картка, компанія, примітка, вкладення.

## Drive sync

Вимкнено: `DRIVE_ENABLED = False` в `api.py` та `app.js`. Всі Drive роути повертають 503. Увімкнути = 2 рядки. Весь код збережено.

## Git

- `main` — стабільна версія
- `feature/org-roles` — поточна активна гілка
- `web` — Google OAuth + Drive (попередня активна)

Деплой: `docker build` → push на `obetsa/reimbursement-app:latest`.
