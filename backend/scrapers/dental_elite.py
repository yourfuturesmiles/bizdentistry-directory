"""
Dental Elite scraper — https://dentalelite.co.uk/practices/

Verification checklist (complete before first run):
  [ ] Confirm whether listings page is server-rendered or JS-rendered.
      Run: curl -s https://dentalelite.co.uk/practices/ | grep -i "practice"
      If listing titles appear in curl output → BeautifulSoup sufficient.
      If the HTML is empty/minimal → Playwright required (see Playwright section below).
  [ ] robots.txt permits scraping /practices/
  [ ] Confirm stable external_id strategy (URL slug or numeric ID)

Playwright fallback:
  If the page is JS-rendered, set USE_PLAYWRIGHT = True below and ensure:
    - `playwright` is in requirements.txt
    - `playwright install chromium` runs in the Railway build command (Procfile)
    - The Railway plan has enough memory for a headless Chromium instance (~200MB)

CSS selectors below are based on Dental Elite's typical listing card structure.
If the scraper returns 0 listings, inspect the live page source and update selectors.
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL  = "https://dentalelite.co.uk/practices/"
USE_PLAYWRIGHT = False  # Set True if JS-rendered (see docstring above)

# ── Selectors — update if Dental Elite restructures their page ─────────────────
LISTING_CARD_SELECTOR = "article.practice, div.practice-card, .listing-item, .property"
TITLE_SELECTOR        = "h2, h3, .practice-name, .listing-title"
LOCATION_SELECTOR     = ".location, .practice-location, .address, .town"
PRICE_SELECTOR        = ".price, .asking-price, .guide-price"
TYPE_SELECTOR         = ".practice-type, .type-badge, [class*='type']"
TENURE_SELECTOR       = ".tenure, [class*='tenure']"
LINK_SELECTOR         = "a[href*='/practices/']"
IMAGE_SELECTOR        = "img.practice-image, img.listing-image, .thumbnail img, img"
HIGHLIGHTS_SELECTOR   = "ul.features li, .key-features li, .highlights li"
EBITDA_SELECTOR       = ".ebitda, [class*='ebitda'], .financials"
TURNOVER_SELECTOR     = ".turnover, [class*='turnover']"
UDA_SELECTOR          = ".uda, [class*='uda']"
# ──────────────────────────────────────────────────────────────────────────────


def _fetch_with_playwright(url: str) -> str:
    """Fetch JS-rendered page using Playwright. Only called if USE_PLAYWRIGHT=True."""
    from playwright.sync_api import sync_playwright
    import time
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"User-Agent": "BizDentistryBot/1.0"})
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)  # Extra wait for any deferred rendering
        html = page.content()
        browser.close()
    return html


class DentalEliteScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="dental-elite",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def fetch_page(self, url: str) -> str:
        if USE_PLAYWRIGHT:
            import time
            time.sleep(2)
            return _fetch_with_playwright(url)
        return super().fetch_page(url)

    def _extract_external_id(self, url: str) -> str | None:
        """
        Extract stable ID from Dental Elite listing URL.
        Verify slug stability: if slugs change on listing edit, use a numeric ID instead.
        e.g. /practices/mixed-practice-birmingham/ → external_id = "mixed-practice-birmingham"
        """
        # Try numeric ID first
        match = re.search(r"/practices/.*?(\d{4,})", url)
        if match:
            return match.group(1)
        # Fall back to full slug (stable for WordPress unless listing is re-saved)
        segments = [s for s in url.rstrip("/").split("/") if s]
        slug = segments[-1] if segments else None
        return slug

    def _extract_listing_url(self, card, base_url: str) -> str | None:
        link_tag = card.select_one(LINK_SELECTOR) or card.find("a", href=True)
        if not link_tag:
            return None
        href = link_tag.get("href", "")
        if href.startswith("http"):
            return href
        return "https://dentalelite.co.uk" + href

    def _extract_text(self, card, selector: str) -> str | None:
        el = card.select_one(selector)
        return el.get_text(strip=True) if el else None

    def _normalise_practice_type(self, raw: str | None) -> str | None:
        if not raw:
            return None
        raw_up = raw.upper()
        if "NHS" in raw_up and "PRIVATE" in raw_up:
            return "Mixed"
        if "NHS" in raw_up:
            return "NHS"
        if "PRIVATE" in raw_up:
            return "Private"
        return raw.strip()

    def _normalise_tenure(self, raw: str | None) -> str | None:
        if not raw:
            return None
        raw_up = raw.upper()
        if "FREEHOLD" in raw_up:
            return "Freehold"
        if "LEASEHOLD" in raw_up:
            return "Leasehold"
        return raw.strip()

    def _extract_surgeries(self, card) -> int | None:
        text = card.get_text()
        match = re.search(r"(\d+)\s*(?:surgery|surgeries|dental chair|chair)", text, re.I)
        return int(match.group(1)) if match else None

    def _extract_ebitda(self, card) -> tuple[str | None, str | None]:
        """Returns (ebitda_associate_led, ebitda_owner_operated)."""
        text = card.get_text()
        assoc = re.search(r"associate[- ]led[^£\d]*([£\d,k]+)", text, re.I)
        owner = re.search(r"owner[- ]operated[^£\d]*([£\d,k]+)", text, re.I)
        assoc_val = assoc.group(1).strip() if assoc else self._extract_text(card, EBITDA_SELECTOR)
        owner_val = owner.group(1).strip() if owner else None
        return assoc_val, owner_val

    def _extract_uda(self, card) -> str | None:
        text = card.get_text()
        match = re.search(r"(\d+(?:\.\d+)?p?)\s*(?:per UDA|UDA value|UDA rate)", text, re.I)
        if match:
            return match.group(1)
        return self._extract_text(card, UDA_SELECTOR)

    def parse_listings(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(LISTING_CARD_SELECTOR)

        if not cards:
            cards = [
                el for el in soup.find_all(["article", "div", "li"])
                if el.find("a", href=re.compile(r"/practices/"))
            ]
            logger.warning(
                "[dental-elite] Primary selector found 0 cards; fallback found %d. "
                "Update LISTING_CARD_SELECTOR or set USE_PLAYWRIGHT=True.",
                len(cards),
            )

        results = []
        for card in cards:
            listing_url = self._extract_listing_url(card, LISTINGS_URL)
            if not listing_url:
                continue

            external_id = self._extract_external_id(listing_url)
            if not external_id:
                continue

            ebitda_assoc, ebitda_owner = self._extract_ebitda(card)

            img_tag   = card.select_one(IMAGE_SELECTOR)
            image_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else None

            highlight_els = card.select(HIGHLIGHTS_SELECTOR)
            highlights    = [el.get_text(strip=True) for el in highlight_els] or None

            results.append({
                "external_id":            external_id,
                "listing_url":            listing_url,
                "title":                  self._extract_text(card, TITLE_SELECTOR),
                "location":               self._extract_text(card, LOCATION_SELECTOR),
                "asking_price":           self._extract_text(card, PRICE_SELECTOR),
                "practice_type":          self._normalise_practice_type(
                                              self._extract_text(card, TYPE_SELECTOR)
                                          ),
                "tenure":                 self._normalise_tenure(
                                              self._extract_text(card, TENURE_SELECTOR)
                                          ),
                "num_surgeries":          self._extract_surgeries(card),
                "turnover":               self._extract_text(card, TURNOVER_SELECTOR),
                "ebitda_associate_led":   ebitda_assoc,
                "ebitda_owner_operated":  ebitda_owner,
                "uda_value":              self._extract_uda(card),
                "image_url":              image_url,
                "highlights":             highlights,
            })

        return results
