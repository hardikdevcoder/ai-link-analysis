"""Automatically check saved analysis results against the real websites.

Usage (project root, venv active):
    python -W ignore score_samples.py            # automatic checks only (no LLM cost)
    python -W ignore score_samples.py --judge    # also ask the LLM for a second opinion

Reads  docs/final/sample_*.json (or docs/sample_*.json), downloads each site again,
runs 11 checks and writes docs/quality_scores.md (ready to paste into the README).

IMPORTANT: this is an automatic PROXY for quality, not a human judgement.
It checks whether results are grounded in the page and follow the rules.
It cannot tell if a competitor is truly the best match. Glance at each result yourself too.
"""
import argparse
import asyncio
import glob
import json
import os
import re
from collections import Counter

from app.services.analysis_service import _clean_json, _words
from app.services.llm_service import call_llm
from app.services.website_extractor import extract_content, fetch_html

COMMON = {
    "about", "their", "which", "these", "would", "there", "other", "where", "while", "after",
    "before", "should", "could", "great", "using", "learn", "start", "every", "better", "being",
    "first", "years", "people", "build", "built", "make", "makes", "your", "yours", "with",
    "more", "most", "than", "that", "this", "from", "have", "what", "when", "into", "over",
    "just", "like", "also", "only", "work", "free", "best", "home", "contact", "privacy",
    "terms", "login", "pricing", "company",
}

BAD_PHRASES = ("search volume", "monthly searches", "searches per month", "monthly search volume")


def read_samples():
    files = sorted(glob.glob("docs/final/sample_*.json")) or sorted(glob.glob("docs/sample_*.json"))
    samples = []
    for path in files:
        with open(path) as f:
            data = json.load(f)
        samples.append((path, data["website"], data["analysis"]))
    return samples


def top_terms(text, n=10):
    words = [w for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in COMMON]
    return [w for w, _ in Counter(words).most_common(n)]


def overlap(name, page_words):
    words = _words(name)
    if not words:
        return 0.0
    return sum(1 for w in words if w in page_words) / len(words)


def run_checks(analysis, content):
    page_text = " ".join([content["title"], content["meta_description"],
                          " ".join(content["headings"]), content["text"]])
    page_words = set(_words(page_text))
    out_text = json.dumps(analysis).lower()
    seo = analysis["seo_improvements"]
    checks = []

    def add(name, passed, detail):
        checks.append((name, bool(passed), detail))

    # 1 brand name is on the page
    brand = analysis["brand"]["name"]
    add("Brand name found on page", overlap(brand, page_words) >= 0.5, brand)

    # 2 services are grounded in the page text
    services = analysis["top_services"]
    ungrounded = [s["name"] for s in services if overlap(s["name"], page_words) < 0.5]
    add("At least 3 of 5 services found on page", len(services) - len(ungrounded) >= 3,
        "not found on page: %s" % (ungrounded or "none"))

    # 3 competitors
    comps = analysis["competitor_analysis"]["competitors"]
    labels_ok = all(c.get("source") == "ai_suggested" for c in comps)
    add("3+ competitors, all labelled ai_suggested", len(comps) >= 3 and labels_ok,
        "%d competitors: %s" % (len(comps), ", ".join(c["name"] for c in comps)))

    # 4 search queries
    queries = analysis["target_search_queries"]
    platforms = {p for q in queries for p in q["platforms"]}
    add("5 queries covering 3+ platforms", len(queries) == 5 and len(platforms) >= 3,
        "%d queries, platforms: %s" % (len(queries), ", ".join(sorted(platforms))))

    # 5 and 6 SEO title and meta description are new and within limits
    title, meta = seo["recommended_title"], seo["meta_description"]
    add("SEO title new and <= 60 chars",
        len(title) <= 60 and title.strip().lower() != content["title"].strip().lower(),
        "%d chars: %s" % (len(title), title))
    add("Meta description new and <= 160 chars",
        len(meta) <= 160 and meta.strip().lower() != content["meta_description"].strip().lower(),
        "%d chars" % len(meta))

    # 7 supporting content
    sc = seo["supporting_content"]
    types = {i["type"].lower() for i in sc}
    add("4+ supporting content items, 3+ types", len(sc) >= 4 and len(types) >= 3,
        "%d items, %d types" % (len(sc), len(types)))

    # 8 primary keyword appears in title and meta
    kw = seo["primary_keyword"].lower()
    add("Primary keyword used in title and meta", kw in title.lower() and kw in meta.lower(),
        "keyword: %s" % seo["primary_keyword"])

    # 9 no invented numbers
    pcts = re.findall(r"\d[\d,.]*\s?%", out_text)
    unsupported = [p for p in pcts if p.replace(" ", "") not in page_text.lower().replace(" ", "")]
    phrases = [p for p in BAD_PHRASES if p in out_text]
    add("No invented statistics or search volumes", not unsupported and not phrases,
        "unsupported: %s" % ((unsupported + phrases) or "none"))

    # 10 audience filled in
    aud = analysis["target_audience"]
    add("Audience section filled in",
        bool(aud["primary_audience"]) and bool(aud["secondary_audience"]) and bool(aud["customer_needs"]),
        "geography: %s" % aud.get("geographic_focus", ""))

    # 11 uses terms specific to this site
    terms = top_terms(page_text)
    used = [t for t in terms if t in out_text]
    add("Uses terms specific to this site", len(terms) > 0 and len(used) / len(terms) >= 0.3,
        "%d of %d frequent page terms used" % (len(used), len(terms)))

    passed = sum(1 for _, ok, _ in checks if ok)
    score = max(1, min(5, 1 + round(4 * passed / len(checks))))
    return checks, passed, score


JUDGE_SYSTEM = """You are a strict reviewer. You receive text taken from a website and an AI-generated analysis of it.
Score how well the analysis matches the website from 1 to 5:
5 = brand, services and audience all match the site; competitors are real and relevant
4 = mostly right with one weak point
3 = usable but partly generic or partly wrong
2 or 1 = mostly wrong or generic
Only judge against the website text provided. Return ONLY JSON:
{"score": 4, "problems": ["short problem 1"], "notes": "one sentence"}"""


async def judge(content, analysis):
    summary = {
        "brand": analysis["brand"],
        "services": [s["name"] for s in analysis["top_services"]],
        "competitors": [c["name"] for c in analysis["competitor_analysis"]["competitors"]],
        "primary_audience": analysis["target_audience"]["primary_audience"],
        "search_queries": [q["query"] for q in analysis["target_search_queries"]],
    }
    prompt = ("<website_text>\nTitle: %s\nHeadings: %s\nText: %s\n</website_text>\n\n<analysis>\n%s\n</analysis>"
              % (content["title"], ", ".join(content["headings"]), content["text"][:6000],
                 json.dumps(summary, indent=1)))
    raw, _ = await call_llm(JUDGE_SYSTEM, prompt)
    return json.loads(_clean_json(raw))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge", action="store_true", help="add an LLM second opinion")
    args = parser.parse_args()

    samples = read_samples()
    if not samples:
        print("No docs/final/sample_*.json files found. Run run_samples.py first.")
        return

    results = []
    for path, url, analysis in samples:
        print("\n%s  (%s)" % (url, path))
        try:
            content = extract_content(await fetch_html(url))
        except Exception as e:                                   # noqa: BLE001
            print("   could not download the site again: %s" % str(e)[:100])
            results.append({"url": url, "error": "could not re-download the site"})
            continue

        checks, passed, score = run_checks(analysis, content)
        row = {"url": url, "passed": passed, "total": len(checks), "score": score, "checks": checks}
        for name, ok, detail in checks:
            print("   [%s] %s - %s" % ("PASS" if ok else "FAIL", name, detail))
        print("   automatic score: %d/5 (%d of %d checks passed)" % (score, passed, len(checks)))

        if args.judge:
            try:
                row["judge"] = await judge(content, analysis)
                print("   LLM second opinion: %s/5 - %s" % (row["judge"].get("score"), row["judge"].get("notes", "")))
            except Exception as e:                               # noqa: BLE001
                print("   LLM second opinion failed: %s" % str(e)[:100])
            await asyncio.sleep(5)
        results.append(row)

    # ---------- write the markdown report ----------
    lines = ["| Website | Automatic score | Checks passed | Failed checks |" +
             (" LLM second opinion |" if args.judge else ""),
             "|---|---|---|---|" + ("---|" if args.judge else "")]
    for r in results:
        if "error" in r:
            lines.append("| %s | n/a | n/a | %s |%s" % (r["url"], r["error"], " n/a |" if args.judge else ""))
            continue
        failed = "; ".join(n for n, ok, _ in r["checks"] if not ok) or "none"
        extra = ""
        if args.judge:
            j = r.get("judge")
            extra = " %s/5 |" % j.get("score") if j else " n/a |"
        lines.append("| %s | %d/5 | %d of %d | %s |%s" % (r["url"], r["score"], r["passed"], r["total"], failed, extra))

    lines += ["", "**How these scores were produced:** a script downloads each website again and runs 11 automatic checks "
              "(brand and services found in the page text, 3+ competitors labelled as AI suggestions, queries across platforms, "
              "new SEO title and meta description within length limits, supporting content, keyword placement, "
              "no invented statistics, audience filled in, site-specific terms used). Score = 1 + 4 x (checks passed / 11), rounded.",
              "This is an automatic proxy for quality, not a formal accuracy benchmark. It does not verify that competitors are "
              "the best possible match."]
    if args.judge:
        lines.append("The LLM second opinion was produced by the same model family that wrote the analysis, so it may be lenient.")

    os.makedirs("docs", exist_ok=True)
    with open("docs/quality_scores.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print("\nSaved docs/quality_scores.md")


asyncio.run(main())
