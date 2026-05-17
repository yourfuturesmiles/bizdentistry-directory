# Railway deployment
# Web process: starts the FastAPI API server
web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT

# Cron process: daily scraper — schedule in Railway as "0 6 * * *"
# Railway runs this as a separate cron job, not as a long-running process.
# worker: python -m backend.scrapers.run_scrapers

# If Playwright is needed for Dental Elite, add to build command in Railway settings:
# pip install playwright && playwright install chromium
