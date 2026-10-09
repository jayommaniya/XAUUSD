import asyncio, hmac, json, logging, os, time, uuid
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import IntegrityError
import db, engine
from providers import NullNews, make_price_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xau")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
POLL_S = float(os.getenv("POLL_SECONDS", "10"))
ALLOWED = {s.strip() for s in os.getenv("ALLOWED_SYMBOLS", "XAUUSD").split(",")}
provider = make_price_provider()
news = NullNews()
ms = lambda: int(time.time() * 1000)


class Alert(BaseModel):
    v: int = 1
    symbol: str = Field(max_length=20)
    tf: str = Field(max_length=5)
    t: int
    price: float = Field(gt=0)
    dir: Literal["BUY", "SELL"]
    mode: Literal["5m", "10m", "both"]
    score: float = Field(ge=0, le=100)
    dir5: int = Field(ge=-1, le=1)
    score5: float = Field(ge=0, le=100)
    dir10: int = Field(ge=-1, le=1)
    score10: float = Field(ge=0, le=100)
    entry: float = Field(gt=0)
    sl: float = Field(gt=0)
    tp: float = Field(gt=0)
    rr: float = Field(gt=0)
    atr: float = Field(gt=0)
    rsi: float = Field(ge=0, le=100)
    horizon_min: int = Field(ge=1, le=60)
    reasons: str = Field(default="", max_length=600)


class Hub:
    def __init__(self): self.ws = set()
    async def send(self, msg):
        for w in list(self.ws):
            try: await w.send_json(msg)
            except Exception: self.ws.discard(w)
hub = Hub()


def admin(authorization: str = Header(default="")):
    tok = authorization.removeprefix("Bearer ").strip()
    if not ADMIN_TOKEN or not hmac.compare_digest(tok.encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(401, "unauthorized")


def limits():
    return engine.Limits(min_score=float(db.get_setting("min_score", "65")), min_rr=float(db.get_setting("min_rr", "1.5")))


async def tracker():
    """Polls the price feed ONLY while a paper trade is open (keeps free API quotas safe)."""
    while True:
        await asyncio.sleep(POLL_S)
        try:
            t = db.open_trade()
            if not t: continue
            now = ms()
            price = await asyncio.to_thread(provider.price, "XAUUSD")
            if price is None:
                if now > t["expires_at_ms"] + 60_000:
                    up = dict(status="NO_DATA", closed_at_ms=now, hold_s=(now - t["opened_at_ms"]) // 1000)
                else: continue
            else:
                up = engine.step_trade(t, price, now)
            db.update_trade(t["id"], up)
            await hub.send({"type": "trade", "id": t["id"], **up})
        except Exception as e:
            log.error("tracker error: %s", type(e).__name__)


@asynccontextmanager
async def lifespan(app):
    if len(WEBHOOK_SECRET) < 16 or WEBHOOK_SECRET == "CHANGE_ME" or len(ADMIN_TOKEN) < 16:
        raise RuntimeError("Set WEBHOOK_SECRET and ADMIN_TOKEN (16+ chars) in the environment")
    db.init(os.getenv("DATABASE_URL", "sqlite:///./signals.db"), os.path.join(os.path.dirname(__file__), "schema.sql"))
    task = asyncio.create_task(tracker())
    yield
    task.cancel()

app = FastAPI(title="XAU signal backend", lifespan=lifespan)


@app.get("/health")
def health(): return {"ok": True}


@app.post("/webhook/tradingview")
async def webhook(request: Request):
    raw = await request.body()
    if len(raw) > 8192: raise HTTPException(413, "too large")
    try: data = json.loads(raw)
    except Exception: raise HTTPException(400, "bad json")
    if not isinstance(data, dict): raise HTTPException(400, "bad json")
    secret = str(data.pop("secret", ""))
    if not hmac.compare_digest(secret.encode(), WEBHOOK_SECRET.encode()):
        log.warning("webhook rejected: bad secret")
        raise HTTPException(401, "unauthorized")
    try: a = Alert(**data)
    except ValidationError as e:
        log.warning("webhook invalid payload: %d errors", e.error_count())
        raise HTTPException(422, "invalid payload")
    now, ad, lim = ms(), a.model_dump(), limits()
    reason = None if a.symbol in ALLOWED else "symbol_not_allowed"
    reason = reason or engine.check_signal(ad, now, lim) or news.blackout(now)
    if not reason and db.get_setting("paper_on", "1") != "1": reason = "paper_off"
    if not reason:
        n, pnl = db.today_stats(now - now % 86_400_000)
        reason = engine.check_limits(n, pnl, db.open_trade() is not None, lim)
    fill = None
    if not reason:
        px = await asyncio.to_thread(provider.price, a.symbol)
        fill = px if px is not None else a.entry
        reason = engine.check_fill(ad, fill, lim)
    sid = str(uuid.uuid4())
    row = dict(id=sid, symbol=a.symbol, tf=a.tf, signal_time_ms=a.t, received_at_ms=now, direction=a.dir, mode=a.mode, score=a.score,
               dir5=a.dir5, score5=a.score5, dir10=a.dir10, score10=a.score10, entry=a.entry, sl=a.sl, tp=a.tp, rr=a.rr, atr=a.atr,
               rsi=a.rsi, horizon_min=a.horizon_min, reasons=a.reasons, raw_json=json.dumps(data),
               status="REJECTED" if reason else "ACCEPTED", reject_reason=reason)
    try: db.insert("signals", row)
    except IntegrityError: return {"status": "duplicate"}
    out = {"status": row["status"], "reason": reason, "signal_id": sid}
    if not reason:
        tid = str(uuid.uuid4())
        db.insert("trades", dict(id=tid, signal_id=sid, direction=a.dir, entry=fill, sl=a.sl, tp=a.tp, opened_at_ms=now,
                                 expires_at_ms=now + a.horizon_min * 60_000, status="OPEN", mfe=0, mae=0))
        out["trade_id"] = tid
    await hub.send({"type": "signal", **{k: v for k, v in row.items() if k != "raw_json"}, "trade_id": out.get("trade_id")})
    return out


@app.get("/api/signals", dependencies=[Depends(admin)])
def signals(limit: int = 100):
    return db.q("SELECT * FROM signals ORDER BY signal_time_ms DESC LIMIT :n", n=min(limit, 500))


@app.get("/api/trades", dependencies=[Depends(admin)])
def trades(limit: int = 100):
    return db.q("SELECT * FROM trades ORDER BY opened_at_ms DESC LIMIT :n", n=min(limit, 500))


@app.get("/api/state", dependencies=[Depends(admin)])
def state():
    s = db.q("SELECT * FROM signals ORDER BY signal_time_ms DESC LIMIT 1")
    return {"latest_signal": s[0] if s else None, "open_trade": db.open_trade(),
            "paper_on": db.get_setting("paper_on", "1") == "1", "min_score": limits().min_score, "min_rr": limits().min_rr}


class SettingsIn(BaseModel):
    paper_on: bool | None = None
    min_score: float | None = Field(default=None, ge=0, le=100)
    min_rr: float | None = Field(default=None, ge=0.5, le=10)


@app.post("/api/settings", dependencies=[Depends(admin)])
def settings(s: SettingsIn):
    for k, v in s.model_dump(exclude_none=True).items():
        db.set_setting(k, int(v) if k == "paper_on" else v)
    return state()


@app.websocket("/ws")
async def ws(w: WebSocket, token: str = ""):
    if not ADMIN_TOKEN or not hmac.compare_digest(token.encode(), ADMIN_TOKEN.encode()):
        await w.close(code=4401); return
    await w.accept(); hub.ws.add(w)
    try:
        while True: await w.receive_text()
    except WebSocketDisconnect:
        hub.ws.discard(w)
