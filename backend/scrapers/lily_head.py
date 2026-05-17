"""
Lily Head Dental Practice Sales scraper — https://dentalpracticesales.co.uk/dental-practices/

Verification checklist (complete before first run):
  [x] Server-rendered WordPress site — BeautifulSoup sufficient
  [ ] robots.txt permits scraping /dental-practices/
  [ ] Confirm slug stability: WordPress slugs may change if a listing is re-saved.
      If slugs are unstable, derive external_id from a stable query parameter or
      the WordPress post ID embedded in a data attribute.

Lily Head listings contain rich financial data:
  - Annual Turnover
  - EBITDA (associate-led and owner-operated)
These appear on both the index cards and individual listing pages.
Parse them from the index card if available; otherwise make a second request
to the individual listing page (increases scrape time but improves data quality).

CSS selectors below are based on typical WordPress practice listing themes.
Update selectors after inspecting the live page source.
"""

import re
import logging
from bs4 import BeautifulSoup
from backend.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LISTINGS_URL = "https://dentalpracticesales.co.uk/dental-practices/"

# ── Selectors — update if Lily Head restructures their page ───────────────────
LISTING_CARD_SELECTOR = (
    "article.type-practice, "
    "div.practice-listing, "
    ".listing-card, "
    ".property-item, "
    "article[class*='post']"
)
TITLE_SELECTOR         = "h2.entry-title, h3.entry-title, h2, h3, .practice-name"
LOCATION_SELECTOR      = ".location, .practice-location, .entry-meta .location, .town"
PRICE_SELECTOR         = ".price, .asking-price, [class*='price']"
TYPE_SELECTOR          = ".practice-type, .type, [class*='type'], .category"
TENURE_SELECTOR        = ".tenure, [class*='tenure'], .freehold, .leasehold"
LINK_SELECTOR          = "a.practice-link, h2 > a, h3 > a, a[href*='/dental-practices/']"
IMAGE_SELECTOR         = ".wp-post-image, img.practice-image, .featured-image img, img"
HIGHLIGHTS_SELECTOR    = "ul.practice-highlights li, .key-features li, .highlights li, .features li"
TURNOVER_SELECTOR      = ".turnover, [class*='turnover']"
EBITDA_SELECTOR        = ".ebitda, [class*='ebitda']"
UDA_SELECTOR           = ".uda, [class*='uda']"
SURGERIES_SELECTOR     = ".surgeries, [class*='surge']"
# ──────────────────────────────────────────────────────────────────────────────


class LilyHeadScraper(BaseScraper):
    def __init__(self, max_listings: int = 999):
        super().__init__(
            agent_slug="lily-head",
            listings_url=LISTINGS_URL,
            max_listings=max_listings,
        )

    def _extract_external_id(self, url: str) -> str | None:
        """
        Extract stable ID from Lily Head (WordPress) listing URL.
        Prefer numeric WordPress post ID if embedded in URL or data attribute.
        Fall back to URL slug.
        """
        # WordPress often includes /?p=12345 or ?post_id= in some configurations
        match = re.search(r"[?&]p=(\d+)", url)
        if match:
            return match.group(1)
        # Use URL slug as external_id
        segments = [s for s in url.rstrip("/").split("/") if s]
        return segments[-1] if segments else None

    def _extract_listing_url(self, card) -> str | None:
        link_tag = card.select_one(LINK_SELECTOR) or card.find("a", href=True)
        if not link_tag:
            return None
        href = link_tag.get("href", "")
        if href.startswith("http"):
            return href
        return "https://dentalpracticesales.co.uk" + href

    def _extract_text(self, card, selector: str) -> str | None:
        el = card.select_one(selector)
        return el.get_text(strip=True) if el else None

    def _extract_financial_text(self, text: str, pattern: str) -> str | None:
        """Extract a financial value from raw card text using a regex pattern."""
        match = re.search(pattern, text, re.I | re.S)
        return match.group(1).strip() if match else None

    def _extract_turnover(self, card) -> str | None:
        text = card.get_text()
        # Look for "Turnover: £XXX,XXX" or "Annual Turnover £XXX,XXX"
        val = self._extract_financial_text(
            text, r"(?:annual\s+)?turnover[:\s]+([£\d,k\.]+)"
        )
        if val:
            return val
        return self._extract_text(card, TURNOVER_SELECTOR)

    def _extract_ebitda(self, card) -> tuple[str | None, str | None]:
        text = card.get_text()
        assoc = self._extract_financial_text(
            text, r"(?:ebitda|profit)[^£\d]*associate[- ]led[^£\d]*([£\d,k\.]+)"
        )
        if not assoc:
            assoc = self._extract_financial_text(
                text, r"associate[- ]led[^£\d\n]*([£\d,k\.]+)"
            )
        owner = self._extract_financial_text(
            text, r"(?:ebitda|profit)[^£\d]*owner[- ]operated[^£\d]*([£\d,k\.]+)"
        )
        if not owner:
            owner = self._extract_financial_text(
                text, r"owner[- ]operated[^£\d\n]*([£\d,k\.]+)"
            )
        return assoc, owner

    def _extract_uda(self, card) -> str | None:
        text = card.get_text()
        match = re.search(r"(\d+(?:\.\d+)?p?)\s*(?:per UDA|UDA value|UDA rate)", text, re.I)
        if match:
            return match.group(1)
        return self._extract_text(card, UDA_SELECTOR)

    def _extract_surgeries(self, card) -> int | None:
        text = card.get_text()
        match = re.search(r"(\d+)\s*(?:surgery|surgeries|dental chair|chair)", text, re.I)
        return int(match.group(1)) if match else None

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

    def parse_listings(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(LISTING_CARD_SELECTOR)

        if not cards:
            cards = [
                el for el in soup.find_all(["article", "div"])
                if el.find("a", href=re.compile(r"/dental-practices/"))
            ]
            logger.warning(
                "[lily-head] Primary selector found 0 cards; fallback found %d. "
                "Update LISTING_CARD_SELECTOR.",
                len(cards),
            )

        results = []
        for card in cards:
            listing_url = self._extract_listing_url(card)
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
                "turnover":               self._extract_turnover(card),
                "ebitda_associate_led":   ebitda_assoc,
                "ebitda_owner_operated":  ebitda_owner,
                "uda_value":              self._extract_uda(card),
                "image_url":              image_url,
                "highlights":             highlights,
            })

        return results
