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
python api.py                        # сервер на http://localhost:5500
python tests/test_api.py             # тести (потрібна змінна SESSION_COOKIE або аргумент)
python tests/test_hierarchy.py
python tests/test_members.py
python tests/test_isolation.py       # не потребує cookie — створює тестових юзерів сам
```

PostgreSQL має бути запущений локально. `DATABASE_URL` береться з `.env`.

## Структура файлів

```
api.py                             # весь backend (~3000+ рядків)
index.html                         # SPA, один файл
admin.html                         # окрема адмін панель (token login, SA функції)
js/
  app.js                           # весь frontend JS
  admin.js                         # SA функції для admin.html (окремо від app.js)
  auth.js                          # авторизація (login/activate/OAuth)
  config.js                        # конфіг (DRIVE_ENABLED тощо)
  i18n.js                          # переклади UA/DE/EN
  db.js                            # DB helpers (frontend)
css/
  style.css                        # основні стилі
  components.css                   # компоненти
  mobile.css                       # мобільна адаптація
migrations/
  schema_pg.sql                    # базова схема PostgreSQL (запуск: psql ... < migrations/schema_pg.sql)
  migrate_001_org_hierarchy.sql    # organizations, org_members, org_id
  migrate_002_leave_org.sql        # org_members.left_at (soft exclude)
  migrate_002_seed_orgs.py         # seed: org для існуючих юзерів
  migrate_003_email_verification.sql # users.email_verified, email_verifications
  migrate_004_file_paths.py        # міграція шляхів файлів
  migrate_005_superadmin.sql       # is_superadmin
  migrate_006_multiorg.sql         # users.plan, org_deletion_notices
  migrate_007_suspended.sql        # organizations.is_suspended
  migrate_008_registered_at.sql    # users.registered_at
  migrate_009_user_suspended.sql   # users.is_suspended
tests/
  test_api.py                      # базові API тести (16/16)
  test_hierarchy.py                # тести ієрархії org (22/24)
  test_members.py                  # тести member management (47/47)
  test_isolation.py                # ізоляція org (45/45)
  test_superadmin.py               # SA: delete org + deletion notices (11/11)
requirements.txt
Dockerfile
docker-compose.yaml
docs/                              # нотатки, план, story.md (.gitignore)

> Всі нові тести створювати в папці `tests/`.
> Всі нові SQL/Python міграції створювати в папці `migrations/`.
```

## Ієрархія БД (зверху вниз)

```
users                         — акаунти (email+password або Google OAuth)
├── email_verified BOOLEAN
├── registered_at TIMESTAMP   — коли активував акаунт (≠ created_at = коли створено/запрошено)
├── is_suspended BOOLEAN       — заблоковано superadmin
└── password_hash = 'PENDING' — юзер запрошений але не активований

email_verifications           — токени активації / email верифікації
└── → users.id

organizations                 — верхній рівень, org належить owner_id
├── → users.id (owner_id)
└── is_suspended BOOLEAN       — заблоковано superadmin (SA.5)

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

## Поточний стан (станом на 10.06.2026)

**Гілка `feature/org-roles`** — активна розробка.

Зроблено:
- SQLite → PostgreSQL (psycopg2, `migrations/schema_pg.sql`)
- Реєстрація/логін (email+password + Google OAuth)
- Ієрархія org: organizations, org_members
- Onboarding: створити/приєднатись до org (invite token 10 хв)
- Сторінка членів org (тільки для admin): ролі, company access chips
- API оновлено під org_id: всі ендпоінти фільтрують по org
- Ролі: admin / manager / user (viewer прибрано)
- Company access: org_member_companies, фільтрація по юзеру
- i18n для auth/onboarding/org/verify/activate/invite/superadmin (uk/de/en)
- Вихід з org: м'яке виключення (left_at), повернення зберігає id
- User role restrictions: hide write buttons у frontend
- Адмін запрошує юзерів через email (activation link, 48г)
- Реєстрація закрита (POST /auth/register → 403)
- Soft exclude / restore / permanent delete (з підтвердженням email)
- Email верифікація: SMTP Gmail, verify + activate flow
- Pending статус для незактивованих юзерів
- Фаза 0 ✅: ізоляція файлів, superadmin, IDOR фікси, cascade delete, test_isolation
- Фаза 1 ✅: multi-org (active_org_id в сесії, /org/list, /org/switch), ліміт 2 org для free, owner видаляє org (cascade + notices), Settings→Організація для всіх ролей, "Змінити організацію" модалка (join+create)
- Superadmin панель ✅: SA.1–SA.7, SA.9–SA.11 (статистика, org/users списки, пошук, suspend/delete org та users, створення users, фільтри)
- Фаза 2.5 ✅: error pages — 403, 404, 500, org suspended, user suspended (з кнопкою "Вийти")
- Фаза 2.2+2.3 ✅: org plan (free/pro), usage limits, progress bars в Settings (ліміти оновлено 13.06 — див. нижче, план тіарів)
- Org picker redesign: картки з аватаром, badge ролі, стрілка
- `users.registered_at` — дата активації акаунту (окремо від created_at)
- **Окрема адмін панель** ✅: `admin.html` + `js/admin.js` на роуті `/admin`, token-based login (`ADMIN_TOKEN` в `.env`), повністю відокремлена від `index.html`
- Фікс timezone-багу: `expires_at` (email_verifications, org_invites) — naive UTC порівнювався з `now()` в сесійній timezone БД (Europe/Kiev), через що 10-хв org-invite токен миттєво "протухав". Фікс: `expires_at > (now() AT TIME ZONE 'utc')`
- `seed_data.py` переписано під PostgreSQL (org-схема, генерує тестові записи для org "obetsa")
- Тести: test_api 16/16 ✅, test_hierarchy 24/24 ✅, test_members 47/47 ✅, test_isolation 45/45 ✅, test_superadmin 16/16 ✅
- Фаза 2.1 (частково) ✅: `organizations.settings JSONB` (`migrate_011_org_settings.sql`) — `default_currency` (EUR/UAH/USD), `GET /org/me` повертає `settings`, `PUT /org/settings` (admin). Нові записи отримують currency з org-дефолту (без select у формі, без конвертації — старі записи не змінюються). UI: Settings → Організація, select валюти (admin); відображення суми/деталей запису тепер показує реальну валюту запису (€/₴/$)
- План-тіари (частково) ✅: `migrate_012_plan_tiers.sql` + `USER_ORG_LIMITS`/`ORG_USAGE_LIMITS`/`get_org_limits()` в api.py — 4 тіари (free/pro/ultimate/zero) для `users.plan` і `organizations.plan`. Залишилось: SA UI (dropdown планів, users.plan), storage-лімит enforcement, динамічний `{max}` org picker — деталі у "Відкриті питання"

Відкладено / наступне: див. Roadmap нижче.

## Відомі баги (TODO)

Немає відкритих.

### Виправлено

| # | Баг | Фікс |
|---|-----|------|
| B.1 | `DELETE /superadmin/users/<id>` падав для власника org (`organizations.owner_id REFERENCES users(id)` без `ON DELETE CASCADE/SET NULL` → FK violation → 500) | Перед видаленням перевіряємо `SELECT name FROM organizations WHERE owner_id=%s` — якщо юзер власник якоїсь org, повертаємо `409 {'error': 'is_org_owner', 'orgs': [...]}` без видалення. У `js/admin.js` модалка видалення показує назву(и) org замість generic помилки |
| B.2 | `/admin` пускав без `ADMIN_TOKEN`, якщо вже була сесія superadmin (`require_superadmin()` приймав `admin_auth` АБО `is_superadmin`-сесію) | `require_superadmin()` тепер вимагає І `admin_auth` (токен), І `is_superadmin`-сесію (AND). `/admin/login` додатково перевіряє що поточний юзер залогінений в основному застосунку і має `is_superadmin=true` — інакше `login_required`/`forbidden`. Тепер доступ до `/admin` мають тільки superadmin, залогінений в `index.html` **і** з правильним токеном |

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

### Фаза 1 — Multi-org ✅

| # | Задача | Статус |
|---|--------|--------|
| ✅ 1.1 | `active_org_id` в сесії + `GET /org/list` + `POST /org/switch` | Готово |
| ✅ 1.2 | Settings → Організація для всіх ролей (switcher, join, create) | Готово |
| ✅ 1.3 | Ліміт: max 2 активні org на free акаунт (`users.plan`) | Готово |
| ✅ 1.4 | Owner видаляє org (`DELETE /org/delete`) + `org_deletion_notices` | Готово |
| ✅ 1.5 | "Змінити організацію" — модалка з табами join/create | Готово |
| ⬜ 1.6 | PostgreSQL RLS | Відкладено |

### Superadmin панель

| # | Задача | Статус |
|---|--------|--------|
| ✅ SA.1 | Статистика-картки вгорі (org / users / records / storage) | Готово |
| ✅ SA.2 | Pending юзерів в таблиці org | Готово |
| ✅ SA.3 | Остання активність org | Готово |
| ✅ SA.4 | Storage per org (МБ) | Готово |
| ✅ SA.5 | Заблокувати/розблокувати org (`is_suspended`) | Готово |
| ✅ SA.6 | Видалити org з підтвердженням | Готово |
| ✅ SA.7 | Пошук по назві org або email адміна | Готово |
| ✅ SA.8 | Змінити план org (free → pro) — toggle кнопка в рядку org | Готово |
| ✅ SA.9 | Список всіх користувачів (email, ім'я, org(и), статус, дата реєстрації) | Готово |
| ✅ SA.10 | Створити користувача від SA (invite link або пароль одразу, без org) | Готово |
| ✅ SA.11 | Фільтри + сортування в списку користувачів (пошук, статус, дата) | Готово |

### Фаза 2 — Tenant features

| # | Задача | Деталі |
|---|--------|--------|
| ✅ 2.1 | Tenant settings | `organizations.settings JSONB` — `default_currency` (EUR/UAH/USD) зроблено; "назва в листах" відкладено (не зрозуміло навіщо окремо від `organizations.name`) |
| ✅ 2.2 | Usage limits (Free tier) | 3 члени / 100 записів / 5 компаній |
| ✅ 2.3 | `plan` колонка на org | `free` / `pro` |

### Фаза 2.5 — Error pages ✅

| # | Сторінка | Статус |
|---|----------|--------|
| ✅ E.1 | 403 — Немає доступу | Готово |
| ✅ E.2 | Org suspended — "Організацію заблоковано" | Готово |
| ✅ E.3 | 404 — Не знайдено | Готово |
| ✅ E.4 | 500 — Помилка сервера | Готово |
| ✅ E.5 | User suspended — "Акаунт заблоковано" + кнопка Вийти | Готово |

`showErrorPage(type)` у `app.js` — замінює main-контент, іконка + текст + кнопка.

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

---

## Модуль «Приватні фінанси» (окремий, майбутній)

> ⚠️ Це окремий модуль — не перетинається з поточною системою відшкодувань. Розробка починається тільки після уточнення з клієнтом.

ТЗ отримано (файл: `docs/TZ Privatni Finansy.docx`). Суть: повноцінний особистий фінансовий трекер.

**Розділи модуля:** Dashboard · Банківські рахунки · Транзакції · Готівка · Мені винні · Я винен · Інвестиції · Місячні звіти · Графіки · Налаштування

**Потенційна точка інтеграції** (вирішити пізніше): розділ "Мені винні" може підтягувати дані з існуючого модуля витрат (`records.to_return/returned/remainder`) — але тільки якщо клієнт підтвердить.

**Питання до клієнта перед стартом:**
1. Які банки потрібна інтеграція? (ПриватБанк, Monobank, Revolut, інші?)
2. Які інвестиційні платформи/брокери?
3. Пріоритет — спочатку ручний ввід, потім API — чи одразу з інтеграціями?
4. Цей модуль для тих самих юзерів/org що і поточна система?

**Статус:** очікуємо уточнення від клієнта.

---

### Відкриті питання

> ⚠️ Ці питання не закриті — повернутись до них перед деплоєм або при появі відповідного контексту.

**Шлях файлів: org_id vs org_name**
Зараз: `ReceiptsManager/{org_id}/...` — унікально, але нечитабельно.
Альтернатива: `ReceiptsManager/{org_name}/...` — читабельно, але потрібні умови:
1. `organizations.name` — UNIQUE constraint (заборонити однакові назви)
2. Перейменування org — заборонено super admin, дозволено тільки org-admin своєї org

Якщо обидві умови виконані → назва стабільна як id, можна перейти на org_name в шляхах.
Рішення відкладено. Поточний код використовує org_id.

**"Вийти з організації" для manager/user — поведінка під питанням**
Зараз кнопка "Вийти" для non-admin робить soft-leave (left_at = now()) — та сама операція що і "Виключити" від адміна.
Проблема: юзер/менеджер може сам себе виключити, обходячи контроль адміна.
Варіанти для обговорення:
- Повністю прибрати кнопку (тільки адмін може виключати)
- Замінити на "Запит на вихід" → адмін підтверджує
- Залишити як є (юзер відповідальний за свої дії)

**Валюта в записах — вирішено (12.06.2026)**
`organizations.settings.default_currency` (EUR/UAH/USD, дефолт EUR), встановлює org-admin в Settings → Організація. Нові записи отримують цю валюту автоматично, без select у формі. **Конвертації немає** — старі записи зберігають свою валюту, суми не перераховуються при зміні org-валюти. Якщо знадобиться реальна конвертація (курси, перерахунок) — окрема велика фіча, не планується.

**Google Drive — перевірити перед підключенням**
Drive sync вимкнено (`DRIVE_ENABLED = False`). Перед увімкненням:
1. Перевірити які OAuth scopes зараз є в Google Console
2. Переглянути всі `/drive/*` та `/sync/*` роути в `api.py`
3. Врахувати нову multi-tenant структуру папок (зараз `ReceiptsManager/{org_id}/...`)
4. Drive папки теж мають бути ізольовані по org

**Бізнес-модель free/pro — вирішено (13.06.2026)**

Гібрид: два окремих поля плану, кожне зі своєю роллю. Без терміну дії (без `plan_expires_at`) — підписка діє доки SA не змінить план вручну; періоди (місяць/рік) — окрема фіча на майбутнє.

`users.plan` — скільки організацій може мати юзер:

| plan | ліміт org |
|---|---|
| free | 1 |
| pro | 3 |
| ultimate | 10 |
| zero (SA-only, прихований) | без ліміту |

`organizations.plan` — ліміти ресурсів всередині org:

| plan | members | records | companies | storage |
|---|---|---|---|---|
| free | 9 | 100 | 5 | 300 MB |
| pro | 24 | 500 | 20 | 1 GB |
| ultimate | 99 | 1000 | 50 | 5 GB |
| zero (SA-only, прихований) | без ліміту | без ліміту | без ліміту | без ліміту |

`zero` — невидимий план, ставить тільки SA вручну (напр. для тестових/VIP акаунтів). SA може встановити будь-який план будь-якому юзеру/org без обмежень.

Реалізація (api.py): `USER_ORG_LIMITS`, `ORG_USAGE_LIMITS`, `check_org_limit()`, `check_free_limit()`, `get_org_limits()`. `migrations/migrate_012_plan_tiers.sql` — існуючі юзери з невалідним `plan` (стара `'premium'` тощо) → `pro`.

SA UI ✅: dropdown 4 плани (free/pro/ultimate/zero) для org (`/superadmin/orgs/<id>/set-plan`, було toggle free/pro) і для users.plan (новий `/superadmin/users/<id>/set-plan`) — `js/admin.js` (`_planSelect`, `superadminSetOrgPlan`, `superadminSetUserPlan`), нова колонка "Plan" у списку users. Тести: `test_superadmin.py` 22/22 ✅.

Залишилось (наступні кроки):
- Storage-лімит (`storage_mb`) — поки не enforced при завантаженні файлів
- Org picker: текст лімітів org (`{max}`) хардкоджений як 2 — зробити динамічним за `USER_ORG_LIMITS`

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
