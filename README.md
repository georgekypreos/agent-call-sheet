# Agent Call Sheet

A Next.js dashboard for daily SREG agent outreach. Pulls people from Follow Up Boss, enriches with Courted production data, and curates a daily call list with progress tracking, buckets, and FUB-synced call logging.

## Stack

- **Next.js 14** (App Router) + **TypeScript**
- **Tailwind CSS** for styling
- **Prisma + SQLite** (local) / **Turso / libSQL** (production on Vercel)
- **Axios** for HTTP to FUB and Courted APIs
- **Vercel Cron** for the daily sync

## Local setup

```bash
# 1. Install deps
npm install

# 2. Configure environment
cp .env.example .env.local
# Edit .env.local with your FUB + Courted API keys

# 3. Initialize the database
npx prisma db push

# 4. Run the dev server
npm run dev
# Open http://localhost:3000

# 5. (Optional) Trigger a sync to pull FUB + Courted data
curl -X POST http://localhost:3000/api/refresh
```

## Deploying to Vercel + Turso

1. Create a [Turso](https://turso.tech) database.
   ```bash
   turso db create agent-call-sheet
   turso db tokens create agent-call-sheet
   ```
2. Push the schema to Turso:
   ```bash
   DATABASE_URL="libsql://your-db.turso.io?authToken=<token>" npx prisma db push
   ```
3. Push the repo to GitHub, import it on Vercel.
4. In Vercel → Project Settings → Environment Variables, add everything from `.env.example`:
   - `DATABASE_URL=libsql://your-db.turso.io`
   - `TURSO_AUTH_TOKEN=<token>`
   - All `FUB_*`, `COURTED_*`, and `CRON_SECRET` values
5. Deploy. The `vercel.json` includes a cron job that triggers `/api/cron/sync` daily at 5 AM UTC.

## Project structure

```
app/
  layout.tsx                Root layout (loads canvas-confetti CDN)
  page.tsx                  Dashboard page
  globals.css               Tailwind + base styles
  api/
    agents/route.ts         GET — top ten / bucket / coops / birthday / anniversary
    called/[fubId]/route.ts POST — toggle "called today" + FUB tag
    bucket/[fubId]/route.ts POST — move agent into a bucket
    skip/[fubId]/route.ts   POST — per-day skip (auto-resets at midnight)
    note/[fubId]/route.ts   POST — add note to FUB
    log-call/[fubId]/route.ts POST — log a Call activity to FUB
    refresh/route.ts        POST — manually trigger sync
    cron/sync/route.ts      GET  — Vercel Cron entrypoint
components/
  Dashboard.tsx             Main React shell — tabs, filters, progress, list
  AgentCard.tsx             One agent card with profile, controls, buttons
  Confetti.ts               CDN-based confetti with fallback
  singleTab.ts              Single-reusable-tab opener (avoids tab pile-up)
  format.ts                 Display helpers (money, dates, initials, trends)
lib/
  config.ts                 Env loader with typed config
  db.ts                     Prisma client (uses libSQL adapter when on Turso)
  fub.ts                    Follow Up Boss API client (axios)
  courted.ts                Courted API client (axios)
  matching.ts               Email/phone normalization, today-match helper
  sync.ts                   FUB pull, Courted enrichment, Coops rotation
  agents.ts                 Main agent query — powers /api/agents
  types.ts                  Shared types (DTOs, tab keys, etc.)
prisma/
  schema.prisma             Database schema (Agent, Bucket, SkipDay, Call, Note, …)
vercel.json                 Cron schedule + function maxDuration
```

## Sync strategy

The full sync (15K FUB contacts + Courted enrichment) won't fit in Vercel's 60-second function timeout in one shot. Three pieces:

1. **`syncFubPeople`** — paginates `/people?stage=Agents&fields=allFields`. Each page is upserted to the `Agent` table. Stops early if it's been running > 50s; next cron run continues.
2. **`syncCourtedEnrichment`** — for agents missing recent Courted data, looks each one up by email. Cached in `CourtedEnrichment` (7-day TTL). Processes 100 per invocation.
3. **`syncCoopsRotation`** — pulls FUB Smart List 21 and stores today's 10-person rotation slice.

`POST /api/refresh` runs all three sequentially with shorter budgets. The daily Vercel Cron job does the same with longer budgets.

## Migrating from the Python version

The Python implementation (`app.py`, `templates/dashboard.html`, `data/*.json`) is still in this folder. Once you've verified the Next.js version works end-to-end against your real FUB + Courted data, you can delete:

```
app.py
csv_mode.py
config.json config.example.json
requirements.txt run.bat run_csv.bat
templates/
data/
.venv/
```

(The `.gitignore` keeps these out of git in the meantime.)

## Key features

- **Top ten tab** — SREG-tagged agents only, rotated 5 most + 5 least transactions per day. Full coverage takes ~99 days at 988 SREG agents.
- **Coops** — FUB Smart List 21 deterministically rotated 10/day.
- **Birthday / Anniversary** — automatic — show agents whose date matches today.
- **Warm / Nurture / Hot** — persistent buckets, one assignment per agent.
- **Skip** — per-day demotion to bottom of list, resets at midnight.
- **Mark called** — tags `called-YYYY-MM-DD` in FUB + logs a Call activity to the FUB timeline + writes to local DB for progress tracking.
- **Filter chips** — Brokerage tags (Green Valley, Signature Real Estate Group, regions) act as sub-filters within the active tab.
- **Single-tab navigation** — FUB and Courted links share one persistent browser tab each.
- **Confetti + affirmations** — celebrate at 100%, encouraging messages along the way.

## Common commands

```bash
npm run dev          # local dev server on :3000
npm run build        # production build (runs prisma generate)
npm run start        # production server
npm run db:push      # push schema changes to the DB
npm run db:studio    # open Prisma Studio to browse data
```
