# Static Data Audit — index.html
> Станом на 02.04.2026

Всі місця де в `index.html` є хардкодні дані, які мають бути або динамічними (з JS/БД), або правильно i18n-ізованими. Прибираємо по одному блоку.

---

## Пріоритет 1 — Структурна помилка (критично)

### ~~[S1] Три дублікати "Recent records" секції~~ ✅ DONE

---

## Пріоритет 2 — Мертвий код Supabase

### ~~[S2] Email-confirm screen (Supabase)~~ ✅ DONE
> Видалено. Залишено `<!-- TODO: Google OAuth -->` коментар в auth-screen для майбутньої кнопки.

---

## Пріоритет 3 — Статичні дані дашборду

### ~~[D1] Hero-сума і підпис~~ ✅ DONE
> JS вже рендерив по класу `.dash-hero-amount` / `.dash-hero-sub`. Замінено хардкод на `—`.

### ~~[D2] Значення stat-карток~~ ✅ DONE
> JS вже рендерив по `querySelectorAll('.stat-value')[0..3]`. Замінено `7/3/8/2` на `0`.

---

### ~~[D3] "файлів" — відсутній data-i18n~~ ✅ DONE
> Додано ключ `dash.files` (uk/de/en) в i18n.js, додано `data-i18n` до елементу.

---

### ~~[D4] Хардкодний список компаній в дашборді~~ ✅ DONE
> Очищено. JS в `updateDashboard()` вже рендерив цей блок динамічно.

---

## Пріоритет 4 — Статичні опції в формах (мали бути з БД)

### ~~[F1] Опції `field-card` — хардкодні картки~~ ✅ DONE
> Залишено тільки default option. JS в `populateInstrumentDropdowns()` вже заповнював з БД.

---

### ~~[F2] Опції `field-company` — хардкодні компанії~~ ✅ DONE
> Залишено тільки default option. JS в `populateCompanyDropdowns()` вже заповнював з БД.

---

## Пріоритет 5 — Відсутній data-i18n

### ~~[I1] Навігаційні елементи sidebar~~ ✅ DONE
> Всі текстові вузли огорнуто в `<span data-i18n="...">`. `Google Drive` залишено без перекладу.

### ~~[I2] Sync status "Онлайн"~~ ✅ DONE
> Додано `data-i18n="sidebar.online"` до `#sync-status-text`.

---

### ~~[I3] Екран авторизації без data-i18n~~ ✅ DONE
> `data-i18n` на лого, підзаголовок, tabs, labels. `auth-submit-btn` без data-i18n — JS тепер використовує `t()` в `switchAuthTab` і `handleAuth`.
