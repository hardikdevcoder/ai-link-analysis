import json
from fastapi.testclient import TestClient

from app.main import app, _cache
from app.schemas import AnalysisResult
from app.services.analysis_service import verify_service_sources

client = TestClient(app)

GOOD_HTML = "<html><head><title>Acme Web</title></head><body><h1>Web design for small businesses</h1><p>" + (
    "We build affordable websites and online stores for small businesses. " * 10
) + "</p></body></html>"


def _fake_analysis():
    return {
        "brand": {"name": "Acme Web", "category": "Web design", "summary": "Builds websites."},
        "content_quality_note": "",
        "competitor_analysis": {
            "brand_overview": "x", "main_category": "Web design",
            "products_and_services": ["Websites"],
            "brand_profile": {"main_service": "Websites", "target_market": "SMBs",
                              "key_strength": "Price", "opportunity": "SEO"},
            "competitors": [{"name": "Rival", "main_service": "Websites", "target_market": "SMBs",
                             "strengths": ["Brand"], "weaknesses": ["Cost"], "source": "ai_suggested"}],
            "competitor_note": "",
            "competitive_advantages": ["Price"], "positioning_opportunities": ["SEO"],
        },
        "target_search_queries": [
            {"query": "q%d" % i, "platforms": ["Google"], "intent": "Service",
             "business_relevance": "x", "target_audience": "SMBs"} for i in range(5)
        ],
        "seo_improvements": {
            "primary_keyword": "web design", "secondary_keywords": ["a"],
            "long_tail_keywords": ["b"], "business_keywords": ["c"],
            "recommended_title": "Web Design for Small Business", "title_structure_note": "x",
            "meta_description": "Affordable web design.",
            "supporting_content": [{"type": "FAQ", "title": "t", "reason": "r"}] * 4,
        },
        "top_services": [
            {"name": "s%d" % i, "description": "d", "target_industry": "i",
             "target_customer": "c", "main_benefit": "b", "source": "from_website"} for i in range(5)
        ],
        "target_audience": {
            "primary_audience": ["SMBs"], "secondary_audience": ["Startups"],
            "industries": ["Retail"], "business_types": ["Shops"], "customer_profiles": ["Owner"],
            "geographic_focus": "Global", "customer_needs": ["Website"],
            "customer_interests": ["Growth"], "recommended_marketing_segments": ["Local shops"],
        },
    }


def setup_function():
    _cache.clear()


# ---------- validation and security ----------
def test_invalid_url():
    assert client.post("/link-analysis", json={"url": "hello"}).status_code == 422


def test_localhost_blocked():
    assert client.post("/link-analysis", json={"url": "http://127.0.0.1"}).status_code == 400


def test_private_ip_blocked():
    assert client.post("/link-analysis", json={"url": "http://169.254.169.254"}).status_code == 400


# ---------- full flow with fakes ----------
def test_full_flow(monkeypatch):
    async def fake_fetch(url):
        return GOOD_HTML

    async def fake_llm(system_prompt, user_prompt):
        return json.dumps(_fake_analysis()), {"input_tokens": 10, "output_tokens": 20, "thinking_tokens": 0}

    monkeypatch.setattr("app.main.fetch_html", fake_fetch)
    monkeypatch.setattr("app.services.analysis_service.call_llm", fake_llm)

    r = client.post("/link-analysis", json={"url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["brand"]["name"] == "Acme Web"
    assert len(body["analysis"]["target_search_queries"]) == 5
    assert len(body["analysis"]["top_services"]) == 5


def test_llm_returns_garbage(monkeypatch):
    async def fake_fetch(url):
        return GOOD_HTML

    async def bad_llm(system_prompt, user_prompt):
        return "this is not json", {"input_tokens": 1, "output_tokens": 1, "thinking_tokens": 0}

    monkeypatch.setattr("app.main.fetch_html", fake_fetch)
    monkeypatch.setattr("app.services.analysis_service.call_llm", bad_llm)

    r = client.post("/link-analysis", json={"url": "https://example.com"})
    assert r.status_code == 502


def test_too_little_content(monkeypatch):
    async def fake_fetch(url):
        return "<html><body><p>Hi</p></body></html>"

    monkeypatch.setattr("app.main.fetch_html", fake_fetch)
    r = client.post("/link-analysis", json={"url": "https://example.com"})
    assert r.status_code == 422


def test_cache_avoids_second_llm_call(monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(url):
        return GOOD_HTML

    async def fake_llm(system_prompt, user_prompt):
        calls["n"] += 1
        return json.dumps(_fake_analysis()), {"input_tokens": 1, "output_tokens": 1, "thinking_tokens": 0}

    monkeypatch.setattr("app.main.fetch_html", fake_fetch)
    monkeypatch.setattr("app.services.analysis_service.call_llm", fake_llm)

    client.post("/link-analysis", json={"url": "https://example.com"})
    client.post("/link-analysis", json={"url": "https://example.com"})
    assert calls["n"] == 1


# ---------- label checking ----------
def test_unsupported_service_marked_inferred():
    data = _fake_analysis()
    data["top_services"][0]["name"] = "Quantum Blockchain Consulting"
    data["top_services"][1]["name"] = "Affordable Websites"
    result = AnalysisResult.model_validate(data)
    content = {
        "title": "Acme Web",
        "meta_description": "",
        "headings": ["Web design"],
        "text": "We build affordable websites and online stores for small businesses.",
    }
    result = verify_service_sources(result, content)
    assert result.top_services[0].source == "inferred"        # words not on the page
    assert result.top_services[1].source == "from_website"    # words are on the page