import asyncio
import json
import os
import time

from app.services.website_extractor import fetch_html, extract_content
from app.services.analysis_service import analyze

# Put 3-5 real business sites here
SITES = [
    "https://basecamp.com",
    "https://thoughtbot.com",
    "https://www.buffer.com",
    "https://www.allbirds.com",
    "https://www.zingermanscommunity.com",
]


async def run_one(i, url):
    print(f"\n[{i}] {url}")
    try:
        content = extract_content(await fetch_html(url))
        if len(content["text"]) < 200:
            print("   SKIPPED: not enough readable content")
            return
        start = time.perf_counter()
        result, usage = await analyze(content)
        secs = round(time.perf_counter() - start, 2)
        print(f"   OK  {secs}s  tokens: {usage}")
        print(f"   brand: {result.brand.name} | category: {result.brand.category}")
        print(f"   new title: {result.seo_improvements.recommended_title}")
        print(f"   competitors: {[c.name for c in result.competitor_analysis.competitors]}")

        os.makedirs("docs", exist_ok=True)
        with open(f"docs/sample_{i}.json", "w") as f:
            json.dump({"website": url, "seconds": secs, "usage": usage,
                       "analysis": result.model_dump()}, f, indent=2)
    except Exception as e:
        print(f"   FAILED: {str(e)[:200]}")


async def main():
    for i, url in enumerate(SITES, start=1):
        await run_one(i, url)
        await asyncio.sleep(5)          # avoid free-tier rate limits


asyncio.run(main())