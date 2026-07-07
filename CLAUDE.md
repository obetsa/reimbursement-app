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
  config.js                        # конфіг (APP_MODE)
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
  migrate_010_org_plan.sql         # organizations.plan
  migrate_011_org_settings.sql     # organizations.settings JSONB (default_currency)
  migrate_012_plan_tiers.sql       # план-тіари free/pro/ultimate/zero
  migrate_013_payments.sql         # payments — архітектура оплат (Фаза 3, Крок 1)
  migrate_014_org_name_unique.sql  # organizations.name UNIQUE (case-insensitive)
  migrate_015_token_type.sql       # тип токена (email_verifications)
  migrate_016_org_invites_member_companies.sql # org_invites, org_member_companies допов.
  migrate_017_fix_org_members_role_check.sql   # CHECK constraint ролей (viewer→manager)
  migrate_018_remove_drive_columns.sql         # drop drive_id/storage_type/refresh_token
  migrate_019_record_author.sql    # records — автор запису
  migrate_020_record_payer.sql     # records — платник (окремо від автора)
  migrate_021_company_expenses.sql # company_expenses — витрати між компаніями
  migrate_022_cexp_entered_by.sql  # company_expenses.entered_by
  migrate_023_cexp_status.sql      # company_expenses.status + returned_amount
  migrate_024_cexp_soft_delete.sql # company_expenses.is_deleted + deleted_at
tests/
  test_api.py                      # базові API тести (16/16)
  test_hierarchy.py                # тести ієрархії org (22/24)
  test_members.py                  # тести member management (47/47)
  test_isolation.py                # ізоляція org (45/45)
  test_superadmin.py               # SA: delete org + deletion notices (11/11)
  test_billing.py                  # payments table + apply_plan_payment (21/21)
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

company_expenses              — витрати між компаніями (хто оплатив ≠ для кого = внутрішній борг)
├── → organizations.id
├── → companies.id (paying_company_id, beneficiary_company_id)
├── → users.id (entered_by, created_by, updated_by)
├── status: waiting | partial | done
└── is_deleted BOOLEAN / deleted_at TIMESTAMP — soft delete (корзина)

unprocessed_imports            — таблиця лишилась в схемі, але неактивна (Drive-функціонал видалено 30.06.2026)
└── → users.id
```

## Ролі в організації

| Роль      | Права                                        |
|-----------|----------------------------------------------|
| `admin`   | все: члени, компанії, всі записи             |
| `manager` | свої записи + компанії, які має доступ       |
| `user`    | тільки перегляд (viewer)                     |

## Поточний стан (станом на 05.07.2026)

**Гілка `company-expenses`** — активна розробка (ще не змержена в `main`). Кілька довгих feature-гілок (`company-expenses`, `release-3-design`, `web`, `app-sqlite`) — свідомий підхід до версійності, не потребує зведення в одну гілку без окремого прохання.

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
- План-тіари ✅: `migrate_012_plan_tiers.sql` + `USER_ORG_LIMITS`/`ORG_USAGE_LIMITS`/`get_org_limits()`/`get_org_usage()`/`get_org_storage_mb()` в api.py — 4 тіари (free/pro/ultimate/zero) для `users.plan` і `organizations.plan`. SA UI: dropdown планів для org і users. Storage-лімит enforced при завантаженні файлів (+ фікс SA.4 storage path). Org picker: динамічний `{max}` через `/auth/me.org_limit`. Деталі у "Відкриті питання" → "Бізнес-модель free/pro"
- Фаза 3, Крок 1+2 ✅ (Монетизація): таблиця `payments`, `PAYMENT_PROVIDER=None`, `apply_plan_payment()`, `/billing/checkout` + `/billing/webhook/<provider>` (стаби 503). UI: Settings → "💳 Тариф" — `GET /billing/plans` віддає тіри free/pro/ultimate, дві секції (свій план юзера + план org), кнопки "Перейти на PRO/ULTIMATE" → checkout (зараз тост "недоступно"). Тести: test_billing 21/21 ✅
- "Вийти з організації" (manager/user) ✅: підтвердження паролем перед leave (модалка замість `confirm()`). `/auth/me` повертає `has_password` (`false` для Google OAuth юзерів — `password_hash='GOOGLE_AUTH'`); для них крок з паролем пропускається. `POST /org/leave` приймає `{password}`, перевіряє SHA256 проти `users.password_hash`, 403 `invalid_password` при невірному. i18n: `org.leave_title/leave_password_placeholder/leave_wrong_password`
- `org.limit_create_hint` — прибрано хардкод "2" ("більше організацій" замість "більше 2 організацій") у uk/de/en, бо ліміт залежить від плану
- Ліміт org для non-admin ролей ✅ (15.06.2026, варіант B): `check_org_limit(user_id, conn, role='admin')` рахує тільки org де юзер `admin` — `users.plan` обмежує лише кількість org-admin, а не загальну кількість org-членства. `/org/join` і invite manager/user — без ліміту. Frontend: `adminOrgCount`, i18n `org.limit_info` → "Ви адмін у {used} з {max} організацій". Деталі у "Відкриті питання"
- `organizations.name` unique + rename ✅ (15.06.2026, кроки 1-3 з "Шлях файлів: org_id vs org_name"): `migrate_014_org_name_unique.sql` — унікальний індекс по `lower(name)`. `/org/create` тепер також перевіряє унікальність (409 `org_name_taken`). Новий `PUT /org/rename` — тільки org-admin (`require_org(min_role='admin')`), case-insensitive перевірка дублікату (виключаючи себе). UI: Settings → Організація → рядок "Назва організації" з кнопкою "Перейменувати" (тільки admin) → модалка з полем назви. i18n: `org.name_label/rename_btn/rename_title/rename_success` (uk/de/en), помилка дубліката через існуючий `superadmin.err_name_taken`. Кроки 4-5 (модалка міграції файлів, перехід на org_name шляхи) — наступний реліз, деталі у "Відкриті питання"
- SA.12 ✅ (15.06.2026): клік на назву org у списку `/admin` → модалка зі списком всіх активних членів org (email, ім'я, роль, статус). Новий ендпоінт `GET /superadmin/orgs/<org_id>/members` (за зразком `/org/members`, тільки активні — `left_at IS NULL`). `js/admin.js`: `openOrgMembersModal(orgId, orgName)`, назва org у таблиці/картках стала клікабельною. i18n: `superadmin.org_members_title/no_org_members` (uk/de/en), решта (ролі, статуси, колонки) — існуючі ключі. test_superadmin 22/22 ✅
- Google OAuth login узгоджено з закритою реєстрацією ✅ (15.06.2026): `/auth/google` + `/auth/callback` вже існували (з гілки `web`, кнопка "Увійти через Google" в `index.html`), але `/auth/callback` створював нового юзера для будь-якого Google-акаунту — обхід `registration_closed`. Фікс у `/auth/callback`: невідомий email → редірект `/?google_error=registration_closed` (без створення юзера); `is_suspended` (не-SA) → `/?google_error=user_suspended`; `password_hash='PENDING'` (запрошений, не активований) → перший Google-логін = активація (`email_verified=TRUE, registered_at=now()`, мірор `/auth/activate`). Frontend: `js/app.js` ловить `?google_error=...`, показує тост (`auth.err_google_registration_closed` uk/de/en, для suspended — існуючий `error.user_suspended_desc`)
- Доступ до компаній з модалки "Компанії" ✅ (16.06.2026): у Settings → Компанії, при редагуванні або створенні компанії, в модалці тепер є секція "Доступ користувачів" — чіпи всіх не-admin членів org (manager/user, активні), клік перемикає `org_member_companies` (той самий механізм, що в Settings → Організація). Новий ендпоінт `GET /companies/<id>/access` (admin-only, повертає `user_id[]`). Для нової компанії: після "Зберегти" модалка лишається відкритою, заголовок змінюється на "Редагувати компанію", кнопка "Скасувати" → "Закрити", з'являється секція доступу (порожня, бо `org_member_companies` ще немає записів для нового `company_id`). i18n: `form.close`, `company.access_label`, `company.access_empty` (uk/de/en). Попутно виправлено баг (3 місця: `create_company`, `org_member_invite`, `create_record`) — `conn.close()` викликався ДО `get_org_limits(org_id, conn)` у гілці `limit_reached`, через що замість `403` повертався `500 psycopg2.InterfaceError: connection already closed`
- Пагінація ✅ (16.06.2026): "Документи" (`index.html`) і SA-панель (org/users у `/admin`) — десктоп: Prev/Next + "Сторінка X з Y" (`DOCS_PAGE_SIZE`/`SA_PAGE_SIZE = 20`, client-side slice вже отриманих масивів `filteredDocs`/`_saOrgs`/`_saUsers`); мобільний (≤768px): кнопка "Показати ще" (load more, +20). Новий блок стилів `.pagination-bar/.pagination-btn/.pagination-info/.pagination-load-more` (css/components.css). i18n: `pagination.page_of/prev/next/show_more` (uk/de/en). Сторінка скидається на 1 при зміні фільтра/сортування. Перевірено headless Chrome (десктоп 1280x900 і мобільний 390x844, мок-дані 25-45 записів) + test_isolation 36/37 (1 попередження — незмінний skip без SA-сесії)
- Google Drive sync ✅ видалено повністю (30.06.2026): весь `/drive/*`, `/sync/*`, `/unprocessed/*` код з бекенду і фронтенду, `DRIVE_ENABLED`, Drive UI, i18n `drive.*/sync.*/unprocessed.*`. Стара гілка `feature/google-drive-sync` збережена в git на випадок повернення. `migrate_017` (fix org_members role CHECK), `migrate_018` (drop drive_id/storage_type/refresh_token). Google OAuth login (без sync) лишився і працює окремо
- Автор/платник записів, дашборд платників ✅: `records` — окремі `author`/`payer` (`migrate_019`, `migrate_020`), дашборд-віджет топ-платників, поділ платіжних інструментів
- **Модуль «Витрати по компаніях» + «Розрахунки між компаніями»** ✅ (01.07–05.07.2026, гілка `company-expenses`, не змержена в `main`): нова таблиця `company_expenses` (`migrate_021`, +`entered_by` в `migrate_022`, +`status`/`returned_amount` в `migrate_023`, +soft delete в `migrate_024`) — витрата = хто оплатив (компанія) + для кого (компанія); розбіжність = внутрішній борг. Сторінка "Витрати по компаніях": таблиця/картки (мобільний дефолт — картки, як в документах), пошук + фільтри (оплатив/для кого/статус) + сортування, статус погашення (waiting/partial/done). Сторінка "Розрахунки між компаніями" (`GET /company-settlements`): net-баланс між парами компаній, drill-down картка компанії (кому винна / хто винен їй) через `openSettleCompanyModal`. Дашборд-віджет: топ-5 відкритих боргів (`loadDashSettlements`). Nav badge-каунти в сайдбарі. Роль-фільтр: `_get_accessible_company_ids()` — manager/user бачать тільки записи де хоч одна компанія в їх `org_member_companies`, admin — всі. Soft delete: корзина з двома блоками (документи + витрати по компаніях), `PUT /company-expenses/<id>/restore`, `DELETE /company-expenses/<id>/permanent`. Мобільна адаптація (05.07): `_cexpView`/`cexpSetView()` форсують `cards` на ≤768px (той самий патерн, що й `currentView`/`setView()` в документах); картки `#settle-table-wrap` на мобільному з підписами `.settle-mobile-label` (щоб цифри не висіли без контексту після приховування `<thead>`)
- Сайдбар — секція "Записи" ✅ (05.07.2026): Dashboard відокремлено розділювачем від решти; "Документи" + "Галерея чеків" згруповані під новим заголовком-секцією `nav.section_records` ("Записи"/"Records"/"Einträge"), за зразком "Витрати"/"Розрахунки". Корзина (перенесена раніше, 05.07) лишається після "Розрахунків між компаніями", перед "Налаштування"
- Company-expenses — перегляд/редагування записів ✅ (05.07.2026): клік по рядку таблиці або картці відкриває `openCexpModal(id)` — для admin/manager це звичайне редагування; для `user` (view-only) той самий модал, але всі поля `disabled`, кнопка "Зберегти" схована, "Скасувати" → "Закрити" (заголовок "Перегляд витрати", i18n `cexp.modal_title_view`). Окремої "🗑️ Видалити" в перегляді немає — свідомо (не мала сенсу для view-only ролі)
- Company-expenses — чіткіші підписи фільтрів ✅ (05.07.2026): дропдауни в панелі фільтрів тепер "Хто оплатив" / "Для кого" (`cexp.filter_paying_placeholder/filter_bene_placeholder`) замість однакового "Всі компанії" на обох — залишаються **однонапрямковим** AND-фільтром (paying=X І beneficiary=Y), без бідирекційної логіки
- Company-settlements → company-expenses "pair filter" ✅ (05.07.2026): клік на число в колонці "Записів" (`_settleRender`) відкриває "Витрати по компаніях" з банером `#cexp-pair-banner` ("Показано лише: Компанія А ↔ Компанія Б" + "✕ Показати всі") — показує **всі** записи між цими двома компаніями в обидва напрямки (`_cexpPairFilter`, окремий від дропдаунів "Хто оплатив"/"Для кого" механізм). Банер ховається при ручній зміні пошуку/фільтра/статусу (`cexpUserFilterChanged()`) або переході на сторінку заново
- Company-settlements — фільтри "Хто винен" / "Кому винен" ✅ (05.07.2026): два нових дропдауни (`settle-filter-debtor`/`settle-filter-creditor`, i18n `settle.filter_debtor/filter_creditor`) поруч з існуючим "Всі компанії" — directional AND-фільтр по `debtor_id`/`creditor_id`
- Компанії — доступ, сортування, is_active фільтри ✅ (07.07.2026): 1) `create_company` тепер грантить manager-творцю доступ до щойно створеної компанії (`org_member_companies`) — раніше сам її не бачив; 2) `GET /companies` сортує по `created_at` замість `sort_order, name` (дублікати sort_order давали хаотичний порядок); 3) дропдауни компаній в cexp (`_cexpPopulateCompanySelects`, `_cexpPopulateFilterSelects`) і settlements (`_settlePopulateFilter`) тепер фільтрують `is_active`, як і форма документів. SA-панель: додано `total_companies` в `/superadmin/stats` + картка. i18n: `settle.net_badge` (uk) "Нетований" → "Нетто"

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
| ✅ SA.12 | Клік на org у списку → модалка зі списком всіх користувачів цієї org | Готово |

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
| ✅ 3.0 | Архітектура оплат (без провайдера) | `migrations/migrate_013_payments.sql` — таблиця `payments`; `PAYMENT_PROVIDER = None` (флаг як `DRIVE_ENABLED`); `apply_plan_payment()`; `POST /billing/checkout` і `POST /billing/webhook/<provider>` — стаби, 503 поки провайдер не підключений. Тести: `tests/test_billing.py` 21/21 ✅ |
| ✅ 3.2 | Billing сторінка в settings | Новий таб Settings → "💳 Тариф" (`settings.billing`, окремо від `settings.payments` = платіжні інструменти). `GET /billing/plans` — публічні (не-zero) тіри `USER_ORG_LIMITS`/`ORG_USAGE_LIMITS`. Дві секції: "Ваш тариф" (ліміт org для юзера) і "Тариф організації" (members/records/companies/storage, видно всім, кнопки тільки admin). Кнопки "Перейти на PRO/ULTIMATE" → `/billing/checkout` (зараз 503 → тост `billing.unavailable`) |
| 3.1 | Stripe або LiqPay | Підключити провайдера (ключі, checkout-сесія, перевірка підпису вебхука) |
| 3.3 | Plan upgrade flow | Один платіж = план назавжди (без `plan_expires_at`); `valid_until` в `payments` підготовлено під майбутні періоди |

### Company Expenses модуль ✅ (гілка `company-expenses`, не змержена в `main`)

| # | Задача | Статус |
|---|--------|--------|
| ✅ 1 | `company_expenses` таблиця + CRUD, таблиця/картки, пошук/фільтри/сортування | Готово |
| ✅ 2 | Статус погашення (waiting/partial/done) + returned_amount | Готово |
| ✅ 3 | "Розрахунки між компаніями" — net-баланс, `/company-settlements` | Готово |
| ✅ 4 | Drill-down картка компанії (кому винна / хто винен їй) | Готово |
| ✅ 5 | Дашборд-віджет — топ-5 відкритих боргів | Готово |
| ✅ 6 | Роль-фільтр (manager/user — тільки доступні компанії) | Готово |
| ✅ 7 | Soft delete + корзина (2 блоки: документи + cexp) | Готово |
| ✅ 8 | Мобільна адаптація (cards-дефолт, підписи на settle-картках) | Готово |

### Суміжно

| Задача | Коли |
|--------|------|
| Supabase cloud | Після Фази 0, перед деплоєм (відкладено на наступний реліз) |
| ✅ Google OAuth login узгоджено з закритою реєстрацією | Готово (15.06.2026) — `/auth/callback` тепер: невідомий email → `registration_closed` (без створення юзера), `is_suspended` → `user_suspended`, `password_hash='PENDING'` → активація (мірор `/auth/activate`) |

### Наступні кроки

> Порядок виконання, тільки коли користувач сам скаже почати.

1. **OWASP ZAP scan** — перед першим публічним деплоєм (`zap.yaml` в корені — підготовка)
2. **Hypothesis tests** — property-based тести для критичної логіки (org isolation, ролі, ліміти)
3. **Відновити пароль** — flow "Забули пароль?" прихований (`display:none` у `index.html`). Потребує: SMTP-шаблон листа, `/auth/forgot-password` і `/auth/reset-password` ендпоінти, токен з TTL у `email_verifications`. Показати кнопку після реалізації.
4. **Portainer** — Recreate + Re-pull, накатити міграції 021-024 (company_expenses) — не терміново, робити коли скаже користувач
5. **Merge `company-expenses` в `main`** — тільки коли скаже користувач; кілька довгих feature-гілок — це нормальний робочий підхід, не проблема, яку треба вирішувати самостійно

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

**Остаточне видалення компанії — показувати "(видалено) Назва" замість "—" (07.07.2026, ідея, не реалізовано)**
Зараз: `permanent_delete_company` фізично видаляє рядок з `companies`; FK `ON DELETE SET NULL` обнуляє `paying_company_id`/`beneficiary_company_id` в `company_expenses` — назва компанії губиться назавжди, у "Витратах" показується "—".

Ідея: зберігати назву окремо ще до видалення (нові колонки `paying_company_name_snapshot`/`beneficiary_company_name_snapshot` в `company_expenses`, заповнити в `permanent_delete_company` перед тим як БД обнулить id), і показувати "(видалено) Назва" замість "—".

Відкрите питання, яке впливає на дизайн: "Розрахунки між компаніями" зараз повністю **виключають** пару, якщо хоч одна компанія `NULL` (`WHERE ... IS NOT NULL`). Треба вирішити:
- лишити як є (борг з видаленою компанією зникає з розрахунків) — тоді snapshot потрібен тільки для "Витрат"
- або послабити умову і показувати борг з видаленою компанією й там, позначений "(видалено)"

**Статус:** тільки ідея, в план на майбутнє. Не починати без окремого підтвердження користувача.

**Шлях файлів: org_id vs org_name — рішення по кроках (15.06.2026)**
Зараз: `ReceiptsManager/{org_id}/...` — унікально, але нечитабельно. Цей реліз — без змін, org_id лишається.

Кроки 1-3 ✅ (15.06.2026) — підготовчі умови зроблено:
1. ✅ `organizations.name` — UNIQUE constraint (case-insensitive, `migrate_014_org_name_unique.sql`, унікальний індекс по `lower(name)`)
2. ✅ Перейменування org — `PUT /org/rename`, тільки org-admin своєї org (`require_org(min_role='admin')`); SA-панель такої можливості не має
3. ✅ UI: кнопка "Перейменувати" в Settings → Організація (тільки admin), модалка з полем назви

Залишилось на наступний реліз (org_name шлях — сама ідея `ReceiptsManager/{org_name}/...` відкладена):
4. При перейменуванні — модалка з попередженням, що це триватиме якийсь час (іде міграція файлів):
   - на час міграції — погасити всі сесії учасників org
   - модалка адміна залишається відкритою (не дає закрити), поки міграція файлів не завершиться
   - **Поки шляхи на `org_id` — крок 4 не потрібен** (перейменування не зачіпає файли). Стане актуальним тільки разом з кроком 5.
5. Тільки після кроку 4 і коли назва стабільна як id → перехід шляхів на `org_name`

Поточний код використовує org_id. RLS (1.6) — теж наступний реліз.

**Ліміт організацій (`users.plan`) для non-admin ролей — вирішено, реалізовано (15.06.2026)**
Було: напис "X з Y організацій активно. Ліміт досягнуто" показувався в Settings → Організація для всіх ролей, як тільки free-юзер є членом >1 org — навіть якщо в цих org він тільки `user`/`manager`.

Обрано варіант B: `check_org_limit(user_id, conn, role='admin')` тепер приймає роль і одразу повертає `True`, якщо `role != 'admin'`. Для `role='admin'` рахує тільки `org_members WHERE role='admin' AND left_at IS NULL` і порівнює з `USER_ORG_LIMITS[plan]`. Тобто `users.plan` обмежує лише кількість org, де юзер — admin.

Виклики:
- `/org/create` — без змін (дефолт `role='admin'`, бо створення org завжди робить creator admin)
- `/org/join` — `check_org_limit(user_id, conn, role='user')` (приєднання по invite-токену завжди дає роль `user`) → ефективно завжди `True`
- `org_member_invite` (`/org/members/invite`) — `check_org_limit(new_user_id, conn, role=role)`, де `role` — вже валідована `manager`/`user` → ефективно завжди `True`, `invitee_org_limit_reached` більше не виникає для manager/user інвайтів

Frontend (`js/app.js`, `loadOrgMembers`): `adminOrgCount = orgList.filter(o => o.role === 'admin').length`, `atLimit = adminOrgCount >= orgLimit`. i18n `org.limit_info` змінено з "{used} з {max} організацій активно" на "Ви адмін у {used} з {max} організацій" (uk/de/en) — точніше відображає нову семантику.

Теоретична дірка (підвищення non-admin до admin понад ліміт) — не актуальна: `/org/members/<id>/role` дозволяє тільки `new_role in ('manager','user')`, admin-роль ніде не призначається крім `/org/create`.

**Валюта в записах — вирішено (12.06.2026)**
`organizations.settings.default_currency` (EUR/UAH/USD, дефолт EUR), встановлює org-admin в Settings → Організація. Нові записи отримують цю валюту автоматично, без select у формі. **Конвертації немає** — старі записи зберігають свою валюту, суми не перераховуються при зміні org-валюти. Якщо знадобиться реальна конвертація (курси, перерахунок) — окрема велика фіча, не планується.

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
| free | 10 | 100 | 5 | 300 MB |
| pro | 25 | 500 | 20 | 1 GB |
| ultimate | 100 | 1000 | 50 | 5 GB |
| zero (SA-only, прихований) | без ліміту | без ліміту | без ліміту | без ліміту |

`zero` — невидимий план, ставить тільки SA вручну (напр. для тестових/VIP акаунтів). SA може встановити будь-який план будь-якому юзеру/org без обмежень.

Реалізація (api.py): `USER_ORG_LIMITS`, `ORG_USAGE_LIMITS`, `check_org_limit()`, `check_free_limit()`, `get_org_limits()`, `get_org_usage()`, `get_org_storage_mb()`. `migrations/migrate_012_plan_tiers.sql` — існуючі юзери з невалідним `plan` (стара `'premium'` тощо) → `pro`.

SA UI ✅: dropdown 4 плани (free/pro/ultimate/zero) для org (`/superadmin/orgs/<id>/set-plan`, було toggle free/pro) і для users.plan (новий `/superadmin/users/<id>/set-plan`) — `js/admin.js` (`_planSelect`, `superadminSetOrgPlan`, `superadminSetUserPlan`), нова колонка "Plan" у списку users. Тести: `test_superadmin.py` 22/22 ✅.

Storage-лімит ✅: `get_org_storage_mb(org_id)` рахує реальний розмір `data/uploads/ReceiptsManager/{org_id}` (рекурсивно). Додано в `get_org_usage()` (поле `storage_mb`). `upload_attachment` перевіряє ліміт перед збереженням файлу → 403 `{'error':'limit_reached','resource':'storage','limit':...}` (пропускається для `zero` плану). Заодно виправлено SA.4 — `superadmin_list_orgs` рахував storage по неправильному шляху (`data/{org_id}` замість `data/uploads/ReceiptsManager/{org_id}`), тепер використовує той самий `get_org_storage_mb()`.

Org picker — динамічний `{max}` ✅: `/auth/me` повертає `org_limit` (з `USER_ORG_LIMITS`, `null` для SA/zero). `js/app.js` org-info блок використовує `meData.org_limit` замість хардкодженого `2`; для `null` (SA або zero-план) рядок лімітів не показується.

Frontend ✅: usage-бари в Settings → Організація тепер показують і storage (`limit.label_storage`, бар з `storage_mb`); `limit.section_title` і повідомлення `limit.members/records/companies/storage` генералізовані (прибрано "для безкоштовного плану" — ліміти тепер діють для всіх планів, не лише free). `uploadAttachment` (js/db.js) тепер парсить структуровану помилку (`e.data`), щоб `_errMsg()` міг показати `limit.storage`.

Залишилось: нічого — Крок 3 завершено.

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

Повністю видалено (`4f255b9`, 30.06.2026) — весь `/drive/*`, `/sync/*`, `/unprocessed/*` код, `DRIVE_ENABLED`, Drive UI, i18n-ключі. Стара гілка `feature/google-drive-sync` збережена в git на випадок повернення. Google OAuth login (без sync) лишився і працює окремо.

## Git

- `main` — стабільна версія
- `company-expenses` — поточна активна гілка (модуль розрахунків між компаніями, не змержена)
- `release-3-design` — попередня активна (автор/платник, дашборд платників, фавікон) — закомічено
- `web` — Google OAuth + стара Drive-логіка (історична)
- `app-sqlite` — стара SQLite-версія (історична)

Кілька довгих feature-гілок одночасно — свідомий підхід до версійності. Не пропонувати мерж в `main` без прямого прохання користувача.

Деплой: `docker build` → push на `obetsa/reimbursement-app:latest`. Не пушити в docker/Portainer без прямого прохання користувача.

**Версійність на Docker Hub** (з 07.07.2026): перед перезаписом `latest` — попередній `latest` спершу тегується наступним по порядку `vN` і пушиться окремо (архів), і тільки після цього новий код пушиться як `latest`. Поточні теги: `v1` (30.04) → `v2` (12.05) → `v3` (19.06) → `v4` (30.06) → `v5` (07.07, архів latest до фіксів компаній) → `latest` (07.07, поточний код). Наступний архівний тег — `v6`.
