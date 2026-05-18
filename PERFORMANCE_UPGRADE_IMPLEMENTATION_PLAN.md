# Performance Upgrade Implementation Plan

This plan implements `PERFORMANCE_UPGRADE_DESIGN.md` in small, testable steps. It is ordered so the agent becomes more reliable first, then smarter, then more scalable.

## Guiding Principles

- Keep OpenClaw WhatsApp delivery unchanged.
- Keep `.env` for secrets and local configuration.
- Do not remove the current Yahoo/Stooq no-key path; keep it as fallback.
- Prefer SQLite for the next phase; move to Postgres/vector DB only after the local workflow is stable.
- Each step should end with a dry-run test and a saved memory record.

## Phase 0: Baseline And Safety

Status: Done

Goal: make sure the current project is stable before adding new sources.

Steps:

1. Run the current dry run:

   ```bash
   cd /home/renjeff/Documents/projects/Stock
   API_REQUEST_DELAY_SECONDS=0 PYTHONPATH=src python3 -m stock_whatsapp_agent.main --dry-run
   ```

2. Confirm the current outputs exist:

   ```text
   memory/daily_stock/YYYY-MM-DD/stock_update.md
   memory/daily_stock/YYYY-MM-DD/stock_update.json
   data/stock_agent.sqlite3
   ```

3. Confirm `.env` is ignored by git.

4. Add a small smoke-test checklist to `README.md`.

Completion notes:

- Dry-run command is documented in `README.md`.
- Memory and SQLite outputs are documented in `README.md`.
- `.env` remains ignored by git.
- This phase does not require production code changes.

Acceptance criteria:

- Current agent still fetches at least fallback prices.
- Current agent still saves SQLite and daily memory.
- No secret values are committed.

## Phase 1: Provider Health And Fallback Control

Status: Done

Goal: make provider failures visible and controllable.

Files likely touched:

- `src/stock_whatsapp_agent/providers.py`
- `src/stock_whatsapp_agent/storage.py`
- `src/stock_whatsapp_agent/config.py`
- `.env.example`

Steps:

1. Add a `ProviderResult` shape internally:

   ```text
   provider_name
   success
   error
   latency_ms
   fetched_at
   stale
   ```

2. Add a `provider_health` SQLite table:

   ```text
   run_id
   provider_name
   operation
   success
   error
   latency_ms
   created_at
   ```

3. Wrap each provider call with health tracking:

   ```text
   get_quote
   get_news
   get_top_gainers
   get_history
   ```

4. Add config:

   ```bash
   PRIMARY_MARKET_PROVIDER=finnhub
   FALLBACK_MARKET_PROVIDERS=stooq,yahoo
   PROVIDER_TIMEOUT_SECONDS=8
   ```

5. Show provider warnings in the dry-run log, but keep WhatsApp concise.

Completion notes:

- `ProviderHealthRecord` records provider name, operation, success, error, latency, timestamp, and stale flag.
- Provider calls for quotes, news, top gainers, and history are wrapped with health tracking.
- `provider_health` records are saved to SQLite with each run.
- `PRIMARY_MARKET_PROVIDER`, `FALLBACK_MARKET_PROVIDERS`, and `PROVIDER_TIMEOUT_SECONDS` are documented in `.env.example`.
- The existing Yahoo/Stooq path remains the default no-key fallback behavior.

Acceptance criteria:

- A provider failure does not stop the run.
- Provider success/failure is saved to SQLite.
- WhatsApp output mentions stale or missing data only when important.

## Phase 2: Finnhub Primary Provider

Status: Done

Goal: use Finnhub as the primary data source for richer and more reliable stock intelligence.

Files likely touched:

- `src/stock_whatsapp_agent/providers.py`
- `src/stock_whatsapp_agent/config.py`
- `.env.example`
- `README.md`

Steps:

1. Add `.env.example` entries:

   ```bash
   FINNHUB_API_KEY=your_finnhub_key
   PRIMARY_MARKET_PROVIDER=finnhub
   ```

2. Split provider configuration:

   ```text
   STOCK_API_PROVIDER can remain for backward compatibility.
   New config should prefer PRIMARY_MARKET_PROVIDER.
   ```

3. Implement Finnhub quote support:

   ```text
   /quote
   ```

4. Implement Finnhub company news:

   ```text
   /company-news
   ```

5. Implement Finnhub recommendation trend:

   ```text
   /stock/recommendation
   ```

6. Implement Finnhub earnings calendar or earnings endpoint if available on the selected plan.

7. Add rate-limit handling:

   ```text
   429 -> mark provider limited -> use fallback
   ```

Completion notes:

- `FINNHUB_API_KEY` is supported as the provider-specific key.
- `PRIMARY_MARKET_PROVIDER=finnhub` selects Finnhub when a key is available.
- Missing Finnhub credentials fall back to Yahoo/Stooq instead of stopping the run.
- Finnhub quote and company-news support remain available.
- Finnhub recommendation trends and earnings calendar signals are fetched and saved when available.
- Recommendation and earnings records are stored in SQLite and daily memory.

Acceptance criteria:

- With `FINNHUB_API_KEY`, watchlist quotes and news come from Finnhub.
- Without `FINNHUB_API_KEY`, the agent still works through Stooq/Yahoo fallback.
- Provider source is recorded in SQLite.

## Phase 3: Response Cache And News Deduplication

Status: Done

Goal: reduce repeated API calls and repeated LLM work.

Files likely touched:

- `src/stock_whatsapp_agent/storage.py`
- new `src/stock_whatsapp_agent/cache.py`
- new `src/stock_whatsapp_agent/dedupe.py`

Steps:

1. Add a `provider_cache` SQLite table:

   ```text
   cache_key
   provider_name
   operation
   response_json
   created_at
   expires_at
   ```

2. Add cache TTL config:

   ```bash
   QUOTE_CACHE_TTL_SECONDS=300
   NEWS_CACHE_TTL_SECONDS=21600
   HISTORY_CACHE_TTL_SECONDS=86400
   ```

3. Add deterministic cache keys:

   ```text
   provider:operation:symbol:params_hash
   ```

4. Add news dedupe table:

   ```text
   news_hash
   symbol
   headline
   url
   first_seen_at
   last_seen_at
   seen_count
   ```

5. Compute `news_hash` from:

   ```text
   normalized URL if available
   else normalized headline + source
   ```

6. Filter duplicate news before formatting and reasoning.

Completion notes:

- Added SQLite-backed `provider_cache` storage with per-operation TTL.
- Added cache config for quote, news, and history TTLs.
- Provider calls now check cache before calling the upstream provider.
- Cache hits are tracked in provider health with `stale=true`.
- Added `news_dedupe` table and URL/headline hashing.
- News items are deduplicated before memory, SQLite, and message formatting.

Acceptance criteria:

- Re-running the agent quickly should reuse cached news/history.
- Duplicate headlines do not repeat in the WhatsApp message.
- SQLite records first seen and last seen news.

## Phase 4: Event Extraction Schema

Status: Done

Goal: turn raw news and filings into structured events.

Files likely touched:

- new `src/stock_whatsapp_agent/events.py`
- `src/stock_whatsapp_agent/storage.py`
- `src/stock_whatsapp_agent/reasoning.py`

Steps:

1. Add event model:

   ```text
   symbol
   event_type
   headline
   summary
   source
   published_at
   sentiment
   confidence
   impact_score
   related_symbols
   dedupe_hash
   ```

2. Start with rule-based extraction:

   ```text
   upgrade / downgrade
   earnings / revenue / guidance
   acquisition / partnership
   SEC / investigation / lawsuit
   insider buy / insider sell
   product launch
   macro rate / CPI / jobs
   ```

3. Add `events` SQLite table.

4. Link events back to news rows by `news_hash`.

5. Add event summary to daily memory JSON.

Completion notes:

- Added `StockEvent` and rule-based event extraction in `events.py`.
- News can produce structured events for analyst actions, earnings, guidance, acquisitions, partnerships, legal/SEC issues, insider activity, launches, and macro events.
- Events include sentiment, confidence, impact score, related symbols, and news dedupe hash.
- Events are saved to SQLite and daily memory JSON.
- Event impact now contributes to the heuristic reasoning layer.
- WhatsApp output can show an `Important Events` section when events are available.

Acceptance criteria:

- Every news item can produce zero or one structured event.
- The WhatsApp output can show "important events" instead of raw headlines.
- Events are stored and can be compared across days.

## Phase 5: SEC EDGAR Ingestion

Status: Done

Goal: add official company filing intelligence.

Files likely touched:

- new `src/stock_whatsapp_agent/sec.py`
- `src/stock_whatsapp_agent/storage.py`
- `src/stock_whatsapp_agent/events.py`
- `.env.example`

Steps:

1. Add SEC config:

   ```bash
   SEC_USER_AGENT="StockAgent contact@example.com"
   ENABLE_SEC_INGESTION=true
   ```

2. Add CIK mapping:

   ```text
   symbol -> CIK
   ```

3. Fetch recent company submissions.

4. Track important forms:

   ```text
   8-K
   10-Q
   10-K
   4
   S-1
   ```

5. Store filings:

   ```text
   symbol
   cik
   form_type
   filing_date
   accession_number
   filing_url
   title
   ```

6. Convert filings into events:

   ```text
   filing_event
   insider_transaction
   earnings_related_filing
   ```

Completion notes:

- Added `SecEdgarClient` and `SecFiling` in `sec.py`.
- Added static CIK mapping for the current watchlist and common related stocks.
- Fetches recent important SEC forms: `8-K`, `10-Q`, `10-K`, Form `4`, and `S-1`.
- Stores filings in SQLite with `accession_number` as the dedupe key.
- Adds SEC filings to daily memory JSON.
- Converts important filings into structured events with SEC-specific event types.
- Adds `Recent SEC Filings` to the WhatsApp message when filings are available.

Acceptance criteria:

- Agent can say whether a watchlist stock had a new important filing.
- Filings are deduped by accession number.
- Filing events appear in memory and SQLite.

## Phase 6: Memory Retrieval

Status: Done

Goal: use stored memory to improve today's reasoning.

Files likely touched:

- new `src/stock_whatsapp_agent/memory_retrieval.py`
- `src/stock_whatsapp_agent/reasoning.py`
- `src/stock_whatsapp_agent/storage.py`

Steps:

1. Add retrieval functions:

   ```text
   get_recent_analyses(symbol, days=7)
   get_recent_events(symbol, days=14)
   get_open_alerts(symbol)
   get_active_narratives(symbol)
   ```

2. Add "what changed since yesterday" comparison:

   ```text
   price change
   new events
   repeated events
   narrative direction
   alert level change
   ```

3. Add memory context to reasoning:

   ```text
   prior stance
   prior confidence
   recent alert history
   repeated narrative
   ```

4. Add `memory_retrievals` table:

   ```text
   run_id
   symbol
   memory_type
   retrieved_id
   reason
   ```

Completion notes:

- Added `memory_retrieval.py` with recent analysis, event, alert, and narrative retrieval helpers.
- Added per-symbol `MemoryContext` with prior stance, prior confidence, recent alerts, recent events, repeated event count, and change summary.
- Added `memory_retrievals` SQLite table.
- Memory context is passed into reasoning and can reduce confidence for repeated recent alerts/events.
- Daily WhatsApp output includes a `Memory Comparison` section.
- Daily memory JSON includes memory contexts.

Acceptance criteria:

- The daily message can say "new since yesterday" or "continuing from prior runs."
- Repeated unchanged events are not treated as fresh.
- Reasoning confidence can be adjusted using prior memory.

## Phase 7: News Clustering Skill

Status: Done

Goal: cluster headlines about the same story.

Files likely touched:

- new `src/stock_whatsapp_agent/skills/news_clustering.py`
- `src/stock_whatsapp_agent/events.py`
- `src/stock_whatsapp_agent/storage.py`

Steps:

1. Add a local `skills` package.

2. Implement rule-based clustering first:

   ```text
   same symbol
   similar normalized keywords
   same event type
   close publish time
   ```

3. Add `event_clusters` table:

   ```text
   cluster_id
   title
   symbols
   event_type
   source_count
   first_seen_at
   last_seen_at
   summary
   confidence
   ```

4. Attach events to clusters.

5. Format WhatsApp with cluster summaries instead of every headline.

Completion notes:

- Added a local `skills` package with rule-based news/event clustering.
- Clustering groups events by symbol, event type, keyword similarity, and close publish time.
- Added cluster IDs to events and persists cluster summaries in `event_clusters`.
- WhatsApp output shows concise `News Clusters` with source count and confidence when clusters exist.
- Daily memory JSON includes event clusters.

Acceptance criteria:

- Multiple articles about one NVDA event become one cluster.
- The message includes source count and concise summary.
- Token usage and message length are reduced.

## Phase 8: Narrative Tracking Skill

Status: Done

Goal: identify and track multi-day market stories.

Files likely touched:

- new `src/stock_whatsapp_agent/skills/narrative_tracking.py`
- `src/stock_whatsapp_agent/storage.py`
- `src/stock_whatsapp_agent/reasoning.py`

Steps:

1. Define initial narratives:

   ```text
   AI infrastructure
   cloud capex
   EV margin pressure
   rate-cut expectations
   chip export controls
   datacenter power demand
   ```

2. Map events to narratives using keywords and related symbols.

3. Add `narratives` table:

   ```text
   narrative_id
   name
   direction
   strength
   related_symbols
   supporting_event_ids
   contradicting_event_ids
   updated_at
   ```

4. Update narrative direction:

   ```text
   strengthening
   weakening
   stable
   mixed
   ```

5. Add one narrative line to WhatsApp when meaningful.

Completion notes:

- Added `narrative_tracking.py` with initial AI infrastructure, cloud capex, EV margin, rates, chip export, and datacenter power narratives.
- Events map to narratives through configured keywords and carry related symbols into the narrative state.
- Added persisted `narratives` state with direction, strength, related symbols, supporting events, contradicting events, and updated time.
- Strengthening, weakening, and mixed narratives can influence per-stock reasoning.
- WhatsApp output includes a `Market Narratives` section when narrative movement is meaningful.

Acceptance criteria:

- Agent can report whether the AI infrastructure narrative is strengthening or weakening.
- Narrative state persists across runs.
- Related symbols can be attached to the same narrative.

## Phase 9: Cross-Stock Reasoning Skill

Status: Done

Goal: infer second-order effects between stocks.

Files likely touched:

- new `src/stock_whatsapp_agent/skills/cross_stock_reasoning.py`
- `src/stock_whatsapp_agent/storage.py`
- `src/stock_whatsapp_agent/reasoning.py`

Steps:

1. Add a basic relationship map:

   ```text
   NVDA -> AMD, SMCI, ANET, VRT, ETN
   TSLA -> RIVN, GM, F, ALB
   MSFT -> AMZN, GOOGL, NVDA
   AAPL -> QCOM, AVGO, TSM
   ```

2. Add relationship types:

   ```text
   competitor
   supplier
   customer
   sector peer
   beneficiary
   constraint
   ```

3. Generate cross-stock observations from events and price moves.

4. Store observations:

   ```text
   source_symbol
   related_symbol
   relationship
   reasoning
   confidence
   ```

5. Show only high-confidence observations in WhatsApp.

Completion notes:

- Added `cross_stock_reasoning.py` with the initial relationship map and relationship types.
- Generates observations from high-impact source events and large source price moves.
- Persists deterministic cross-stock observations in SQLite and skips already stored observations.
- High-confidence read-throughs can influence per-stock reasoning.
- WhatsApp output includes a `Cross-Stock Read-Through` section for high-confidence observations only.

Acceptance criteria:

- If NVDA has an AI demand event, agent can mention related beneficiaries.
- Cross-stock reasoning is stored, not regenerated blindly every run.
- Low-confidence relationships are not sent as alerts.

## Phase 10: Alert Prioritization

Status: Done

Goal: send fewer, better alerts.

Files likely touched:

- new `src/stock_whatsapp_agent/skills/alert_prioritization.py`
- `src/stock_whatsapp_agent/reasoning.py`
- `src/stock_whatsapp_agent/formatter.py`

Steps:

1. Define alert levels:

   ```text
   none
   watch
   important
   urgent
   ```

2. Score:

   ```text
   absolute price move
   volume anomaly
   event impact
   news cluster strength
   SEC filing severity
   social sentiment spike
   memory novelty
   ```

3. Add "novelty" penalty for repeated old news.

4. Add "source confidence" boost for SEC/company filings.

5. Format WhatsApp around alert priority.

Completion notes:

- Added `alert_prioritization.py` with `none`, `watch`, `important`, and `urgent` levels.
- Alert score now combines price moves, volume signals, event impact, news cluster strength, SEC/company source confidence, cross-stock read-through, and memory novelty penalties.
- Existing yes/no alert behavior is preserved, with yes only for `important` and `urgent` priorities.
- Analyses persist alert level, score, and reason in SQLite.
- WhatsApp `Agent Actions` are sorted by alert priority and include the reason an alert was or was not triggered.

Acceptance criteria:

- High-severity events are surfaced first.
- Repeated low-value news is suppressed.
- The message clearly says why an alert was or was not triggered.

## Phase 11: Optional Semantic Memory

Status: Done

Goal: add vector retrieval only after structured memory is useful.

Files likely touched:

- new `src/stock_whatsapp_agent/vector_memory.py`
- `.env.example`
- `requirements.txt`

Steps:

1. Choose local-first vector DB:

   ```text
   ChromaDB for simplest local setup
   Qdrant for stronger long-term architecture
   ```

2. Add config:

   ```bash
   ENABLE_VECTOR_MEMORY=false
   VECTOR_DB_PROVIDER=qdrant
   ```

3. Embed only compact summaries:

   ```text
   event summary
   filing summary
   daily analysis
   narrative summary
   ```

4. Retrieve top memories before reasoning.

Completion notes:

- Added `vector_memory.py` with an optional local SQLite-backed semantic memory store.
- Vector memory is disabled by default with `ENABLE_VECTOR_MEMORY=false`.
- The local provider stores compact hashed-vector summaries for events, filings, daily analyses, and narratives without embedding raw oversized documents.
- Enabled runs retrieve top symbol-relevant semantic memories before reasoning and save compact memories after the structured run is persisted.
- Unsupported vector providers are isolated behind config and do not affect disabled runs.

Acceptance criteria:

- Vector memory can be disabled without breaking the agent.
- Agent retrieves relevant older context for a ticker or narrative.
- No raw oversized documents are embedded by default.

## Phase 12: Dashboard Upgrade

Status: Done

Goal: make local inspection easier.

Files likely touched:

- `src/stock_whatsapp_agent/dashboard.py`
- `README.md`

Steps:

1. Expand static HTML dashboard:

   ```text
   watchlist table
   alert table
   event cluster table
   narrative table
   NVDA chart widget
   provider health table
   ```

2. Link dashboard to latest SQLite data.

3. Keep dashboard generation optional.

Completion notes:

- Expanded `dashboard.py` to generate a static `dashboard/index.html` from the latest SQLite run.
- Dashboard includes watchlist, alert priority, event cluster, narrative, and provider health tables.
- Existing chart widget remains linked when enough history is available.
- Missing sections and stale or failed provider calls are clearly marked.
- Dashboard generation remains controlled by `GENERATE_CHART_WIDGET`.

Acceptance criteria:

- Opening `dashboard/index.html` shows the latest run.
- No external server is required.
- Dashboard clearly marks missing or stale data.

## Final Validation Checklist

Run after every phase:

```bash
cd /home/renjeff/Documents/projects/Stock
python3 -m compileall src
API_REQUEST_DELAY_SECONDS=0 PYTHONPATH=src python3 -m stock_whatsapp_agent.main --dry-run
```

Check:

- No linter errors.
- No secrets committed.
- WhatsApp dry-run message remains concise.
- SQLite tables are populated as expected.
- Memory files are written.
- Provider failures do not kill the run.

## Recommended Implementation Order

Best next three implementation tasks:

1. Provider health and fallback control.
2. Finnhub primary provider.
3. Response cache and news dedupe.

These three unlock the largest reliability improvement before adding more advanced skills.

