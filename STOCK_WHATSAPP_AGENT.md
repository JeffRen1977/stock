# Stock WhatsApp OpenClaw Agent Design

## 1. Goal

Build one OpenClaw agent that collects daily US stock market information and sends a concise WhatsApp message to the user.

The agent should support two main information modes:

1. User-selected US stocks, for example AAPL, NVDA, TSLA, MSFT.
2. Daily top rising US stocks, for example the biggest gainers by percentage change during the latest trading day.

The first version should focus on reliable daily delivery, clear summaries, and simple configuration.

## 2. Core User Story

Every trading day, the user wants to receive a WhatsApp message with:

- Latest price information for selected US stocks.
- Daily percentage change and price movement.
- Latest stock-specific news for each selected stock.
- A list of the most rising US stocks for the day.
- A short AI-generated summary explaining what changed.

Example:

```text
US Stock Daily Update

Selected Stocks:
NVDA: $123.45, +2.34%
TSLA: $210.20, -1.18%
AAPL: $190.10, +0.85%

Latest News:
NVDA: AI chip demand remains strong, according to recent analyst commentary.
TSLA: Investors are watching delivery numbers and margin pressure.
AAPL: New product and services updates remain the main market focus.

Top Rising Stocks:
ABC: +18.20%
XYZ: +14.75%
DEF: +11.40%

Summary:
Technology stocks were stronger today, led by semiconductor names. NVDA gained after positive market sentiment around AI demand.
```

## 3. Main Features

### 3.1 Selected Stock Watchlist

The user can configure a list of US stock symbols.

Example configuration:

```json
{
  "watchlist": ["AAPL", "MSFT", "NVDA", "TSLA"],
  "timezone": "America/Los_Angeles",
  "send_time": "07:30"
}
```

The agent should fetch:

- Current or latest close price.
- Daily open, high, low, close.
- Daily change amount.
- Daily change percentage.
- Market cap or volume if available.
- Latest related news for each picked stock.

### 3.2 Daily Top Rising Stocks

The agent should fetch the top US market gainers each day.

Minimum fields:

- Ticker symbol.
- Company name.
- Latest price.
- Percentage gain.
- Trading volume.

The first version can return the top 5 rising stocks.

### 3.3 Per-Stock Latest News

For each selected stock, the agent should fetch the latest related news and include it in the WhatsApp message.

Minimum fields for each news item:

- Ticker symbol.
- News headline.
- News source.
- Published time.
- Short summary in one sentence.
- Source link, if available.

Recommended behavior:

- Include 1 to 3 latest news items per picked stock.
- Prefer news from the last 24 hours.
- If there is no recent news, show `No major recent news found`.
- Keep each stock's news section short so the WhatsApp message remains readable.
- Separate factual headlines from AI interpretation.

Example:

```text
NVDA News
1. Reuters, 08:15 AM: Nvidia shares rose as analysts highlighted continued AI chip demand.
2. CNBC, Yesterday: Investors are watching upcoming earnings guidance.
```

### 3.4 News Summary

After listing the latest news for each selected stock, the agent may add a short combined summary of the most important items.

The summary should be short and practical:

- Avoid long analysis.
- Avoid giving direct financial advice.
- Clearly mention uncertainty.
- Include source links if the message length allows.

### 3.5 WhatsApp Delivery

The agent sends the daily summary through WhatsApp by using OpenClaw's linked WhatsApp channel.

The WhatsApp account should be paired through OpenClaw:

```bash
openclaw gateway start
openclaw channels login --channel whatsapp --verbose
openclaw channels status
```

### 3.6 Scheduling

The agent should run automatically every trading day.

Recommended schedule:

- Morning before market open: send pre-market summary.
- After market close: send final daily summary.

For the first version, use one daily message after market close.

Suggested time:

```text
Monday-Friday, 1:30 PM Pacific Time
```

This is after the regular US market close at 1:00 PM Pacific Time.

## 4. Non-Goals For Version 1

The first version should not try to:

- Execute trades.
- Give personalized investment advice.
- Predict future stock prices.
- Manage a portfolio.
- Support every global market.
- Send high-frequency intraday alerts.

These can be added later after the daily summary is stable.

## 5. Proposed Architecture

```text
Scheduler
   |
   v
OpenClaw Stock Agent
   |
   +-- Stock Market Data Tool
   |
   +-- Stock News Tool
   |
   +-- Top Gainers Tool
   |
   +-- Summary Generator
   |
   v
WhatsApp Sender
   |
   v
User WhatsApp
```

## 6. Agent Responsibilities

The OpenClaw agent should:

1. Read the configured watchlist.
2. Fetch latest stock data.
3. Fetch top rising US stocks.
4. Fetch latest news for each selected stock.
5. Create a concise per-stock news section.
6. Create a concise daily summary.
7. Send the summary to WhatsApp.
8. Log success or failure.
9. Retry delivery if WhatsApp sending fails.

## 7. External Services

### 7.1 Stock Market Data API

Possible providers:

- Yahoo Finance public endpoints
- Polygon.io
- Finnhub
- Alpha Vantage
- Twelve Data
- IEX Cloud

Recommended starting option:

- Yahoo Finance public endpoints for the first no-key prototype.
- Finnhub or Alpha Vantage when an official API key is preferred.
- Polygon.io for more reliable production usage.

Required data endpoints:

- Quote by symbol.
- Company profile.
- Market movers or top gainers.
- Stock news.

### 7.2 WhatsApp Delivery

Required capabilities:

- Send text message.
- Use OpenClaw's linked WhatsApp session.
- Configure one or more recipient phone numbers.
- Send the same daily message to multiple WhatsApp accounts.

## 8. Configuration

Use environment variables for secrets:

```bash
STOCK_API_PROVIDER=yahoo

WHATSAPP_TO=+1xxxxxxxxxx,+1yyyyyyyyyy

WATCHLIST=AAPL,MSFT,NVDA,TSLA
TIMEZONE=America/Los_Angeles
SEND_TIME=13:30
```

Do not commit real phone numbers or optional API keys to the repository.

`WHATSAPP_TO` can contain multiple WhatsApp recipients separated by commas. The agent should loop through the list and send the same stock update message to each account.

## 9. Message Format

The WhatsApp message should be short enough to read quickly.

Recommended format:

```text
US Stock Daily Update - 2026-05-17

Watchlist
AAPL $190.10 +0.85%
MSFT $430.25 +1.10%
NVDA $123.45 +2.34%

Latest News By Stock
AAPL
- Bloomberg, 09:10 AM: Apple shares moved higher as investors watched new product demand.

MSFT
- CNBC, 08:45 AM: Microsoft gained as cloud and AI demand remained a market focus.

NVDA
- Reuters, 07:30 AM: Nvidia rose after analysts pointed to strong AI chip demand.

Top Gainers
ABC +18.20% $12.40
XYZ +14.75% $8.90
DEF +11.40% $22.10

News Summary
NVDA moved higher with continued AI sector strength.
TSLA declined after weaker delivery concerns.

Note: This is informational only, not financial advice.
```

## 10. Error Handling

The agent should handle common failures:

- Stock API unavailable.
- Invalid ticker symbol.
- Rate limit reached.
- WhatsApp API failure.
- One WhatsApp recipient fails while another succeeds.
- Missing configuration.
- Market closed or holiday.

Recommended behavior:

- Log the exact error.
- Retry temporary failures.
- Skip invalid symbols but continue processing the rest.
- Send to all configured WhatsApp accounts independently, so one failed recipient does not block the others.
- Send a short failure notification only if the whole daily job fails.

## 11. Data Quality Rules

The agent should:

- Include timestamp and timezone.
- Prefer official API fields over scraped web pages.
- Avoid sending stale data without warning.
- Mark delayed prices if the provider does not offer real-time data.
- Avoid claiming certainty about why a stock moved unless supported by news.

## 12. Security

Security requirements:

- Store API keys in environment variables or a secret manager.
- Never hard-code WhatsApp tokens.
- Never commit `.env` files.
- Keep logs free of tokens and private phone numbers.
- Use HTTPS APIs only.

## 13. Version 1 Implementation Plan

### Phase 1: Basic Daily Message

- Create project structure.
- Add configuration file support.
- Fetch stock quotes for the watchlist.
- Fetch latest news for each selected stock.
- Format a simple WhatsApp message.
- Send the message manually from a command.

### Phase 2: Top Gainers

- Add top rising stocks API integration.
- Include top 5 gainers in the message.
- Add fallback behavior if the endpoint fails.

### Phase 3: News Summary

- Improve per-stock latest news formatting.
- Generate short summary text.
- Add source links when available.

### Phase 4: Automation

- Add scheduler.
- Run automatically every trading day.
- Add logs and retry behavior.

### Phase 5: Production Hardening

- Add tests.
- Add monitoring.
- Add market holiday handling.
- Add failure notifications.

## 14. Open Questions

Before implementation, confirm:

1. Which stock symbols should be in the first watchlist?
2. Should the message be sent before market open, after market close, or both?
3. Which WhatsApp accounts should receive the stock update?
4. Which stock data provider should be used?
5. Should the agent send only English messages, or English and Chinese?
6. Where will the agent run: local computer, cloud server, or scheduled GitHub Action?

## 15. Recommended First Version

For the first working version:

- Use Python.
- Use Yahoo Finance public endpoints for stock data.
- Use OpenClaw WhatsApp channel for delivery.
- Send one message after market close.
- Configure watchlist through `.env`.
- Keep the OpenClaw agent focused on collecting, summarizing, and delivering information.

