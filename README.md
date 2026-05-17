# BizDentistry Directory

UK dental practice listings directory for [bizdentistry.com](https://www.bizdentistry.com).

## Services

| Service | Purpose | Login |
|---|---|---|
| **Supabase** | PostgreSQL database | supabase.com |
| **Railway** | FastAPI backend + cron scraper | railway.app |
| **Netlify** | Frontend HTML widget hosting | netlify.com |
| **cron-job.org** | Railway warm-up ping | cron-job.org |

---

## Day-to-day operations (non-technical)

All admin operations use the **Supabase Table Editor** — no code required.

### Activate / deactivate a broker
1. Open Supabase → Table Editor → `agents`
2. Find the broker row
3. Toggle `is_active` between `true` (visible) and `false` (hidden)
4. Changes take effect immediately — no deploy needed

### Feature a specific listing
1. Open Supabase → Table Editor → `listings`
2. Find the listing (filter by `agent_id` or `title`)
3. Set `is_featured = true`
4. The listing will move to the top of the directory on the next page load

### Set a broker's max listings
1. Open `agents` table
2. Update `max_listings` for the broker
3. The cap is applied in the API — no scraper restart needed

### View scraper run history
- Open `scraper_runs` table → sort by `run_at` descending
- `listings_found = 0` with an `error_message` means the scraper failed for that agent
- Normal runs show `listings_found > 0`, `error_message = null`

### Manually trigger a scrape (curl)
```bash
curl -X POST https://YOUR-APP.up.railway.app/admin/scrape/christie \
  -H "X-Admin-Password: your-admin-password"
```
Replace `christie` with `dental-elite` or `lily-head` as needed.

### Trigger all scrapers at once
```bash
curl -X POST https://YOUR-APP.up.railway.app/admin/scrape-all \
  -H "X-Admin-Password: your-admin-password"
```

---

## Developer setup

```bash
# 1. Clone the repo
git clone https://github.com/your-org/bizdentistry-directory.git
cd bizdentistry-directory

# 2. Create a Python virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env with your Supabase keys and admin password

# 5. Run the schema in Supabase SQL editor
# (copy-paste supabase/schema.sql into Supabase SQL editor)

# 6. Run the API locally
uvicorn backend.main:app --reload

# 7. Run a single scraper manually
python -m backend.scrapers.run_scrapers --agent=christie
```

---

## Deployment

### Railway (backend)
1. Connect the GitHub repo to Railway
2. Set environment variables in Railway dashboard (copy from `.env`)
3. Railway auto-deploys on every push to `main`
4. Set up the daily cron: `0 6 * * *` → `python -m backend.scrapers.run_scrapers`

### Netlify (frontend)
1. Connect the GitHub repo to Netlify
2. Set publish directory to `frontend`
3. No build command (static file)
4. Netlify auto-deploys on every push to `main`

### Update the API URL in the frontend
After Railway deploys, copy your Railway public URL and update this line in `frontend/index.html`:
```js
const API_BASE = "https://YOUR-APP.up.railway.app";
```

### Wix embed
1. In Wix Editor, add **Embed Code** widget to the page
2. Set src to your Netlify URL (e.g. `https://bizdentistry-directory.netlify.app`)
3. Set height to `900px`, enable scroll
4. Publish the Wix page

---

## What to do if a scraper alert fires

An alert means a scraper run returned fewer listings than the configured minimum.

1. Check `scraper_runs` table in Supabase — look at the `error_message` column
2. If `error_message` is not null → the scraper threw an exception. Check Railway logs.
3. If `error_message` is null but `listings_found` is low → the scraper ran but found fewer listings than expected. The broker's site may have changed its HTML structure.
4. To fix a broken scraper: inspect the broker's live listings page source, update the CSS selectors in the relevant scraper file (`backend/scrapers/christie.py` etc.), push to `main`, Railway redeploys automatically.

---

## Project structure

```
bizdentistry-directory/
  supabase/
    schema.sql          — Full DB schema + RLS policies
  backend/
    main.py             — FastAPI app (public + admin endpoints)
    config.py           — Env vars + scraper thresholds
    database.py         — Supabase clients (anon + service role)
    models.py           — Pydantic response models
    auth.py             — Admin password header check
    scrapers/
      base.py           — BaseScraper (shared logic, monitoring, upsert)
      christie.py       — Christie & Co
      dental_elite.py   — Dental Elite
      lily_head.py      — Lily Head
      run_scrapers.py   — Orchestrator (CLI + API trigger)
  frontend/
    index.html          — Embeddable directory widget (Netlify)
  requirements.txt
  Procfile
  .env.example
  README.md
```
