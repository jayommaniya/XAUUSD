"""Pure decision logic: no I/O, easy to test. Prices are in USD per oz."""
from dataclasses import dataclass


@dataclass
class Limits:
    min_score: float = 65.0
    min_rr: float = 1.5
    max_age_ms: int = 120_000
    max_slip: float = 1.0
    max_trades_day: int = 10
    max_daily_loss_r: float = 3.0


def rr_of(entry, sl, tp):
    risk = abs(entry - sl)
    return abs(tp - entry) / risk if risk > 0 else 0.0


def levels_ok(direction, entry, sl, tp):
    return sl < entry < tp if direction == "BUY" else tp < entry < sl


def check_signal(a: dict, now_ms: int, lim: Limits):
    """Return a rejection reason, or None if the alert is acceptable."""
    if now_ms - a["t"] > lim.max_age_ms:
        return "stale_signal"
    if a["t"] - now_ms > 60_000:
        return "timestamp_in_future"
    if a["score"] < lim.min_score:
        return "score_below_min"
    if not levels_ok(a["dir"], a["entry"], a["sl"], a["tp"]):
        return "invalid_levels"
    if rr_of(a["entry"], a["sl"], a["tp"]) < lim.min_rr:
        return "rr_below_min"
    return None


def check_limits(today_trades: int, today_pnl_r: float, has_open: bool, lim: Limits):
    if has_open:
        return "trade_already_open"
    if today_trades >= lim.max_trades_day:
        return "max_trades_day"
    if today_pnl_r <= -lim.max_daily_loss_r:
        return "max_daily_loss"
    return None


def check_fill(a: dict, fill: float, lim: Limits):
    """Paper fill = first price seen after the alert; reject if it moved too far."""
    if abs(fill - a["entry"]) > lim.max_slip:
        return "slippage_too_large"
    if not levels_ok(a["dir"], fill, a["sl"], a["tp"]):
        return "levels_invalid_at_fill"
    if rr_of(fill, a["sl"], a["tp"]) < lim.min_rr:
        return "rr_below_min_at_fill"
    return None


def step_trade(t: dict, price: float, now_ms: int) -> dict:
    """Update MFE/MAE and close on SL/TP/expiry. Exit uses the observed price (can be worse than SL)."""
    d = 1 if t["direction"] == "BUY" else -1
    move = (price - t["entry"]) * d
    up = {"mfe": max(t["mfe"] or 0, move), "mae": max(t["mae"] or 0, -move)}
    status = None
    if (price <= t["sl"]) if d > 0 else (price >= t["sl"]):
        status = "LOSS"
    elif (price >= t["tp"]) if d > 0 else (price <= t["tp"]):
        status = "WIN"
    elif now_ms >= t["expires_at_ms"]:
        status = "EXPIRED"
    if status:
        risk = abs(t["entry"] - t["sl"])
        up.update(status=status, exit_price=price, closed_at_ms=now_ms,
                  pnl_r=move / risk, hold_s=(now_ms - t["opened_at_ms"]) // 1000)
    return up
