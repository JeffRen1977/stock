# Stock WhatsApp Agent

Python agent that sends a daily US stock update to one or more WhatsApp accounts.

It currently supports:

- Watchlist quotes.
- Latest news for each selected stock.
- Daily top gainers when using Yahoo Finance.
- Simple technical indicators: SMA, RSI, and 5-day momentum.
- Heuristic reasoning for stance, confidence, alerts, and actions.
- WhatsApp delivery to multiple recipients through OpenClaw.
- Daily memory saved under `memory/daily_stock/YYYY-MM-DD/`.
- Structured run history in local SQLite.
- Static chart widget, defaulting to NVDA.

## Setup

Create a virtual environment and install dependencies:

```bash
cd /home/renjeff/Documents/projects/Stock
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Create your local environment file:

```bash
cp .env.example .env
```

Then edit `.env` with your WhatsApp recipient numbers and stock watchlist. The default Yahoo Finance provider does not need a stock API key.

Example recipients:

```bash
WHATSAPP_TO=+1xxxxxxxxxx,+1yyyyyyyyyy
```

The stock agent uses the same OpenClaw WhatsApp channel style as the WeChat agent. Make sure WhatsApp is linked:

```bash
openclaw gateway start
openclaw channels login --channel whatsapp --verbose
openclaw channels status
```

## Run

Preview the message without sending:

```bash
stock-whatsapp-agent --dry-run
```

Send the message:

```bash
stock-whatsapp-agent
```

Without package installation, run directly from source:

```bash
PYTHONPATH=src python3 -m stock_whatsapp_agent.main --dry-run
PYTHONPATH=src python3 -m stock_whatsapp_agent.main
```

## Smoke Test Checklist

Run this checklist before starting a larger upgrade:

```bash
cd /home/renjeff/Documents/projects/Stock
python3 -m compileall src
API_REQUEST_DELAY_SECONDS=0 PYTHONPATH=src python3 -m stock_whatsapp_agent.main --dry-run
git status --short
```

Confirm:

- The dry run prints a stock update.
- At least fallback prices are available for the watchlist.
- `memory/daily_stock/YYYY-MM-DD/stock_update.md` is written.
- `memory/daily_stock/YYYY-MM-DD/stock_update.json` is written.
- `data/stock_agent.sqlite3` exists.
- `.env` does not appear in `git status --short`.

## Data Provider

Use Yahoo Finance for the no-key version:

```bash
STOCK_API_PROVIDER=yahoo
PRIMARY_MARKET_PROVIDER=yahoo
FALLBACK_MARKET_PROVIDERS=stooq,yahoo
PROVIDER_TIMEOUT_SECONDS=8
QUOTE_CACHE_TTL_SECONDS=300
NEWS_CACHE_TTL_SECONDS=21600
HISTORY_CACHE_TTL_SECONDS=86400
```

Yahoo Finance supports watchlist quotes, stock news search, and top gainers in this implementation without a local API key. Alpha Vantage and Finnhub remain available only if you explicitly configure a `STOCK_API_KEY`.

To use Finnhub as the primary provider:

```bash
PRIMARY_MARKET_PROVIDER=finnhub
FINNHUB_API_KEY=your_finnhub_key
```

Finnhub adds company news, recommendation trends, and earnings calendar signals when the API key is configured. If Finnhub is selected without a key, the agent falls back to Yahoo/Stooq instead of stopping the run.

The default config waits between requests:

```bash
API_REQUEST_DELAY_SECONDS=13
```

If you see `N/A`, the provider may have returned no data or temporarily blocked the request. For faster testing, reduce this delay.

Provider health is saved to SQLite for every quote, news, top-gainers, and history call. This makes rate limits and fallback behavior visible during later tuning.

Provider responses are cached in SQLite using separate TTL values for quotes, news, and history. News items are deduplicated by URL or headline/source hash before being saved or shown.

News is also converted into structured events when possible. Events include type, sentiment, confidence, impact score, related symbols, and the source news hash. They are saved to SQLite and daily memory, and high-impact events can influence the agent's alert decision.

SEC EDGAR ingestion is enabled by default for important filings such as `8-K`, `10-Q`, `10-K`, Form `4`, and `S-1`. Set a real contact in `.env`:

```bash
ENABLE_SEC_INGESTION=true
SEC_USER_AGENT="OpenClawStockAgent/0.1 your-email@example.com"
SEC_FILINGS_LIMIT=5
```

Recent filings are saved to SQLite and daily memory, and important filings are converted into structured events.

Memory retrieval can compare current events with prior analyses, recent alerts, and recent events so repeated information is treated differently from genuinely new information. It is disabled by default while the local workflow is being stabilized:

```bash
ENABLE_MEMORY_RETRIEVAL=true
```

## Memory

Each run saves the generated message and raw stock data:

```text
memory/daily_stock/YYYY-MM-DD/stock_update.md
memory/daily_stock/YYYY-MM-DD/stock_update.json
data/stock_agent.sqlite3
dashboard/nvda_chart.html
```

Disable this only if needed:

```bash
SAVE_DAILY_MEMORY=false
```

The SQLite database stores quotes, news, top gainers, price history, technical indicators, and agent analyses. The chart widget is a standalone HTML file that can be opened in a browser.

## Scheduling

For a local Linux machine, add a cron job after the US market closes.

Example for 1:30 PM Pacific time, Monday through Friday:

```cron
30 13 * * 1-5 cd /home/renjeff/Documents/projects/Stock && .venv/bin/stock-whatsapp-agent >> agent.log 2>&1
```

Make sure the machine timezone matches the schedule you expect.

## Security

Do not commit `.env`. It contains private WhatsApp phone numbers and may contain API keys if you switch providers.
