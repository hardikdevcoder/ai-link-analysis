import logging
import time

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.config import settings
from app.schemas import AnalysisRequest
from app.services.analysis_service import analyze
from app.services.website_extractor import extract_content, fetch_html
from app.utils.rate_limiter import RateLimiter
from app.utils.validators import UnsafeURLError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Link Analysis",
    description="Analyzes a website URL with an LLM and returns competitor, search query, "
                "SEO, services and target audience insights.",
)

CACHE_TTL = 3600          # 1 hour
CACHE_MAX_ITEMS = 200
_cache = {}               # url -> (timestamp, response)

limiter = RateLimiter(settings.rate_limit_per_minute, settings.max_analyses_per_day)


def _cache_put(url: str, response: dict) -> None:
    if len(_cache) >= CACHE_MAX_ITEMS:                 # drop the oldest entry
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)
    _cache[url] = (time.time(), response)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.post("/link-analysis")
async def link_analysis(req: AnalysisRequest, request: Request):
    url = str(req.url)

    # 1. cache (saves tokens and money; cached answers do not count toward the rate limit)
    cached = _cache.get(url)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    # 2. rate limit (only requests that would cost money are counted)
    client_ip = request.client.host if request.client else "unknown"
    blocked = limiter.check(client_ip)
    if blocked:
        raise HTTPException(status_code=429, detail=blocked, headers={"Retry-After": "60"})

    # 3. fetch the website (includes SSRF protection)
    try:
        html = await fetch_html(url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403, 429):
            detail = "The website blocked automated access (HTTP %d)." % code
        else:
            detail = "The website returned an error (HTTP %d)." % code
        raise HTTPException(status_code=502, detail=detail)
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(status_code=502, detail="Could not fetch the website: %s" % e)

    # 4. extract readable content
    content = extract_content(html)
    if len(content["text"]) < 200:
        raise HTTPException(
            status_code=422,
            detail="Not enough readable content. The site may need JavaScript to load.",
        )

    # 5. analyze with the LLM
    start = time.perf_counter()
    try:
        result, usage = await analyze(content)
    except Exception:
        logger.exception("LLM analysis failed")        # full detail stays in the server log only
        raise HTTPException(status_code=502, detail="AI analysis failed. Please try again.")
    elapsed = round(time.perf_counter() - start, 2)

    # 6. build the response
    response = {
        "success": True,
        "website": url,
        "brand": result.brand.model_dump(),
        "content_quality_note": result.content_quality_note,
        "analysis": {
            "competitor_analysis": result.competitor_analysis.model_dump(),
            "target_search_queries": [q.model_dump() for q in result.target_search_queries],
            "seo_improvements": result.seo_improvements.model_dump(),
            "top_services": [s.model_dump() for s in result.top_services],
            "target_audience": result.target_audience.model_dump(),
        },
        "meta": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "llm_seconds": elapsed,
            "token_usage": usage,
        },
    }
    _cache_put(url, response)
    return response