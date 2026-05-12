"""FastAPI service that wraps the Kodo People scraper.

POST /scrape   body: {"url": "<report url>"}
GET  /health   -> {"status": "ok"}

A single Chromium instance is launched on startup and reused across requests
(one fresh BrowserContext per request). MAX_CONCURRENCY caps the number of
in-flight scrapes so the browser doesn't fall over under load.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from playwright.async_api import Browser, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, Field, HttpUrl

from scrape_kodo import scrape_with_browser

log = logging.getLogger("kodo_api")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "2"))
SCRAPE_TIMEOUT_MS = int(os.environ.get("SCRAPE_TIMEOUT_MS", "60000"))


EXAMPLE_REPORT_URL = (
    "https://app.kodopeople.com/index.php?r=report%2Fshare&id="
    "d4lkFhOgY8gsg2VgOEF_VzIxYzF%20hN2Q5Yzk3MjJhZjBlMjUzY2EwNTc5NDE2Nzk0NTIzYTNmZDc3Y2YyMzdjM2RmM2VlMjRiNDQ3"
    "%20MmIwN2VIybmYqllyCfTUOlvPr0Dg23d71PkSP8C6KUfZ2qgPFisekK6GvQ2iIYK9o_f0wJcP7RYU1Q"
    "%20nrB0GpPkYHUHpqph3A6hAyeX3KL7M10UHfVA%3D%3D"
)


class ScrapeRequest(BaseModel):
    url: HttpUrl = Field(
        ...,
        description="Public Kodo People share URL",
        examples=[EXAMPLE_REPORT_URL],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"url": EXAMPLE_REPORT_URL}],
        }
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Launching Chromium (max concurrency: %d)", MAX_CONCURRENCY)
    pw = await async_playwright().start()
    browser: Browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    app.state.browser = browser
    app.state.semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    try:
        yield
    finally:
        log.info("Shutting down Chromium")
        await browser.close()
        await pw.stop()


app = FastAPI(
    title="Kodo People Scraper",
    version="1.0.0",
    description="Scrape a public Kodo People Soft Skills PRO report into JSON.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    browser: Browser | None = getattr(app.state, "browser", None)
    return {
        "status": "ok" if browser and browser.is_connected() else "degraded",
        "browser_connected": bool(browser and browser.is_connected()),
        "max_concurrency": MAX_CONCURRENCY,
    }


@app.post("/scrape")
async def scrape_endpoint(payload: ScrapeRequest) -> dict[str, Any]:
    browser: Browser = app.state.browser
    if not browser.is_connected():
        raise HTTPException(status_code=503, detail="Browser is not available")

    url = str(payload.url)
    async with app.state.semaphore:
        try:
            return await scrape_with_browser(browser, url, timeout_ms=SCRAPE_TIMEOUT_MS)
        except (asyncio.TimeoutError, PlaywrightTimeout) as e:
            raise HTTPException(status_code=504, detail=f"Scrape timed out: {e}")
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except PlaywrightError as e:
            # Navigation failures (DNS, refused, TLS, ...) live here.
            raise HTTPException(status_code=502, detail=f"Navigation failed: {e}")
        except Exception:
            log.exception("Unexpected scraper error for %s", url)
            raise HTTPException(status_code=500, detail="Internal scraper error")
