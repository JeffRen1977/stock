# Stock Agent Instructions

This project is an OpenClaw-based stock WhatsApp alert agent.

- Use OpenClaw's WhatsApp channel for delivery.
- Do not add third-party WhatsApp providers.
- Store secrets and phone numbers in `.env`; do not commit real keys or private numbers.
- Save every generated daily stock update under `memory/daily_stock/YYYY-MM-DD/`.
- Save structured market/news/analysis records in local SQLite under `data/`.
- Keep dashboard artifacts under `dashboard/`.
- Keep the agent focused on informational stock updates, not trading or financial advice.
- After Python code changes, run `python3 -m compileall src`.
- For a local dry run, use `PYTHONPATH=src python3 -m stock_whatsapp_agent.main --dry-run`.
