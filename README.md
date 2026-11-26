# AI-Powered Website Link Analysis API

A FastAPI service that takes a website URL, reads the page, asks an LLM to analyse it, and returns
five structured sections: competitor comparison, top 5 search queries, SEO improvements, top 5
services and target audience.

- **Live demo:** TODO (add your deployed URL)
- **API docs (Swagger):** TODO `https://<your-app>/docs`
- **Endpoint:** `POST /link-analysis`

## How it works

```
POST /link-analysis {"url": "..."}
   1. Validate the URL (Pydantic)
   2. Cache check, then per-IP and daily rate limit
   3. Fetch the page (SSRF-safe, manual redirect checking)
   4. Extract title, meta description, headings and body text with BeautifulSoup (capped at 12,000 characters)
   5. Send the cleaned content to the LLM with a strict prompt
   6. Validate the reply against Pydantic models (one retry that feeds the error back to the model)
   7. Check "from_website" service labels against the page text in code
   8. Return JSON
```

## Project structure

```
app/
  main.py                       endpoint, caching, rate limiting, error handling
  config.py                     settings from environment variables
  schemas.py                    request and response models (also validate the LLM output)
  services/
    website_extractor.py        safe fetching + HTML cleaning
    llm_service.py              one call_llm() for Gemini, Anthropic or OpenAI
    analysis_service.py         prompt, validation, retry, label verification
  utils/
    validators.py               URL validation and SSRF protection
    rate_limiter.py             in-memory per-IP and daily limits
tests/                          pytest tests (no real network or LLM calls)
benchmark.py                    compares models on the same websites
```

## Setup

```bash
git clone <your-repo-url> && cd ai-link-analysis
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # then edit .env with your own key
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Open http://localhost:4000/docs and try `POST /link-analysis`.

Environment variables (see `.env.example`): `LLM_PROVIDER` (`gemini`, `anthropic` or `openai`),
`LLM_MODEL`, `LLM_API_KEY`, `RATE_LIMIT_PER_MINUTE`, `MAX_ANALYSES_PER_DAY`. No keys are committed to this repository.

## Sample request

```bash
curl -X POST http://localhost:4000/link-analysis \
  -H "Content-Type: application/json" \
  -d '{"url": "https://basecamp.com"}'
```

Sample responses (full JSON files from real runs) are in `docs/final/`. Shape of a response (abbreviated):

```json
{
  "success": true,
  "website": "https://basecamp.com/",
  "brand": {"name": "Basecamp", "category": "Project Management Software", "summary": "..."},
  "content_quality_note": "",
  "analysis": {
    "competitor_analysis": {"competitors": [{"name": "Asana", "source": "ai_suggested", "...": "..."}], "...": "..."},
    "target_search_queries": [{"query": "...", "platforms": ["Google", "LinkedIn"], "intent": "...", "...": "..."}],
    "seo_improvements": {"primary_keyword": "...", "recommended_title": "...", "meta_description": "...", "supporting_content": []},
    "top_services": [{"name": "...", "source": "from_website", "...": "..."}],
    "target_audience": {"primary_audience": [], "secondary_audience": [], "industries": [], "...": "..."}
  },
  "meta": {"provider": "gemini", "model": "gemini-3.5-flash-lite", "llm_seconds": 11.9,
           "token_usage": {"input_tokens": 2844, "output_tokens": 2368, "thinking_tokens": 0}}
}
```

Error responses:

| Case | Status |
|---|---|
| Invalid URL format | 422 |
| Private or internal address (SSRF) | 400 |
| Website unreachable, blocks bots, or returns an error | 502 |
| Page has too little readable text (for example, it needs JavaScript) | 422 |
| LLM failed or returned invalid output twice | 502 (details only in the server log) |
| Rate limit exceeded | 429 |

## Security and honesty rules

- **SSRF protection:** only `http`/`https`; the hostname is resolved and rejected if it points to a private, loopback, link-local, reserved, multicast or unspecified address. Redirects are followed manually (maximum 5) and every hop is checked again. Downloads are size-capped.
- **Prompt injection:** website text is wrapped in `<website_content>` tags and the prompt tells the model to treat it as data only.
- **No invented data:** the prompt forbids search volumes, rankings, traffic numbers, percentages and statistics.
- **Competitors are AI suggestions**, not verified research. Every competitor is labelled `ai_suggested`.
- **Service labels are checked in code.** The model labels each service `from_website` or `inferred`, then `verify_service_sources()` downgrades a service to `inferred` if most words of its name do not appear in the scraped text. This is a keyword-overlap heuristic: it checks the service *name* only, not the description.
- **Secrets** are read from environment variables. `.env` is git-ignored.

## Tests

```bash
pytest -v
```

Tests never call the real internet or an LLM. They cover URL validation, SSRF blocking, the full flow with fake website and LLM, invalid LLM output, thin pages, caching, label verification and the rate limiter.

## LLM platform and model research

### A. Comparison (checked 22 Nov 2026)

Prices are USD per 1M tokens. **Prices and model names change; re-check the sources before relying on them.**

| Provider | Model | Input / Output price | Context window | Max output | JSON support | Source |
|---|---|---|---|---|---|---|
| Google | `gemini-3.5-flash-lite` | $0.30 / $2.50 | 1,048,576 | 65,536 | JSON response mode (used in this project) | https://aistudio.google.com/docs/whats-new-gemini-3.6, https://ai.google.dev/gemini-api/docs/pricing |
| Anthropic | `claude-haiku-5-5` | $0.10 / $0.50 (prompts up to 100K tokens; $0.50 / $2.50 above) | 1M | 128K | Prompt instructions + validation in this project | https://platform.claude.com/docs/en/models/haiku-5-5/overview |
| OpenAI | `gpt-6-luna` | $0.10 / $0.50 | 1,050,000 | 128,000 | Structured outputs supported; JSON mode used here | https://developers.openai.com/api/docs/models/gpt-6-luna |

Notes on sources: the Gemini prices come from Google's AI Studio release notes; the Anthropic prices come from published reports of Anthropic's pricing table (verify on the official pricing page at https://docs.claude.com); the OpenAI figures come from OpenAI's model page.
Reasoning or "thinking" tokens are billed as output tokens, so the cost formula below counts them.

### B. Measured results vs estimates

**Measured** (my own runs, 5 websites: basecamp.com, thoughtbot.com, buffer.com, allbirds.com, zingermanscommunity.com):

| Model | Valid JSON on first try | Avg response time | Avg input tokens | Avg output tokens |
|---|---|---|---|---|
| gemini-3.5-flash-lite (final prompt) | 5/5 | 11.7 s (range 6.5 to 20.8 s) | 2,714 | 2,301 (thinking tokens reported as 0) |
| gemini-3.5-flash-lite (earlier prompt) | 4/5 (one site needed a retry) | not recorded | not recorded | not recorded |

Small sample (5 sites, one run each). Response time includes network latency and varies between runs.

TODO: **Benchmark run on 26 Nov 2026** (same 5 websites for every model, one run each, my own measurements):

| Model | Runs | Valid JSON first try | Avg seconds | Avg input tokens | Avg output tokens | Avg thinking tokens | Avg cost / analysis | Cost / 1,000 analyses |
|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 4 | 4/4 | 12.4 | 2804 | 2293 | 0 | $0.00657 | $6.57 |
| claude-haiku-5-5 | not benchmarked | - | - | - | - | - | - | - |
| gpt-6-luna | not benchmarked | - | - | - | - | - | - | - |


Models marked "not benchmarked" had no API key, so I make no claim about their speed or quality.

**Quality** is a subjective 1-5 score I assigned by checking each result against its website: TODO (add your scores and one line per site).

### C. Cost per analysis

```
cost = input_tokens / 1,000,000 x input_price
     + (output_tokens + thinking_tokens) / 1,000,000 x output_price
```

**Estimates** using the measured Gemini averages (2,714 input / 2,301 output tokens). Other providers use different tokenizers, so their real token counts will differ. Replace these with your benchmark numbers.

| Model | Estimated cost per analysis | Per 1,000 analyses |
|---|---|---|
| gemini-3.5-flash-lite | about $0.0066 | about $6.57 |
| claude-haiku-5-5 | about $0.0014 | about $1.42 |
| gpt-6-luna | about $0.0014 before reasoning tokens (reasoning tokens are billed as output, so it is likely higher) | about $1.42 or more |

Output tokens are roughly as many as input tokens and cost more per token, so **output dominates the bill**.
The free tier of Gemini makes development cost $0, but production cost should be planned on paid prices.

### D. Final recommendation

- **Used in this project:** `gemini-3.5-flash-lite`, because it is the model I benchmarked end to end (5/5 valid JSON on the final prompt, 6.5 to 20.8 s) and it has a free tier for development.
- **Estimated tokens per analysis:** about 2,700 input and 2,300 output (measured).
- **Estimated cost per analysis:** about $0.0066 at the prices above (calculated from measured tokens).
- **Expected response time:** roughly 7 to 21 seconds (measured on Gemini, 5 sites).
- **Fallback:** a model from a different provider (`claude-haiku-5-5` or `gpt-6-luna`), selectable by changing `LLM_PROVIDER` and `LLM_MODEL`. On paper both are about 4.6 times cheaper per analysis; TODO: confirm speed and quality with `benchmark.py` before switching.
- **Balancing accuracy, speed and cost:** keep the extraction cheap (clean text, capped length), use one LLM call for all five sections, validate the output, retry once with the error message, and cache results. Move to a cheaper model only if the benchmark shows equal quality. I did not test for "maximum accuracy", so I make no such claim.

### E. Cost optimisation used or recommended

- Strip scripts, styles, forms and duplicate headings before sending text; cap the page text at 12,000 characters (about 3,000 tokens).
- One LLM call for all sections; one retry only when validation fails.
- `max_tokens` cap on output.
- In-memory cache (1 hour, 200 entries): repeated URLs cost nothing. Production would use Redis.
- Per-IP and daily rate limits so a public endpoint cannot run up the bill.
- Possible next step: a cheaper model for simple extraction and a stronger model only for competitor and SEO reasoning.

## Deployment

Build command: `pip install -r requirements.txt`
Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
Environment variables: set `LLM_PROVIDER`, `LLM_MODEL` and `LLM_API_KEY` in the host's dashboard (never in the repository). A `render.yaml` is included for Render.

## Known limitations

- Sites that build their content with JavaScript, or that block bots, cannot be analysed (a clear error is returned).
- Only the homepage is analysed.
- Competitors are AI suggestions and may be outdated or wrong.
- The cache and rate limiter are in memory and reset on restart.
- The label check is a keyword heuristic.

## Evidence

Screenshots and logs are in `docs/`: TODO (add `docs/screenshots/` images of `/docs`, a real result, and `docs/test_results.txt`).