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
api.py                             # весь backend (~3000+ рядків)
index.html                         # SPA, один файл
js/
  app.js                           # весь frontend JS
  auth.js                          # авторизація (login/activate/OAuth)
  config.js                        # конфіг (DRIVE_ENABLED тощо)
  i18n.js                          # переклади UA/DE/EN
  db.js                            # DB helpers (frontend)
css/
  style.css                        # основні стилі
  components.css                   # компоненти
  mobile.css                       # мобільна адаптація
schema_pg.sql                      # базова схема PostgreSQL
migrate_001_org_hierarchy.sql      # organizations, org_members, org_id
migrate_002_leave_org.sql          # org_members.left_at (soft exclude)
migrate_003_email_verification.sql # users.email_verified, email_verifications
test_api.py                        # базові API тести (16/16)
test_hierarchy.py                  # тести ієрархії org (22/24)
test_members.py                    # тести member management (47/47)
requirements.txt
Dockerfile
docker-compose.yaml
docs/                              # нотатки, план, story.md (.gitignore)
```

## Ієрархія БД (зверху вниз)

```
users                         — акаунти (email+password або Google OAuth)
├── email_verified BOOLEAN
└── password_hash = 'PENDING' — юзер запрошений але не активований

email_verifications           — токени активації / email верифікації
└── → users.id

organizations                 — верхній рівень, org належить owner_id
└── → users.id (owner_id)

org_invites                   — токени запрошення (10 хв)
└── → organizations.id

org_members                   — членство юзера в org
├── → organizations.id
├── → users.id
├── role: admin | manager | user
└── left_at TIMESTAMP         — NULL = активний, NOT NULL = виключений (soft)

org_member_companies          — які компанії доступні конкретному члену
├── → org_members (user_id + org_id)
└── → companies.id

companies                     — компанії в межах org
└── → organizations.id

payment_instruments           — картки / рахунки в межах org
└── → organizations.id

records                       — записи витрат
├── → organizations.id
├── → users.id
├── → companies.id
└── → payment_instruments.id (card_id)

attachments                   — файли до запису
└── → records.id

return_events                 — події повернення коштів
└── → records.id

unprocessed_imports           — необроблені файли з Drive
└── → users.id
```

## Ролі в організації

| Роль      | Права                                        |
|-----------|----------------------------------------------|
| `admin`   | все: члени, компанії, всі записи             |
| `manager` | свої записи + компанії, які має доступ       |
| `user`    | тільки перегляд (viewer)                     |

## Поточний стан (станом на 21.05.2026)

**Гілка `feature/org-roles`** — активна розробка.

Зроблено:
- SQLite → PostgreSQL (psycopg2, `schema_pg.sql`)
- Реєстрація/логін (email+password + Google OAuth)
- Ієрархія org: organizations, org_members
- Onboarding: створити/приєднатись до org (invite token 10 хв)
- Сторінка членів org (тільки для admin): ролі, company access chips
- API оновлено під org_id: всі ендпоінти фільтрують по org
- Ролі: admin / manager / user (viewer прибрано)
- Company access: org_member_companies, фільтрація по юзеру
- i18n для auth/onboarding/org/verify/activate/invite (uk/de/en)
- Вихід з org: м'яке виключення (left_at), повернення зберігає id
- User role restrictions: hide write buttons у frontend
- Адмін запрошує юзерів через email (activation link, 48г)
- Реєстрація закрита (POST /auth/register → 403)
- Soft exclude / restore / permanent delete (з підтвердженням email)
- Email верифікація: SMTP Gmail, verify + activate flow
- Pending статус для незактивованих юзерів
- Тести: test_api 16/16 ✅, test_hierarchy 22/24, test_members 47/47 ✅, test_isolation 45/45 ✅

Відкладено / наступне: див. Roadmap нижче.

## Roadmap

### Фаза 0 — Виправити до Multi-org (критичне)

> Не можна рухатись далі поки не закрито

| # | Задача | Чому критично |
|---|--------|---------------|
| ✅ 0.1 | `data/` ізоляція — `org_id` в шляху файлів | Виправлено |
| ✅ 0.2 | Super admin — `is_superadmin` + панель | Виправлено |
| ✅ 0.3 | `test_isolation.py` — 45/45 | 5 IDOR вразливостей знайдено і виправлено |
| ✅ 0.4 | `org_member_companies` — очистка при permanent delete | Виправлено |
| ✅ 0.5 | Cascade delete org — `DELETE /superadmin/orgs/{id}` | Виправлено |

### Фаза 1 — Multi-org

| # | Задача | Деталі |
|---|--------|--------|
| 1.1 | `active_org_id` в сесії + `GET /org/list` + `POST /org/switch` | API знає яка org активна |
| 1.2 | Org switcher в Налаштування → Організація | Не в sidebar — рідкісна дія |
| 1.3 | Ліміт: max 2 активні org на free акаунт | `users.plan DEFAULT 'free'`; superadmin без ліміту |
| 1.4 | Видалення org owner'ом | `DELETE /org/delete`; сповіщення для членів (`user_notifications`) |
| 1.5 | Onboarding: "Приєднатись до ще однієї org" | Для юзерів вже в якійсь org |
| 1.6 | PostgreSQL RLS | Другий шар захисту після application-level |

**Правила ліміту:**
- Free: max 2 активні org (left_at IS NULL)
- Premium / Superadmin: без ліміту
- Перевірка в: POST /org/join, POST /org/create, POST /org/members/invite

### Superadmin панель — доповнення (після Фази 0)

| # | Задача | Деталі |
|---|--------|--------|
| SA.1 | Статистика-картки вгорі | Всього org / активних юзерів / записів / storage |
| SA.2 | Pending юзерів в таблиці | Скільки не активували акаунт по кожній org |
| SA.3 | Остання активність | Коли org востаннє додавала запис |
| SA.4 | Storage per org | Скільки МБ займає кожна org |
| SA.5 | Заблокувати/розблокувати org | Поле `is_suspended`, тимчасово відключити доступ |
| SA.6 | Видалити org | З підтвердженням (як permanent delete у members) |
| SA.7 | Пошук по назві org або email адміна | Filter в таблиці |
| SA.8 | Змінити план org | free → pro (після Billing фази) |

### Фаза 2 — Tenant features

| # | Задача | Деталі |
|---|--------|--------|
| 2.1 | Tenant settings | `organizations.settings JSONB` — валюта, назва в листах |
| 2.2 | Usage limits (Free tier) | 3 члени / 100 записів / 5 компаній |
| 2.3 | `plan` колонка на org | `free` / `pro` |

### Фаза 3 — Monetization

| # | Задача | Деталі |
|---|--------|--------|
| 3.1 | Stripe або LiqPay | Webhook → оновлює `plan` |
| 3.2 | Billing сторінка в settings | |
| 3.3 | Plan upgrade flow | |

### Суміжно

| Задача | Коли |
|--------|------|
| Supabase cloud | Після Фази 0, перед деплоєм |
| OWASP ZAP scan | Перед першим публічним деплоєм |
| Hypothesis tests | Після Multi-org |
| Перехід на Google OAuth | Після Фази 1 |

### Відкриті питання

**Шлях файлів: org_id vs org_name**
Зараз: `ReceiptsManager/{org_id}/...` — унікально, але нечитабельно.
Альтернатива: `ReceiptsManager/{org_name}/...` — читабельно, але потрібні умови:
1. `organizations.name` — UNIQUE constraint (заборонити однакові назви)
2. Перейменування org — заборонено super admin, дозволено тільки org-admin своєї org

Якщо обидві умови виконані → назва стабільна як id, можна перейти на org_name в шляхах.
Рішення відкладено. Поточний код використовує org_id.

**Google Drive — перевірити перед підключенням**
Drive sync вимкнено (`DRIVE_ENABLED = False`). Перед увімкненням:
1. Перевірити які OAuth scopes зараз є в Google Console
2. Переглянути всі `/drive/*` та `/sync/*` роути в `api.py`
3. Врахувати нову multi-tenant структуру папок (зараз `ReceiptsManager/{org_id}/...`)
4. Drive папки теж мають бути ізольовані по org

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
