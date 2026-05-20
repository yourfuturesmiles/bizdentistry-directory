"""
Frank Taylor & Associates scraper — https://www.ft-associates.com/

Listing index: /buying-a-dental-practice/dental-practices-for-sale/
Individual listing: /dental-practices/[ref-number]/  e.g. /dental-practices/11-52-3485/

Data available:
  - Reference number (used as external_id)
  - Location / region
  - Asking price (sometimes split: practice + freehold)
  - Fee income (annual turnover equivalent)
  - Number of surgeries
  - Tenure (Freehold / Leasehold / Virtual Freehold)
  - Practice type (NHS / Private / Mixed)
  - Availability status (Available / Under Offer)

Note: Some listings are behind a membership wall. Only publicly visible listings
are scraped. Members-only listings return 302 redirects to the registration page.
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL   = "https://www.ft-associates.com/buying-a-dental-practice/dental-practices-for-sale/"
BASE_URL       = "https://www.ft-associates.com"

CARD_SELECTOR  = "div.practice-listing, article.listing, div[class*='listing'], div[class*='practice']"
REF_PATTERN    = r"(?:ref(?:erence)?\.?\s*)(\d{2}-\d{2}-\d{4})"
PRICE_PATTERN  = r"(?:asking\s+)?price[:\s£]*([£\d,]+)"
INCOME_PATTERN = r"(?:fee\s+income|turnover|income)[:\s£]*([£\d,]+)"
SURGERY_PATTERN= r"(\d+)\s*(?:surgery|surgeries)"
STATUS_PATTERN = r"\b(available|under\s+offer|sold)\b"


class FrankTaylorScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="frank-taylor",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def _regex(self, text: str, pattern: str) -> str | None:
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else None

    def _normalise_type(self, text: str) -> str | None:
        t = text.upper()
        if "NHS" in t and "PRIVATE" in t:
            return "Mixed"
        if "NHS" in t:
            return "NHS"
        if "PRIVATE" in t:
            return "Private"
        return None

    def _normalise_tenure(self, text: str) -> str | None:
        t = text.upper()
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
                el for el in soup.find_all(["div", "article", "li"])
                if el.find("a", href=re.compile(r"/dental-practices/\d"))
            ]
            if cards:
                logger.warning("[frank-taylor] Fallback selector used (%d found)", len(cards))

        results = []
        for card in cards:
            link = card.find("a", href=re.compile(r"/dental-practices/"))
            if not link:
                continue

            href = link.get("href", "")
            listing_url = href if href.startswith("http") else BASE_URL + href

            # External ID: use reference number if present, otherwise URL slug
            raw = card.get_text(" ", strip=True)
            ref_match = re.search(REF_PATTERN, raw, re.I)
            external_id = ref_match.group(1) if ref_match else listing_url.rstrip("/").split("/")[-1]

            # Skip under-offer / sold
            status_match = re.search(STATUS_PATTERN, raw, re.I)
            if status_match and "under" in status_match.group(1).lower():
                continue
            if status_match and "sold" in status_match.group(1).lower():
                continue

            location_el = card.select_one(".location, .region, h2, h3, .area")
            location = location_el.get_text(strip=True) if location_el else ""

            surgeries_match = re.search(SURGERY_PATTERN, raw, re.I)
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
                "turnover":              self._regex(raw, INCOME_PATTERN),
                "ebitda_owner_operated": None,
                "ebitda_associate_led":  None,
                "uda_value":             None,
                "image_url":             image_url,
                "highlights":            None,
            })

        return results
