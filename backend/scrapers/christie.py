"""
Christie & Co scraper — https://www.christie.com/dental-practices-for-sale/

Verification checklist (complete before first run):
  [x] Server-rendered HTML — BeautifulSoup sufficient (no Playwright needed)
  [ ] robots.txt permits scraping /dental-practices-for-sale/
  [x] Stable external_id: numeric ID extracted from listing URL
      e.g. /dental-practices-for-sale/12345/ → external_id = "12345"

CSS selectors below are based on Christie & Co's typical listing card structure.
If the scraper returns 0 listings, inspect the live page source and update the
selectors. The selectors most likely to change are:
  - LISTING_CARD_SELECTOR  (the repeating card container)
  - TITLE_SELECTOR         (practice name)
  - PRICE_SELECTOR         (asking price text)

Run manually to validate:
  python -m backend.scrapers.run_scrapers --agent=christie
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL = "https://www.christie.com/dental-practices-for-sale/"

# ── Selectors — update if Christie & Co restructures their page ────────────────
LISTING_CARD_SELECTOR = "article.property-card, div.listing-card, li.listing-item"
TITLE_SELECTOR        = "h2, h3, .property-title, .listing-title"
LOCATION_SELECTOR     = ".property-location, .location, .address"
PRICE_SELECTOR        = ".property-price, .asking-price, .price"
TYPE_SELECTOR         = ".property-type, .practice-type"
TENURE_SELECTOR       = ".tenure"
LINK_SELECTOR         = "a[href*='/dental-practices-for-sale/']"
IMAGE_SELECTOR        = "img"
HIGHLIGHTS_SELECTOR   = "ul.highlights li, .key-features li, .property-features li"
# ──────────────────────────────────────────────────────────────────────────────


class ChristieScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="christie",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def _extract_external_id(self, url: str) -> str | None:
        """Extract stable numeric ID from Christie & Co listing URL."""
        # e.g. /dental-practices-for-sale/12345/ or /dental-practices-for-sale/12345
        match = re.search(r"/dental-practices-for-sale/(\d+)/?", url)
        if match:
            return match.group(1)
        # Fallback: use last non-empty path segment
        segments = [s for s in url.rstrip("/").split("/") if s]
        return segments[-1] if segments else None

    def _extract_listing_url(self, card, base_url: str) -> str | None:
        link_tag = card.select_one(LINK_SELECTOR) or card.find("a", href=True)
        if not link_tag:
            return None
        href = link_tag.get("href", "")
        if href.startswith("http"):
            return href
        return "https://www.christie.com" + href

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
        match = re.search(r"(\d+)\s*(?:surgery|surgeries|dental chair)", text, re.I)
        return int(match.group(1)) if match else None

    def parse_listings(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(LISTING_CARD_SELECTOR)

        if not cards:
            # Fallback: try to find any article or div with a dental link
            cards = [
                el for el in soup.find_all(["article", "div", "li"])
                if el.find("a", href=re.compile(r"/dental-practices-for-sale/\d+"))
            ]
            logger.warning(
                "[christie] Primary selector found 0 cards; fallback found %d. "
                "Update LISTING_CARD_SELECTOR if this is consistently low.",
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

            title    = self._extract_text(card, TITLE_SELECTOR)
            location = self._extract_text(card, LOCATION_SELECTOR)
            price    = self._extract_text(card, PRICE_SELECTOR)
            p_type   = self._normalise_practice_type(self._extract_text(card, TYPE_SELECTOR))
            tenure   = self._normalise_tenure(self._extract_text(card, TENURE_SELECTOR))

            img_tag   = card.select_one(IMAGE_SELECTOR)
            image_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else None

            highlight_els = card.select(HIGHLIGHTS_SELECTOR)
            highlights    = [el.get_text(strip=True) for el in highlight_els] or None

            results.append({
                "external_id":   external_id,
                "listing_url":   listing_url,
                "title":         title,
                "location":      location,
                "asking_price":  price,
                "practice_type": p_type,
                "tenure":        tenure,
                "num_surgeries": self._extract_surgeries(card),
                "image_url":     image_url,
                "highlights":    highlights,
                # Christie & Co rarely publishes turnover/EBITDA on listing cards
                "turnover":               None,
                "ebitda_associate_led":   None,
                "ebitda_owner_operated":  None,
                "uda_value":              None,
            })

        return results
