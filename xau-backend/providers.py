"""Swappable edges: price feed and news filter. Add new classes, change env, nothing else moves."""
import logging
import os
import httpx

log = logging.getLogger("xau")


class NullPrice:
    def price(self, symbol):
        return None


class TwelveData:
    def __init__(self, key):
        self.key = key

    def price(self, symbol):
        try:
            r = httpx.get("https://api.twelvedata.com/price", params={"symbol": "XAU/USD", "apikey": self.key}, timeout=5)
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception as e:  # log the type only: httpx messages can contain the URL (and the API key)
            log.warning("price fetch failed: %s", type(e).__name__)
            return None


class NullNews:
    def blackout(self, now_ms):  # Phase 7: return a reason string during high-impact events
        return None


def make_price_provider():
    if os.getenv("PRICE_PROVIDER") == "twelvedata" and os.getenv("TWELVEDATA_API_KEY"):
        return TwelveData(os.environ["TWELVEDATA_API_KEY"])
    return NullPrice()
