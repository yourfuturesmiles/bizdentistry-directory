from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import require_admin
from backend.database import anon_client, service_client
from backend.models import AgentConfigUpdate

app = FastAPI(title="BizDentistry Directory API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.bizdentistry.com",
        "https://bizdentistry.com",
        # Replace with your actual Netlify URL:
        "https://bizdentistry-directory.netlify.app",
        # Local dev:
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Public endpoints ──────────────────────────────────────────────────────────

@app.get("/agents")
def get_agents():
    """Returns active agents only. Never exposes billing or inactive agents."""
    result = (
        anon_client.table("agents")
        .select("id, name, slug, website, logo_url, priority_rank, featured_enabled")
        .eq("is_active", True)
        .order("priority_rank")
        .execute()
    )
    return result.data


@app.get("/listings")
def get_listings():
    """
    Returns active listings from active agents.
    max_listings cap is applied per-agent in Python (not SQL) to avoid
    race conditions from concurrent scraper runs.
    Sort: featured first → priority_rank asc → scraped_at desc.
    """
    agents = (
        anon_client.table("agents")
        .select("id, max_listings, priority_rank")
        .eq("is_active", True)
        .order("priority_rank")
        .execute()
    )

    all_listings = []
    for agent in agents.data:
        cap = agent.get("max_listings") or 999
        rows = (
            anon_client.table("listings")
            .select(
                "id, agent_id, title, location, region_normalised, practice_type, "
                "tenure, num_surgeries, asking_price, turnover, ebitda_associate_led, "
                "ebitda_owner_operated, uda_value, highlights, listing_url, image_url, "
                "is_featured, scraped_at"
            )
            .eq("agent_id", agent["id"])
            .eq("is_active", True)
            .order("is_featured", desc=True)
            .order("scraped_at", desc=True)
            .limit(cap)
            .execute()
        )
        # Attach agent priority_rank for final sort
        for row in rows.data:
            row["_priority_rank"] = agent.get("priority_rank", 99)
        all_listings.extend(rows.data)

    # Featured first → agent priority_rank → newest scraped_at
    all_listings.sort(
        key=lambda x: (
            not x.get("is_featured", False),
            x.get("_priority_rank", 99),
            x.get("scraped_at", "") or "",
        )
    )

    # Strip internal sort key before returning
    for listing in all_listings:
        listing.pop("_priority_rank", None)

    return all_listings


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.post("/admin/agent/{agent_id}/toggle", dependencies=[Depends(require_admin)])
def toggle_agent(agent_id: str):
    current = (
        service_client.table("agents")
        .select("is_active")
        .eq("id", agent_id)
        .single()
        .execute()
    )
    if not current.data:
        raise HTTPException(status_code=404, detail="Agent not found")
    new_state = not current.data["is_active"]
    service_client.table("agents").update({"is_active": new_state}).eq("id", agent_id).execute()
    return {"agent_id": agent_id, "is_active": new_state}


@app.post("/admin/agent/{agent_id}/config", dependencies=[Depends(require_admin)])
def update_agent_config(agent_id: str, body: AgentConfigUpdate):
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    service_client.table("agents").update(update_data).eq("id", agent_id).execute()
    return {"agent_id": agent_id, "updated": update_data}


@app.post("/admin/listing/{listing_id}/feature", dependencies=[Depends(require_admin)])
def toggle_featured(listing_id: str):
    current = (
        service_client.table("listings")
        .select("is_featured")
        .eq("id", listing_id)
        .single()
        .execute()
    )
    if not current.data:
        raise HTTPException(status_code=404, detail="Listing not found")
    new_state = not current.data["is_featured"]
    service_client.table("listings").update({"is_featured": new_state}).eq("id", listing_id).execute()
    return {"listing_id": listing_id, "is_featured": new_state}


@app.post("/admin/scrape/{agent_slug}", dependencies=[Depends(require_admin)])
def trigger_scrape(agent_slug: str, background_tasks: BackgroundTasks):
    """Manually trigger a single agent's scraper as a background task."""
    from backend.scrapers.run_scrapers import run_single_agent
    background_tasks.add_task(run_single_agent, agent_slug)
    return {"status": "started", "agent": agent_slug}


@app.post("/admin/scrape-all", dependencies=[Depends(require_admin)])
def trigger_scrape_all(background_tasks: BackgroundTasks):
    """Manually trigger all active scrapers."""
    from backend.scrapers.run_scrapers import run_all_agents
    background_tasks.add_task(run_all_agents)
    return {"status": "started", "message": "All active scrapers queued"}


@app.get("/admin/runs", dependencies=[Depends(require_admin)])
def get_scraper_runs(limit: int = 30):
    result = (
        service_client.table("scraper_runs")
        .select("*, agents(name, slug)")
        .order("run_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


@app.get("/admin/dashboard", dependencies=[Depends(require_admin)])
def get_dashboard():
    agents = service_client.table("agents").select("*").order("priority_rank").execute()
    dashboard = []
    for agent in agents.data:
        listing_count = (
            service_client.table("listings")
            .select("id", count="exact")
            .eq("agent_id", agent["id"])
            .eq("is_active", True)
            .execute()
        )
        featured_count = (
            service_client.table("listings")
            .select("id", count="exact")
            .eq("agent_id", agent["id"])
            .eq("is_active", True)
            .eq("is_featured", True)
            .execute()
        )
        last_run = (
            service_client.table("scraper_runs")
            .select("run_at, listings_found, error_message")
            .eq("agent_id", agent["id"])
            .order("run_at", desc=True)
            .limit(1)
            .execute()
        )
        dashboard.append({
            "agent": {
                "id": agent["id"],
                "name": agent["name"],
                "slug": agent["slug"],
                "is_active": agent["is_active"],
                "scrape_enabled": agent["scrape_enabled"],
                "priority_rank": agent["priority_rank"],
                "max_listings": agent["max_listings"],
                "featured_enabled": agent["featured_enabled"],
                "monthly_budget": agent["monthly_budget"],
                "subscription_tier": agent["subscription_tier"],
            },
            "active_listings": listing_count.count,
            "featured_listings": featured_count.count,
            "last_run": last_run.data[0] if last_run.data else None,
        })
    return dashboard
