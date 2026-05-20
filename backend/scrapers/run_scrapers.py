"""
Scraper orchestrator.

Scheduled by Railway cron: 0 6 * * * → python -m backend.scrapers.run_scrapers
Manual trigger: python -m backend.scrapers.run_scrapers [--agent=<slug>]
Admin API trigger: POST /admin/scrape/<slug>
"""

import argparse
import logging
import sys

from backend.database import service_client
from backend.scrapers.christie import ChristieScraper
from backend.scrapers.dental_elite import DentalEliteScraper
from backend.scrapers.frank_taylor import FrankTaylorScraper
from backend.scrapers.henry_schein import HenryScheinScraper
from backend.scrapers.lily_head import LilyHeadScraper
from backend.scrapers.pfm_dental import PFMDentalScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_scrapers")

SCRAPER_MAP = {
    "christie":      ChristieScraper,
    "dental-elite":  DentalEliteScraper,
    "frank-taylor":  FrankTaylorScraper,
    "henry-schein":  HenryScheinScraper,
    "lily-head":     LilyHeadScraper,
    "pfm-dental":    PFMDentalScraper,
}


def _get_active_agents() -> list[dict]:
    result = (
        service_client.table("agents")
        .select("slug, max_listings")
        .eq("scrape_enabled", True)
        .execute()
    )
    return result.data


def run_single_agent(agent_slug: str):
    """Run one agent's scraper. Called by the admin API and CLI."""
    cls = SCRAPER_MAP.get(agent_slug)
    if not cls:
        logger.error("No scraper registered for slug '%s'", agent_slug)
        return

    agent_row = (
        service_client.table("agents")
        .select("max_listings, scrape_enabled")
        .eq("slug", agent_slug)
        .single()
        .execute()
    )
    if not agent_row.data:
        logger.error("Agent '%s' not found in database", agent_slug)
        return

    if not agent_row.data.get("scrape_enabled", True):
        logger.info("Agent '%s' has scrape_enabled=false — skipping", agent_slug)
        return

    max_listings = agent_row.data.get("max_listings") or 999
    scraper = cls(max_listings=max_listings)
    scraper.run()


def run_all_agents():
    """Run all agents that have scrape_enabled=true. Each runs independently."""
    active = _get_active_agents()
    if not active:
        logger.warning("No agents with scrape_enabled=true found in database")
        return

    logger.info("Running scrapers for %d agents: %s", len(active), [a["slug"] for a in active])

    for agent in active:
        slug = agent["slug"]
        max_listings = agent.get("max_listings") or 999
        cls = SCRAPER_MAP.get(slug)
        if not cls:
            logger.warning("No scraper class registered for slug '%s' — skipping", slug)
            continue
        try:
            logger.info("--- Starting %s ---", slug)
            scraper = cls(max_listings=max_listings)
            scraper.run()
        except Exception as e:
            # One agent failure must never block the others
            logger.error("Unhandled exception for agent '%s': %s", slug, e)

    logger.info("All scrapers complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BizDentistry scraper runner")
    parser.add_argument("--agent", type=str, default=None,
                        help="Slug of a single agent to scrape (default: all active)")
    args = parser.parse_args()

    if args.agent:
        run_single_agent(args.agent)
    else:
        run_all_agents()
