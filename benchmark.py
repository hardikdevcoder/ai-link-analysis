"""Benchmark several LLMs on the same websites and write a results table.

Usage (from the project root, venv active):
    python -W ignore benchmark.py                       # all models below that have a key
    python -W ignore benchmark.py gemini:gemini-3.5-flash-lite anthropic:claude-haiku-5-5

What it MEASURES: response time, token usage, whether the JSON was valid on the
first try, and how many competitors came back.
What it does NOT measure: answer quality. Score that yourself (1-5) and add it to the README.

Models without an API key are skipped and reported as "not benchmarked".
"""
import asyncio
import csv
import json
import os
import sys
import time

from pydantic import ValidationError

from app.config import settings
from app.schemas import AnalysisResult
from app.services.analysis_service import SYSTEM_PROMPT, _clean_json, build_user_prompt
from app.services.llm_service import call_llm, has_key
from app.services.website_extractor import extract_content, fetch_html

# (provider, model name). Check exact names in each provider's docs before running.
MODELS = [
    ("gemini", "gemini-3.5-flash-lite"),
    ("anthropic", "claude-haiku-5-5"),
    ("openai", "gpt-6-luna"),
]

# USD per 1M tokens (input, output). Checked 22 Nov 2026. Prices change, so re-check
# the official pages listed in README.md before you submit.
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "claude-haiku-5-5": (0.10, 0.50),     # rate for prompts up to 100K tokens
    "gpt-6-luna": (0.10, 0.50),
}

SITES = [
    "https://basecamp.com",
    "https://thoughtbot.com",
    "https://www.buffer.com",
    "https://www.allbirds.com",
    "https://www.zingermanscommunity.com",
]

PAUSE_SECONDS = 5          # avoids free-tier rate limits


def cost_usd(model: str, usage: dict):
    if model not in PRICES:
        return None
    in_price, out_price = PRICES[model]
    out_tokens = usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
    return usage.get("input_tokens", 0) / 1e6 * in_price + out_tokens / 1e6 * out_price


async def run_once(provider: str, model: str, site: str, content: dict) -> dict:
    row = {"provider": provider, "model": model, "site": site}
    try:
        start = time.perf_counter()
        raw, usage = await call_llm(SYSTEM_PROMPT, build_user_prompt(content),
                                    provider=provider, model=model)
        row["seconds"] = round(time.perf_counter() - start, 2)
        row.update(usage)
        row["cost_usd"] = cost_usd(model, usage)
        try:
            result = AnalysisResult.model_validate_json(_clean_json(raw))
            row["valid_json_first_try"] = True
            row["competitors"] = len(result.competitor_analysis.competitors)
        except (ValidationError, json.JSONDecodeError) as e:
            row["valid_json_first_try"] = False
            row["error"] = "invalid output: " + str(e)[:120].replace("\n", " ")
    except Exception as e:                             # noqa: BLE001
        row["error"] = str(e)[:150].replace("\n", " ")
    return row


def avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(value, spec):
    return "-" if value is None else format(value, spec)


async def main():
    wanted = MODELS
    if len(sys.argv) > 1:
        wanted = [tuple(arg.split(":", 1)) for arg in sys.argv[1:]]

    # Download each site once and reuse it, so every model sees identical input.
    contents = {}
    for site in SITES:
        try:
            contents[site] = extract_content(await fetch_html(site))
            print("fetched", site, "(%d chars)" % len(contents[site]["text"]))
        except Exception as e:                         # noqa: BLE001
            print("could not fetch", site, "->", str(e)[:100])

    rows, skipped = [], []
    for provider, model in wanted:
        if not has_key(provider):
            print("\nSKIPPED %s:%s (no API key) -> report as 'not benchmarked'" % (provider, model))
            skipped.append(model)
            continue
        print("\n=== %s : %s ===" % (provider, model))
        for site, content in contents.items():
            row = await run_once(provider, model, site, content)
            rows.append(row)
            print("  ", {k: row.get(k) for k in ("site", "seconds", "input_tokens", "output_tokens",
                                                  "thinking_tokens", "valid_json_first_try", "error")})
            await asyncio.sleep(PAUSE_SECONDS)

    fields = ["provider", "model", "site", "seconds", "input_tokens", "output_tokens",
              "thinking_tokens", "cost_usd", "valid_json_first_try", "competitors", "error"]
    with open("benchmark_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "| Model | Runs | Valid JSON first try | Avg seconds | Avg input tokens | Avg output tokens | Avg thinking tokens | Avg cost / analysis | Cost / 1,000 analyses |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for provider, model in wanted:
        mine = [r for r in rows if r["model"] == model]
        if not mine:
            lines.append("| %s | not benchmarked | - | - | - | - | - | - | - |" % model)
            continue
        ok = [r for r in mine if "seconds" in r]
        valid = sum(1 for r in mine if r.get("valid_json_first_try"))
        a_cost = avg([r.get("cost_usd") for r in ok])
        lines.append("| %s | %d | %d/%d | %s | %s | %s | %s | %s | %s |" % (
            model, len(mine), valid, len(mine),
            fmt(avg([r.get("seconds") for r in ok]), ".1f"),
            fmt(avg([r.get("input_tokens") for r in ok]), ".0f"),
            fmt(avg([r.get("output_tokens") for r in ok]), ".0f"),
            fmt(avg([r.get("thinking_tokens") for r in ok]), ".0f"),
            "-" if a_cost is None else "$%.5f" % a_cost,
            "-" if a_cost is None else "$%.2f" % (a_cost * 1000),
        ))

    os.makedirs("docs", exist_ok=True)
    with open("docs/benchmark_summary.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print("\nSaved benchmark_results.csv and docs/benchmark_summary.md")
    if skipped:
        print("Not benchmarked (no key):", ", ".join(skipped))


asyncio.run(main())