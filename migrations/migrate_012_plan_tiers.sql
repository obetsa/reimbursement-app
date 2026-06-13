-- Plan tiers (узгоджено 13.06.2026): free/pro/ultimate/zero
-- users.plan         — скільки org може мати юзер (free=1, pro=3, ultimate=10, zero=без ліміту, SA-only)
-- organizations.plan — ліміти ресурсів всередині org (members/records/companies/storage)
-- Без терміну дії (без plan_expires_at) — підписка діє доки SA не змінить план вручну.

-- Існуючі users.plan з невалідними значеннями (напр. стара 'premium') -> 'pro'
UPDATE users SET plan = 'pro' WHERE plan IS NOT NULL AND plan NOT IN ('free', 'pro', 'ultimate', 'zero');
