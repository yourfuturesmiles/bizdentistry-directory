"""
Henry Schein Dental Practice Sales scraper — https://hsdpracticesales.co.uk/

Listing index: /dental-practices-for-sale/  — uses "Load More" (dynamic), but
first page (~12-15 listings) is server-rendered and sufficient for regular runs.
For full coverage, iterate with ?page=N or use the Load More endpoint if it
returns JSON.

Individual listing: /dental-practices-for-sale/[id]/  e.g. /dental-practices-for-sale/70121/

Note: "Premier Tier" listings are restricted to registered buyers. Only standard
publicly visible listings are scraped — Premier Tier cards are detected by the
presence of the restriction notice and skipped.

Data available:
  - Listing code (used as external_id)
  - Location (county/region)
  - Practice type (Fully Private / Mixed / NHS)
  - Asking price
  - Turnover
  - EBITDA
  - Number of surgeries
  - Tenure
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL   = "https://hsdpracticesales.co.uk/dental-practices-for-sale/"
BASE_URL       = "https://hsdpracticesales.co.uk"

CARD_SELECTOR  = "div.listing-card, article.listing, div[class*='practice-card'], div[class*='listing']"
ID_PATTERN     = r"/dental-practices-for-sale/(\d+)/"
PRICE_PATTERN  = r"(?:asking\s+)?price[:\s£]*([£\d,]+)"
TURNOVER_PAT   = r"turnover[:\s£]*([£\d,]+)"
EBITDA_PAT     = r"ebitda[:\s£]*([£\d,]+)"
SURGERY_PAT    = r"(\d+)\s*(?:surgery|surgeries)"
PREMIER_MARKER = "premier tier"


class HenryScheinScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="henry-schein",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def _regex(self, text: str, pattern: str) -> str | None:
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else None

    def _normalise_type(self, raw: str) -> str | None:
        t = raw.upper()
        if "MIXED" in t:
            return "Mixed"
        if "NHS" in t:
            return "NHS"
        if "PRIVATE" in t:
            return "Private"
        return None

    def _normalise_tenure(self, raw: str) -> str | None:
        t = raw.upper()
        if "FREEHOLD" in t:
            return "Freehold"
        if "LEASEHOLD" in t:
            return "Leasehold"
        return None

    def parse_listings(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select(CARD_SELECTOR)
        if not cards:
            cards = [
                el for el in soup.find_all(["div", "article"])
                if el.find("a", href=re.compile(r"/dental-practices-for-sale/\d"))
            ]
            if cards:
                logger.warning("[henry-schein] Fallback selector (%d found)", len(cards))

        results = []
        for card in cards:
            raw = card.get_text(" ", strip=True)

            # Skip Premier Tier restricted listings
            if PREMIER_MARKER in raw.lower():
                continue

            link = card.find("a", href=re.compile(r"/dental-practices-for-sale/\d"))
            if not link:
                continue

            href = link.get("href", "")
            listing_url = href if href.startswith("http") else BASE_URL + href

            id_match = re.search(ID_PATTERN, listing_url)
            external_id = "hsd-" + id_match.group(1) if id_match else listing_url.rstrip("/").split("/")[-1]

            location_el = card.select_one(".location, .region, .county, h2, h3")
            location = location_el.get_text(strip=True) if location_el else ""

            surgeries_match = re.search(SURGERY_PAT, raw, re.I)
            num_surgeries = int(surgeries_match.group(1)) if surgeries_match else None

            practice_type = self._normalise_type(raw)
            tenure        = self._normalise_tenure(raw)

            title_parts = []
            if num_surgeries:
                title_parts.append(f"{num_surgeries}-Surgery")
            if practice_type:
                title_parts.append(practice_type)
            title_parts.append("Practice")
            if location:
                title_parts.append(f"— {location}")
            title = " ".join(title_parts) or location or "Dental Practice"

            img_tag   = card.select_one("img")
            image_url = None
            if img_tag:
                image_url = img_tag.get("src") or img_tag.get("data-src")

            results.append({
                "external_id":           external_id,
                "listing_url":           listing_url,
                "title":                 title,
                "location":              location,
                "asking_price":          self._regex(raw, PRICE_PATTERN),
                "practice_type":         practice_type,
                "tenure":                tenure,
                "num_surgeries":         num_surgeries,
                "turnover":              self._regex(raw, TURNOVER_PAT),
                "ebitda_owner_operated": self._regex(raw, EBITDA_PAT),
                "ebitda_associate_led":  None,
                "uda_value":             None,
                "image_url":             image_url,
                "highlights":            None,
            })

        return results
