# Reimbursement App

Personal expense and reimbursement tracker with Google Drive integration for receipt storage.

**Stack:** Python · Flask · SQLite · Vanilla JS

---

## What it does

Two main scenarios:
- **Paid privately** (card or cash) → track reimbursement from company
- **Paid with company card** → store the document, no reimbursement needed

---

## Features

- **Expense records** — title, amount, currency, date, company, payment method, notes
- **Reimbursement tracking** — partial returns, remainder, auto-status (pending / partial / done)
- **Receipt attachments** — upload photos and PDFs (up to 5 per record)
- **Google Drive sync** — receipts automatically sync to your own Drive folder (`ReceiptsManager`)
- **Drive import** — drop files into `ReceiptsManager/Unprocessed Imports` on Drive, then assign them to records in the app
- **Gallery** — browse all receipts in one place
- **Archive & trash** — soft delete with restore, separate archive for settled records
- **Export** — XLSX, CSV, PDF with filters and period selection
- **Backup & restore** — back up the full database to Google Drive and restore when needed
- **Settings** — manage companies, payment instruments, theme, accent color
- **Multi-language** — 🇺🇦 Ukrainian · 🇩🇪 German · 🇬🇧 English
- **Mobile-friendly** — responsive UI with landscape orientation support
- **Docker-ready** — single container, data persisted in a named volume

---

## Quick Start (Docker)

1. Create a `.env` file next to `docker-compose.yaml`:

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
SECRET_KEY=some_random_secret_string
REDIRECT_URI=http://localhost:5500/auth/callback
```

2. Run:

```bash
docker-compose up -d
```

3. Open [http://localhost:5500](http://localhost:5500) and sign in with Google.

---

## Local Development

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
python api.py
```

---

## Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project, enable **Google Drive API**
3. Create **OAuth 2.0 credentials** → Web application
4. Add `http://localhost:5500/auth/callback` as an authorized redirect URI
5. Copy Client ID and Secret into your `.env`

---

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `SECRET_KEY` | Flask session secret (use a long random string) |
| `REDIRECT_URI` | OAuth callback URL (default: `http://localhost:5500/auth/callback`) |

---

## Data Storage

| Path | Contents |
|---|---|
| `data/local.db` | SQLite database (all records, users, settings) |
| `data/uploads/` | Uploaded receipt files (structured by year/month/company) |

Both are stored in the `reimbursement-data` Docker volume and excluded from git.
