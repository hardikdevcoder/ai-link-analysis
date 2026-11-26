from typing import List
from pydantic import BaseModel, Field, HttpUrl, field_validator


class AnalysisRequest(BaseModel):
    url: HttpUrl


# ---------- Brand ----------
class Brand(BaseModel):
    name: str
    category: str
    summary: str


# ---------- Section 1: Competitor vs your brand ----------
class BrandProfile(BaseModel):
    main_service: str
    target_market: str
    key_strength: str
    opportunity: str


class Competitor(BaseModel):
    name: str
    main_service: str
    target_market: str
    strengths: List[str]
    weaknesses: List[str]
    source: str = "ai_suggested"          # competitors are AI suggestions, not verified research


class CompetitorAnalysis(BaseModel):
    brand_overview: str
    main_category: str
    products_and_services: List[str]
    brand_profile: BrandProfile
    competitors: List[Competitor]
    competitor_note: str = ""
    competitive_advantages: List[str]
    positioning_opportunities: List[str]


# ---------- Section 2: Search queries ----------
_PLATFORM_MAP = {
    "google": "Google", "google search": "Google",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "x": "X", "twitter": "X", "x (twitter)": "X", "twitter/x": "X",
}


class SearchQuery(BaseModel):
    query: str
    platforms: List[str]
    intent: str
    business_relevance: str
    target_audience: str

    @field_validator("platforms")
    @classmethod
    def only_supported_platforms(cls, v):
        """Keep only Google, Facebook, Instagram, LinkedIn, X. Rename Twitter to X."""
        cleaned = []
        for p in v:
            name = _PLATFORM_MAP.get(p.strip().lower())
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned or ["Google"]


# ---------- Section 3: SEO ----------
class SupportingContent(BaseModel):
    type: str                              # e.g. FAQ, blog topic, landing page
    title: str
    reason: str


class SeoImprovements(BaseModel):
    primary_keyword: str
    secondary_keywords: List[str]
    long_tail_keywords: List[str]
    business_keywords: List[str]
    recommended_title: str = Field(max_length=60)
    title_structure_note: str
    meta_description: str = Field(max_length=160)
    supporting_content: List[SupportingContent]


# ---------- Section 4: Top services ----------
class Service(BaseModel):
    name: str
    description: str
    target_industry: str
    target_customer: str
    main_benefit: str
    source: str = "from_website"           # from_website or inferred

    @field_validator("source")
    @classmethod
    def valid_source(cls, v):
        """Anything other than the two allowed labels is treated as inferred."""
        return v if v in ("from_website", "inferred") else "inferred"


# ---------- Section 5: Target audience ----------
class TargetAudience(BaseModel):
    primary_audience: List[str]
    secondary_audience: List[str]
    industries: List[str]
    business_types: List[str]
    customer_profiles: List[str]
    geographic_focus: str = "Not specified on the website"
    customer_needs: List[str]
    customer_interests: List[str]
    recommended_marketing_segments: List[str]


# ---------- What the LLM must return ----------
class AnalysisResult(BaseModel):
    brand: Brand
    content_quality_note: str = ""
    competitor_analysis: CompetitorAnalysis
    target_search_queries: List[SearchQuery] = Field(min_length=5, max_length=5)
    seo_improvements: SeoImprovements
    top_services: List[Service] = Field(min_length=5, max_length=5)
    target_audience: TargetAudience