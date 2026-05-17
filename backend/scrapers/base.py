import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.config import (
    ALERT_WEBHOOK_URL,
    MIN_EXPECTED_LISTINGS,
    SCRAPER_REQUEST_DELAY,
    SCRAPER_USER_AGENT,
)
from backend.database import service_client

logger = logging.getLogger(__name__)


class ScraperDisabledError(Exception):
    pass


class BaseScraper:
    def __init__(self, agent_slug: str, listings_url: str, max_listings: int = 999):
        self.agent_slug = agent_slug
        self.listings_url = listings_url
        self.max_listings = max_listings
        self.session = self._build_session()
        self._check_robots()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": SCRAPER_USER_AGENT})
        return session

    def _check_robots(self):
        try:
            rp = RobotFileParser()
            robots_url = urljoin(self.listings_url, "/robots.txt")
            rp.set_url(robots_url)
            rp.read()
            if not rp.can_fetch(SCRAPER_USER_AGENT, self.listings_url):
                raise ScraperDisabledError(
                    f"robots.txt disallows scraping {self.listings_url}"
                )
        except ScraperDisabledError:
            raise
        except Exception as e:
            # robots.txt fetch failure is non-fatal — log and continue
            logger.warning("robots.txt check failed for %s: %s", self.agent_slug, e)

    def fetch_page(self, url: str) -> str:
        time.sleep(SCRAPER_REQUEST_DELAY)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text

    def parse_listings(self, html: str) -> list[dict]:
        """Override in each agent scraper. Returns list of listing dicts."""
        raise NotImplementedError

    def compute_hash(self, listing: dict) -> str:
        canonical = "|".join(str(listing.get(f, "") or "") for f in [
            "title", "asking_price", "location", "practice_type", "tenure"
        ])
        return hashlib.md5(canonical.encode()).hexdigest()

    def _get_agent_id(self) -> str:
        result = (
            service_client.table("agents")
            .select("id")
            .eq("slug", self.agent_slug)
            .single()
            .execute()
        )
        return result.data["id"]

    def _enrich_location(self, listing: dict) -> dict:
        """
        Call api.postcodes.io on first ingest to get normalised region + lat/lng.
        Only fires when postcode_area is not yet set.
        Returns listing dict with enrichment fields added.
        """
        location = listing.get("location", "")
        if not location:
            return listing
        try:
            time.sleep(0.5)
            resp = httpx.get(
                "https://api.postcodes.io/postcodes",
                params={"q": location, "limit": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result"):
                    hit = data["result"][0]
                    listing["postcode_area"] = hit.get("outcode", "")[:2]
                    listing["region_normalised"] = hit.get("region", "")
                    listing["latitude"] = hit.get("latitude")
                    listing["longitude"] = hit.get("longitude")
        except Exception as e:
            logger.warning("Postcode enrichment failed for '%s': %s", location, e)
        return listing

    def _append_price_history(self, existing_history: list, new_pence: int | None) -> list:
        if new_pence is None:
            return existing_history
        latest = existing_history[-1]["price_pence"] if existing_history else None
        if new_pence != latest:
            existing_history.append({
                "price_pence": new_pence,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
        return existing_history

    def _parse_price_pence(self, price_str: str | None) -> int | None:
        if not price_str:
            return None
        cleaned = price_str.replace("£", "").replace(",", "").replace(" ", "").strip()
        if cleaned.upper() in ("POA", "PRICEONDAPPLICATION", ""):
            return None
        try:
            return int(float(cleaned) * 100)
        except ValueError:
            return None

    def _upsert_listing(self, agent_id: str, listing: dict) -> str:
        """
        Upserts a single listing. Returns one of: 'new', 'updated', 'unchanged'.
        """
        external_id = listing["external_id"]
        new_hash = self.compute_hash(listing)

        existing = (
            service_client.table("listings")
            .select("id, scrape_hash, asking_price_pence, asking_price_history, postcode_area")
            .eq("agent_id", agent_id)
            .eq("external_id", external_id)
            .execute()
        )

        now = datetime.now(timezone.utc).isoformat()

        if not existing.data:
            # New listing — enrich location on first ingest
            listing = self._enrich_location(listing)
            new_pence = self._parse_price_pence(listing.get("asking_price"))
            listing["asking_price_pence"] = new_pence
            listing["asking_price_history"] = self._append_price_history([], new_pence)
            listing["agent_id"] = agent_id
            listing["scrape_hash"] = new_hash
            listing["scraped_at"] = now
            listing["is_active"] = True
            listing["delisted_at"] = None
            listing["delisted_reason"] = None
            service_client.table("listings").insert(listing).execute()
            return "new"

        row = existing.data[0]

        if row["scrape_hash"] == new_hash:
            # Content unchanged — just update scraped_at timestamp
            service_client.table("listings").update({"scraped_at": now}).eq("id", row["id"]).execute()
            return "unchanged"

        # Content changed — update fields
        new_pence = self._parse_price_pence(listing.get("asking_price"))
        history = self._append_price_history(
            row.get("asking_price_history") or [], new_pence
        )
        update_data = {
            **listing,
            "agent_id": agent_id,
            "scrape_hash": new_hash,
            "scraped_at": now,
            "is_active": True,
            "delisted_at": None,
            "delisted_reason": None,
            "asking_price_pence": new_pence,
            "asking_price_history": history,
        }
        # Preserve postcode enrichment if already done
        if row.get("postcode_area"):
            update_data.pop("postcode_area", None)
            update_data.pop("region_normalised", None)
            update_data.pop("latitude", None)
            update_data.pop("longitude", None)

        service_client.table("listings").update(update_data).eq("id", row["id"]).execute()
        return "updated"

    def _delist_missing(self, agent_id: str, found_external_ids: set[str]) -> int:
        """Mark listings as inactive if they're no longer in the scraped feed."""
        active_rows = (
            service_client.table("listings")
            .select("id, external_id")
            .eq("agent_id", agent_id)
            .eq("is_active", True)
            .execute()
        )
        now = datetime.now(timezone.utc).isoformat()
        delisted = 0
        for row in active_rows.data:
            if row["external_id"] not in found_external_ids:
                service_client.table("listings").update({
                    "is_active": False,
                    "delisted_at": now,
                    "delisted_reason": "withdrawn",
                }).eq("id", row["id"]).execute()
                delisted += 1
        return delisted

    def _write_run(
        self,
        agent_id: str,
        found: int,
        new: int,
        updated: int,
        delisted: int,
        error: str | None,
        duration_ms: int,
    ):
        service_client.table("scraper_runs").insert({
            "agent_id": agent_id,
            "listings_found": found,
            "listings_new": new,
            "listings_updated": updated,
            "listings_delisted": delisted,
            "error_message": error,
            "duration_ms": duration_ms,
        }).execute()

    def _send_alert(self, message: str):
        if not ALERT_WEBHOOK_URL:
            logger.warning("ALERT (no webhook configured): %s", message)
            return
        try:
            httpx.post(
                ALERT_WEBHOOK_URL,
                json={"text": f"⚠️ BizDentistry Scraper Alert\n{message}"},
                timeout=10,
            )
        except Exception as e:
            logger.error("Failed to send alert: %s", e)

    def run(self):
        start = time.monotonic()
        agent_id = self._get_agent_id()
        new_count = updated_count = delisted_count = 0
        error_msg = None
        listings = []

        try:
            logger.info("[%s] Scrape started", self.agent_slug)
            html = self.fetch_page(self.listings_url)
            listings = self.parse_listings(html)
            logger.info("[%s] Found %d listings", self.agent_slug, len(listings))

            found_ids: set[str] = set()
            for listing in listings:
                result = self._upsert_listing(agent_id, listing)
                found_ids.add(listing["external_id"])
                if result == "new":
                    new_count += 1
                elif result == "updated":
                    updated_count += 1

            delisted_count = self._delist_missing(agent_id, found_ids)

            # Update last_scraped_at on the agent
            service_client.table("agents").update({
                "last_scraped_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", agent_id).execute()

            # Alert if result looks suspiciously low
            min_expected = MIN_EXPECTED_LISTINGS.get(self.agent_slug, 1)
            if len(listings) < min_expected:
                self._send_alert(
                    f"[{self.agent_slug}] Only {len(listings)} listings found "
                    f"(expected ≥{min_expected}). Scraper may be broken."
                )

        except Exception as e:
            error_msg = str(e)
            logger.error("[%s] Scrape failed: %s", self.agent_slug, e)
            self._send_alert(f"[{self.agent_slug}] Scrape failed: {e}")

        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._write_run(
                agent_id=agent_id,
                found=len(listings),
                new=new_count,
                updated=updated_count,
                delisted=delisted_count,
                error=error_msg,
                duration_ms=duration_ms,
            )
            logger.info(
                "[%s] Done in %dms — found=%d new=%d updated=%d delisted=%d error=%s",
                self.agent_slug, duration_ms, len(listings),
                new_count, updated_count, delisted_count, error_msg,
            )
