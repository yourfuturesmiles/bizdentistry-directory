import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL      = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")  # Slack or SendGrid webhook; optional

# Minimum listings expected per agent after a healthy scrape.
# Set these after the first successful run establishes a baseline.
# If a run returns fewer than this, an alert is triggered.
MIN_EXPECTED_LISTINGS: dict[str, int] = {
    "christie":     5,
    "dental-elite": 5,
    "lily-head":    3,
}

# Seconds to wait between HTTP requests inside the scraper
SCRAPER_REQUEST_DELAY = 2

# User-agent string for scraper HTTP requests
SCRAPER_USER_AGENT = (
    "BizDentistryBot/1.0 (+https://www.bizdentistry.com; "
    "dental practice directory aggregator; "
    "contact: info@bizdentistry.com)"
)
