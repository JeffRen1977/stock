# OpenClaw Stock Agent Performance Upgrade Design

## 1. Purpose

Improve the current stock agent in three areas:

1. More reliable and richer data ingestion.
2. A memory design that reduces repeated work and improves reasoning quality.
3. New agent skills for event intelligence, narrative tracking, and cross-stock reasoning.

This document is a design proposal only. It does not change the current implementation.

## 2. Current State

The current agent already supports:

- Watchlist prices.
- Per-stock news slots.
- Daily top gainers.
- Simple technical signals.
- Local SQLite run history.
- Daily memory files.
- OpenClaw WhatsApp delivery.

Known weakness:

- Yahoo public endpoints can rate-limit.
- Stooq fallback gives prices but not complete news, gainers, or history.
- The reasoning layer is mostly heuristic.
- Memory is stored, but not yet actively used to reduce repeated analysis.

## 3. Target Architecture

```text
Scheduler
  |
  v
Data Ingestion Layer
  |
  +-- Market Data Providers
  |     +-- Finnhub
  |     +-- Stooq fallback
  |     +-- Yahoo fallback
  |     +-- Polygon future
  |
  +-- Intelligence Sources
  |     +-- SEC EDGAR
  |     +-- FRED macro data
  |     +-- Reddit / StockTwits
  |     +-- Company news
  |
  v
Normalization + Event Extraction
  |
  v
Storage + Memory Layer
  |
  +-- SQLite / Postgres structured store
  +-- File memory for daily summaries
  +-- Vector store for semantic retrieval
  +-- Knowledge graph for entity/event links
  |
  v
OpenClaw Reasoning Agent
  |
  +-- News clustering
  +-- Narrative tracking
  +-- Cross-stock reasoning
  +-- Anomaly detection
  +-- Memory comparison
  |
  v
Notification Layer
  |
  +-- WhatsApp via OpenClaw
  +-- Dashboard
```

## 4. Data Source Strategy

### 4.1 Recommended Provider Order

Use a provider abstraction layer with fallback order:

```text
Finnhub primary
  -> Stooq fallback for prices
  -> Yahoo fallback for public data
  -> Polygon future paid upgrade
```

### 4.2 Finnhub As Primary Source

Finnhub is the recommended next provider because it is better aligned with an AI agent than a pure market-data feed.

Use Finnhub for:

- Quotes.
- Company news.
- SEC filings metadata.
- Earnings calendar.
- Recommendation trends.
- Sentiment.
- Insider transactions.
- Analyst-related data.

Why Finnhub first:

- Free tier is enough for a personal MVP.
- Higher call allowance than many free alternatives.
- Covers both market data and intelligence signals.
- Better fit for event reasoning than only price feeds.

### 4.3 Polygon As Future Upgrade

Polygon should be considered later when the agent needs:

- More reliable real-time or delayed market data.
- WebSocket streaming.
- Options data.
- Higher-frequency monitoring.
- Production-grade price infrastructure.

Polygon is not the first priority for this personal OpenClaw MVP because the free tier is too limited for a multi-source reasoning agent.

### 4.4 Free Intelligence Sources

The agent should not depend only on stock price APIs. Many useful signals are free:

- SEC EDGAR: 10-K, 10-Q, 8-K, Form 4 insider transactions.
- FRED: rates, CPI, unemployment, GDP, liquidity indicators.
- Reddit: retail sentiment and narrative shifts.
- StockTwits: trader chatter.
- Company investor relations pages: earnings releases and presentations.

## 5. Provider Abstraction Layer

Each data source should implement a shared interface.

```text
MarketDataProvider
  get_quote(symbol)
  get_history(symbol, range)
  get_top_gainers(limit)

NewsProvider
  get_company_news(symbol, from_date, to_date)
  get_market_news(topic)

FilingProvider
  get_recent_filings(symbol)
  get_insider_trades(symbol)

MacroProvider
  get_macro_series(series_id)

SocialProvider
  get_mentions(symbol)
  get_sentiment(symbol)
```

Provider behavior:

- Primary provider should be tried first.
- Fallback providers should fill missing fields.
- Results should include provider name and timestamp.
- Rate-limit errors should be stored and summarized.
- A failed provider should not kill the daily run.

## 6. Memory Design

### 6.1 Memory Goals

Memory should improve both efficiency and quality:

- Avoid re-processing the same news repeatedly.
- Compare today with previous days.
- Track narratives over time.
- Remember prior alerts and whether they were useful.
- Provide context for the LLM reasoning layer.

### 6.2 Memory Layers

Use three memory layers.

#### Short-Term Run Memory

Scope: one daily or hourly run.

Stores:

- Raw quotes.
- Raw news.
- Retrieved filings.
- Social posts.
- Intermediate extracted events.
- Final WhatsApp message.

Current fit:

- Existing daily JSON and Markdown files can continue serving this layer.

#### Structured Historical Memory

Scope: many days or months.

Storage:

- SQLite for MVP.
- Postgres later.

Tables:

```text
runs
symbols
quotes
price_history
news
filings
social_mentions
technical_indicators
events
narratives
alerts
analyses
provider_health
```

Use cases:

- Compare today's price move against recent history.
- Detect repeated headlines.
- Track alerts by symbol.
- Measure provider reliability.

#### Semantic Memory

Scope: long-term agent reasoning.

Storage:

- Qdrant or ChromaDB.

Content:

- News summaries.
- Filing summaries.
- Earnings call summaries.
- Prior daily analyses.
- Narrative descriptions.

Retrieval examples:

- "What has the agent said about NVDA AI demand this month?"
- "Which stocks have been linked to AI infrastructure?"
- "Has this SEC filing topic appeared before?"

### 6.3 Memory Efficiency Rules

To reduce repeated work:

- Hash every news URL and headline.
- Skip embedding duplicate content.
- Store provider responses with TTL.
- Summarize large documents once, then reuse summaries.
- Keep raw content separate from extracted events.
- Only send the LLM new or changed information.

## 7. Event Intelligence Layer

The major upgrade is not more data; it is event intelligence.

Pipeline:

```text
Raw news / filing / social post
  -> clean text
  -> extract event
  -> classify event type
  -> link entities
  -> store event
  -> compare with memory
  -> reason about impact
```

Event schema:

```text
event_id
symbol
company
event_type
headline
summary
source
published_at
entities
sentiment
confidence
market_impact
related_symbols
dedupe_hash
```

Example event types:

- Earnings beat or miss.
- Guidance raise or cut.
- Product launch.
- Analyst upgrade or downgrade.
- Insider buy or sell.
- SEC investigation.
- Acquisition.
- Macro shock.
- Sector narrative shift.

## 8. New Agent Skills

### 8.1 News Clustering Skill

Goal:

- Group multiple headlines about the same event.
- Prevent duplicated news from consuming message space and LLM tokens.

Inputs:

- Recent headlines.
- Source URLs.
- Published times.
- Existing event memory.

Outputs:

- Cluster title.
- Representative headline.
- Source count.
- First seen and latest seen time.
- A short summary.

### 8.2 Narrative Tracking Skill

Goal:

- Track market stories across days.

Examples:

- AI infrastructure demand.
- Datacenter power bottleneck.
- EV margin pressure.
- Cloud capex acceleration.
- Rate-cut expectations.

Outputs:

- Narrative name.
- Direction: strengthening, weakening, stable.
- Related symbols.
- Supporting events.
- Contradicting events.
- Confidence.

### 8.3 Cross-Stock Reasoning Skill

Goal:

- Infer second-order effects.

Examples:

```text
NVDA rises on AI infrastructure demand
  -> possible beneficiaries: AMD, SMCI, ANET, VRT, ETN
  -> possible constraints: power, cooling, networking
```

Outputs:

- Primary symbol.
- Related winners.
- Related losers.
- Reasoning chain.
- Confidence.

### 8.4 SEC Filing Reader Skill

Goal:

- Detect material filings and summarize what changed.

Priority filings:

- 8-K.
- 10-Q.
- 10-K.
- Form 4.
- S-1.

Outputs:

- Filing type.
- Why it matters.
- Key risk or opportunity.
- Related prior filing if available.

### 8.5 Macro Context Skill

Goal:

- Connect macro changes to stock moves.

Inputs:

- FRED series.
- Treasury rates.
- CPI.
- Jobs data.
- Dollar index if available.

Outputs:

- Macro regime.
- Likely impact on growth stocks, banks, energy, small caps.
- Watchlist-specific relevance.

### 8.6 Alert Prioritization Skill

Goal:

- Decide what deserves a WhatsApp alert.

Inputs:

- Price move.
- Volume anomaly.
- Event severity.
- Sentiment shift.
- Prior memory.

Outputs:

- Alert level: none, watch, important, urgent.
- Reason.
- Suggested user action: read, watch, investigate, ignore.

## 9. Reasoning Prompt Design

The LLM should receive structured inputs, not raw dumps.

Prompt shape:

```text
You are an OpenClaw financial intelligence agent.

Inputs:
- Watchlist quotes
- Technical indicators
- Clustered events
- SEC filing changes
- Social sentiment
- Macro context
- Relevant memory from prior runs

Tasks:
1. Summarize important developments.
2. Detect unusual movements.
3. Explain likely causes with uncertainty.
4. Compare against historical memory.
5. Identify related stocks and second-order effects.
6. Assign alert level and confidence.
7. Generate a concise WhatsApp message in the user's language.

Rules:
- Do not give direct financial advice.
- Separate facts from interpretation.
- Mention missing or stale data.
- Prefer concise, source-grounded reasoning.
```

## 10. Storage Design

### 10.1 MVP Storage

Keep SQLite for now.

Add tables:

```text
provider_health
filings
social_mentions
events
narratives
event_clusters
memory_retrievals
```

### 10.2 Future Storage

When the agent grows:

- Move SQLite to Postgres.
- Add Qdrant for embeddings.
- Optionally add a graph layer for entity-event relationships.

Graph relationships:

```text
Company -> Event
Event -> Narrative
Narrative -> Sector
Company -> Supplier
Company -> Competitor
Event -> RelatedCompany
```

## 11. Scheduling Design

Recommended stages:

### Daily MVP

- Run once after market close.
- Send one concise WhatsApp message.
- Save memory and structured data.

### Hourly Upgrade

- Run hourly during market hours.
- Only send alert if something meaningful changes.
- Avoid repeating unchanged news.

### Event-Driven Future

Trigger urgent analysis if:

- A watchlist stock moves more than 5%.
- A filing appears.
- A news cluster reaches high severity.
- Social sentiment spikes.
- Volume anomaly appears.

## 12. Notification Design

WhatsApp should stay concise.

Recommended Chinese message structure:

```text
美股智能更新 - YYYY-MM-DD

关注列表
NVDA $225.32 -1.93% | 5日动量 N/A

今日重点
1. NVDA: AI 基础设施叙事仍在延续，但今日股价偏弱。
2. TSLA: 短期表现较弱，需关注交付和利润率叙事。

事件与记忆
- 今日未发现新的重大 SEC 文件。
- AI 基础设施叙事：稳定。

操作提醒
NVDA: 观察，不触发紧急警报。

备注：仅供信息参考，不构成投资建议。
```

## 13. Implementation Roadmap

### Phase 1: Reliable Ingestion

- Add Finnhub as primary provider.
- Keep Yahoo and Stooq as fallback providers.
- Add provider health tracking.
- Add response caching and TTL.
- Add SEC EDGAR filing ingestion.

### Phase 2: Memory Efficiency

- Add news deduplication by URL/headline hash.
- Add event table.
- Add daily memory retrieval.
- Add "what changed since yesterday" comparison.
- Store provider errors and stale-data warnings.

### Phase 3: Skills

- Add news clustering.
- Add narrative tracking.
- Add cross-stock reasoning.
- Add SEC filing reader.
- Add alert prioritization.

### Phase 4: Semantic Memory

- Add Qdrant or ChromaDB.
- Embed event summaries, filing summaries, and daily analyses.
- Retrieve top relevant memories before reasoning.

### Phase 5: Production Upgrade

- Move from SQLite to Postgres if needed.
- Add Polygon for paid market data if real-time reliability becomes important.
- Add dashboard views for narratives, alerts, and symbol history.

## 14. Recommended Next Step

The best next implementation step is:

```text
Finnhub primary provider
+ provider health table
+ response cache
+ news dedupe
+ event extraction schema
```

This gives the biggest reliability and reasoning improvement without overbuilding the system.

