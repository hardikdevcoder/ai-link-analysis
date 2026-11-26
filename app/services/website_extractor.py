import asyncio
import httpx
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.utils.validators import validate_public_url

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LinkAnalysisBot/1.0)"}


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers=HEADERS) as client:
        for _ in range(5):                                      # max 5 redirects
            await asyncio.to_thread(validate_public_url, url)   # check EVERY hop
            r = await client.get(url)
            if r.is_redirect:
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            if "text/html" not in r.headers.get("content-type", ""):
                raise ValueError("That URL is not an HTML web page")
            return r.text[:2_000_000]                           # cap the size
        raise ValueError("Too many redirects")


def extract_content(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    description = meta.get("content", "").strip() if meta else ""
    headings = list(dict.fromkeys(
        h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])
    ))
    text = " ".join(soup.get_text(" ", strip=True).split())

    return {
        "title": title,
        "meta_description": description,
        "headings": headings[:30],
        "text": text[:12_000],
    }