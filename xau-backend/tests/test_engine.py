from engine import Limits, check_fill, check_limits, check_signal, step_trade

NOW = 1_700_000_000_000
LIM = Limits()
def alert(**k):
    a = dict(t=NOW - 5_000, score=80, dir="BUY", entry=3350.0, sl=3347.0, tp=3356.0)
    a.update(k); return a

def test_valid(): assert check_signal(alert(), NOW, LIM) is None
def test_stale(): assert check_signal(alert(t=NOW - 300_000), NOW, LIM) == "stale_signal"
def test_future(): assert check_signal(alert(t=NOW + 300_000), NOW, LIM) == "timestamp_in_future"
def test_low_score(): assert check_signal(alert(score=50), NOW, LIM) == "score_below_min"
def test_wrong_side(): assert check_signal(alert(sl=3353.0), NOW, LIM) == "invalid_levels"
def test_low_rr(): assert check_signal(alert(tp=3351.0), NOW, LIM) == "rr_below_min"
def test_sell_valid(): assert check_signal(alert(dir="SELL", sl=3353.0, tp=3344.0), NOW, LIM) is None
def test_limits():
    assert check_limits(0, 0, True, LIM) == "trade_already_open"
    assert check_limits(10, 0, False, LIM) == "max_trades_day"
    assert check_limits(1, -3.0, False, LIM) == "max_daily_loss"
    assert check_limits(1, -1.0, False, LIM) is None
def test_fill():
    assert check_fill(alert(), 3350.4, LIM) is None
    assert check_fill(alert(), 3352.0, LIM) == "slippage_too_large"

def trade(**k):
    t = dict(direction="BUY", entry=3350.0, sl=3347.0, tp=3356.0, opened_at_ms=NOW, expires_at_ms=NOW + 300_000, mfe=0, mae=0)
    t.update(k); return t

def test_win():
    u = step_trade(trade(), 3356.5, NOW + 60_000)
    assert u["status"] == "WIN" and u["pnl_r"] > 2 and u["hold_s"] == 60
def test_loss_sell():
    u = step_trade(trade(direction="SELL", sl=3353.0, tp=3344.0), 3353.2, NOW + 1_000)
    assert u["status"] == "LOSS" and u["pnl_r"] < -1
def test_expiry_and_excursions():
    u = step_trade(trade(), 3351.0, NOW + 1000)
    assert "status" not in u and u["mfe"] == 1.0 and u["mae"] == 0
    u = step_trade(trade(mfe=1.0), 3348.5, NOW + 1000)
    assert u["mae"] == 1.5 and u["mfe"] == 1.0
    assert step_trade(trade(), 3351.0, NOW + 300_000)["status"] == "EXPIRED"
