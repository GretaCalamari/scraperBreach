import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, HttpUrl

from scraperBreach import ScraperConfig, StealthScraper

# ---------------------------------------------------------------------------
# Lifecycle: browser aperto all'avvio, chiuso allo shutdown
# ---------------------------------------------------------------------------

_scraper: StealthScraper | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scraper
    config = ScraperConfig(
        headless=True,
        min_delay=float(os.getenv("MIN_DELAY", "1.5")),
        max_delay=float(os.getenv("MAX_DELAY", "4.0")),
        proxy=os.getenv("PROXY"),
    )
    _scraper = StealthScraper(config)
    await _scraper.__aenter__()
    yield
    await _scraper.__aexit__(None, None, None)


app = FastAPI(title="StealthScraper API", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Auth opzionale via header X-API-Key
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_key(key: str | None = Security(_api_key_header)) -> None:
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="API key non valida o mancante")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ScrapeRequest(BaseModel):
    url: HttpUrl
    wait_for: str = "domcontentloaded"  # domcontentloaded | load | networkidle


class ScrapeResponse(BaseModel):
    url: str
    chars: int
    html: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest, _: None = Security(_check_key)):
    try:
        html = await _scraper.get_html(str(req.url), wait_for=req.wait_for)
        return ScrapeResponse(url=str(req.url), chars=len(html), html=html)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
