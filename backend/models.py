from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AgentPublic(BaseModel):
    id: str
    name: str
    slug: str
    website: Optional[str]
    logo_url: Optional[str]
    priority_rank: int
    featured_enabled: bool


class ListingPublic(BaseModel):
    id: str
    agent_id: str
    title: Optional[str]
    location: Optional[str]
    region_normalised: Optional[str]
    practice_type: Optional[str]
    tenure: Optional[str]
    num_surgeries: Optional[int]
    asking_price: Optional[str]
    turnover: Optional[str]
    ebitda_associate_led: Optional[str]
    ebitda_owner_operated: Optional[str]
    uda_value: Optional[str]
    highlights: Optional[list[str]]
    listing_url: Optional[str]
    image_url: Optional[str]
    is_featured: bool
    scraped_at: Optional[datetime]


class AgentConfigUpdate(BaseModel):
    priority_rank: Optional[int] = None
    max_listings: Optional[int] = None
    featured_enabled: Optional[bool] = None
    subscription_tier: Optional[str] = None
    monthly_budget: Optional[float] = None
    budget_notes: Optional[str] = None
    scrape_enabled: Optional[bool] = None


class ScraperRunSummary(BaseModel):
    id: str
    agent_id: Optional[str]
    run_at: datetime
    listings_found: Optional[int]
    listings_new: Optional[int]
    listings_updated: Optional[int]
    listings_delisted: Optional[int]
    error_message: Optional[str]
    duration_ms: Optional[int]
