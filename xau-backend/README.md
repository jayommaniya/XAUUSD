# XAU signal backend (Phase 2)
Run locally: `pip install -r requirements.txt`, copy `.env.example` to `.env` and fill it, then
`set -a; . ./.env; set +a; uvicorn main:app --reload`. Tests: `pytest`.
TradingView alert: Condition = the indicator, choose "Any alert() function call", Webhook URL = `https://YOUR-HOST/webhook/tradingview`. The script supplies the JSON itself, so the message box is ignored. Set the indicator's secret input to the same value as WEBHOOK_SECRET.
Postgres: set DATABASE_URL to your Supabase connection string; schema is created on startup.
API (Authorization: Bearer ADMIN_TOKEN): GET /api/state, /api/signals, /api/trades; POST /api/settings {paper_on,min_score,min_rr}; WS /ws?token=...
