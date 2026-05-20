"""
PFM Dental scraper — https://pfmdental.co.uk/practice/

Listing page: /practice/ — server-rendered, all listings visible without JS.
Individual listing URL pattern: /practice/[region-code]-[id]/  e.g. /practice/228-53/

Data available on index page:
  - Location (county)
  - Asking price (practice + optional property)
  - Turnover (with NHS/private/plan split)
  - Principal-led EBITDA (used as ebitda_owner_operated)
  - Associate-led EBITDA (ebitda_associate_led)
  - Number of surgeries / dentists
  - Tenure
  - Status (On Market / Under Offer / Sold)
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL = "https://pfmdental.co.uk/practice/"

CARD_SELECTOR    = "div.practice-item, article.practice, div[class*='practice'], .listing-item"
PRICE_PATTERN    = r"(?:asking\s+)?price[:\s£]*([£\d,]+)"
TURNOVER_PATTERN = r"turnover[:\s£]*([£\d,]+)"
EBITDA_PATTERN   = r"principal(?:\s+led)?\s+ebitda[:\s£]*([£\d,]+)"
ASSOC_PATTERN    = r"associate(?:\s+led)?\s+ebitda[:\s£]*([£\d,]+)"
SURGERY_PATTERN  = r"(\d+)\s*(?:surgery|surgeries|treatment\s+room)"
STATUS_PATTERN   = r"\b(on\s+market|under\s+offer|sold|sstc)\b"


class PFMDentalScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="pfm-dental",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def _get_text(self, el, selector: str) -> str | None:
        found = el.select_one(selector)
        return found.get_text(strip=True) if found else None

    def _regex(self, text: str, pattern: str) -> str | None:
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else None

    def _normalise_type(self, text: str) -> str | None:
        t = text.upper()
        if "NHS" in t and "PRIVATE" in t:
            return "Mixed"
        if "NHS" in t:
            return "NHS"
        if "PRIVATE" in t or "PLAN" in t:
            return "Private"
        return None

    def _normalise_tenure(self, text: str) -> str | None:
        t = text.upper()
        if "FREEHOLD" in t:
            return "Freehold"
        if "LEASEHOLD" in t or "LEASED" in t:
            return "Leasehold"
        return None

    def parse_listings(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        # PFM uses a table or repeated div blocks — try both
        cards = soup.select(CARD_SELECTOR)
        if not cards:
            # Fallback: any element containing a /practice/ link
            cards = [
                el for el in soup.find_all(["div", "tr", "article"])
                if el.find("a", href=re.compile(r"/practice/\d"))
            ]
            if cards:
                logger.warning("[pfm-dental] Used fallback card selector (%d found)", len(cards))

        results = []
        for card in cards:
            link = card.find("a", href=re.compile(r"/practice/\d"))
            if not link:
                continue

            href = link.get("href", "")
            listing_url = href if href.startswith("http") else "https://pfmdental.co.uk" + href

            # Derive stable external_id from URL slug
            slug = listing_url.rstrip("/").split("/")[-1]  # e.g. "228-53"
            external_id = "pfm-" + slug

            raw = card.get_text(" ", strip=True)

            # Skip sold/under-offer
            status_match = re.search(STATUS_PATTERN, raw, re.I)
            if status_match and status_match.group(1).lower() not in ("on market",):
                continue

            # Derive title from location + surgeries + type
            location_el = card.select_one(
                ".location, .county, .region, h2, h3, .practice-title"
            )
            location = location_el.get_text(strip=True) if location_el else ""

            surgeries_match = re.search(SURGERY_PATTERN, raw, re.I)
            num_surgeries = int(surgeries_match.group(1)) if surgeries_match else None

            # Determine practice type from turnover breakdown text
            practice_type = self._normalise_type(raw)

            title_parts = []
            if num_surgeries:
                title_parts.append(f"{num_surgeries}-Surgery")
            if practice_type:
                title_parts.append(practice_type)
            title_parts.append("Practice")
            if location:
                title_parts.append(f"— {location}")
            title = " ".join(title_parts) if title_parts else location or "Dental Practice"

            img_tag = card.select_one("img")
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
                "tenure":                self._normalise_tenure(raw),
                "num_surgeries":         num_surgeries,
                "turnover":              self._regex(raw, TURNOVER_PATTERN),
                "ebitda_owner_operated": self._regex(raw, EBITDA_PATTERN),
                "ebitda_associate_led":  self._regex(raw, ASSOC_PATTERN),
                "uda_value":             None,
                "image_url":             image_url,
                "highlights":            None,
            })

        return results
