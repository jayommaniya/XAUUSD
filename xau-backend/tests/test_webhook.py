import os, tempfile, time
os.environ.update(WEBHOOK_SECRET="s" * 20, ADMIN_TOKEN="a" * 20, DATABASE_URL="sqlite:///" + tempfile.mkdtemp() + "/t.db")
from fastapi.testclient import TestClient
import main

class Fake:
    def price(self, s): return 3350.2
main.provider = Fake()

def payload(**k):
    p = dict(v=1, secret="s" * 20, symbol="XAUUSD", tf="1", t=int(time.time() * 1000), price=3350.0, dir="BUY", mode="both", score=80,
             dir5=1, score5=80, dir10=1, score10=78, entry=3350.0, sl=3347.0, tp=3356.0, rr=2.0, atr=1.5, rsi=58, horizon_min=5, reasons="EMA9>EMA21;")
    p.update(k); return p

def test_flow():
    with TestClient(main.app) as c:
        assert c.post("/webhook/tradingview", json=payload(secret="wrong")).status_code == 401
        assert c.post("/webhook/tradingview", json=payload(score=500)).status_code == 422
        p = payload(); r = c.post("/webhook/tradingview", json=p).json()
        assert r["status"] == "ACCEPTED" and "trade_id" in r
        assert c.post("/webhook/tradingview", json=p).json()["status"] == "duplicate"
        r2 = c.post("/webhook/tradingview", json=payload(t=p["t"] + 1)).json()
        assert r2["reason"] == "trade_already_open"
        h = {"Authorization": "Bearer " + "a" * 20}
        assert c.get("/api/state").status_code == 401
        assert c.get("/api/state", headers=h).json()["open_trade"]["entry"] == 3350.2
        c.post("/api/settings", headers=h, json={"paper_on": False})
        assert c.get("/api/state", headers=h).json()["paper_on"] is False
