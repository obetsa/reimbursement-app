# Reimbursement App

Personal expense and reimbursement tracker. Store receipts, invoices, and track reimbursements from your company.

**Stack:** Python · Flask · SQLite · Vanilla JS

---

## What it does

Two main scenarios:
- **Paid privately** (card or cash) → track reimbursement from company
- **Paid with company card** → store the document, no reimbursement needed

---

## What's done

- ✅ Records with attachments (photos, PDF — up to 5 files per record)
- ✅ Reimbursement tracking — partial returns, remainder, auto-status
- ✅ Dashboard — total outstanding, stats by status and company
- ✅ Documents list — table and card view, search, filters, sorting
- ✅ Archive and trash (soft delete + restore)
- ✅ Export — XLSX, CSV, PDF with filters and period selection
- ✅ Settings — payment instruments, companies, theme, accent color
- ✅ Interface languages — 🇺🇦 Ukrainian · 🇩🇪 German · 🇬🇧 English
- ✅ Local storage for attachments (structured by year/month/company)

---

## Planned

- Google Drive integration (OAuth + sync)
- Import Inbox for unprocessed files
- iOS native app

---

## Run with Docker

```bash
docker run -p 5500:5500 -v reimbursement-data:/app/data obetsa/reimbursement-app
```

Or with docker-compose:

```bash
docker-compose up
```

Open: [http://localhost:5500](http://localhost:5500)

Data (database + uploads) is stored in a named volume — persists between container updates.
