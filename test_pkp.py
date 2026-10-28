"""Checks the PKP tree maths against the worked example in the video (Part 1)."""
import pandas as pd

import pkp_signals as k

# video: 34 units bought @35 -> avg 35; price 34.04 => -2.75% => bid 1 eligible
k.load_ledger = lambda: pd.DataFrame([("2025-11-07", "SIP", 35.0, 34)], columns=["date", "type", "price", "units"])
p = k.pkp_signals(34.04)
assert p["next_bid"]["n"] == 1 and p["next_bid"]["eligible"], p
assert round(p["next_bid"]["trigger_pct"]) == -2

# after bid 1 the next trigger is -4% with double the amount
k.load_ledger = lambda: pd.DataFrame(
    [("d", "SIP", 100.0, 10), ("d", "BID", 98.0, 25)], columns=["date", "type", "price", "units"])
p = k.pkp_signals(100.0)
assert p["next_bid"]["n"] == 2 and p["next_bid"]["trigger_pct"] == -4 and p["next_bid"]["amount"] == 5000

# sell just under notional profit, base never shrinks, bid cycle resets
k.load_ledger = lambda: pd.DataFrame(
    [("d", "SIP", 100.0, 100), ("d", "SELL", 120.0, 10)], columns=["date", "type", "price", "units"])
st = k.pkp_state(k.load_ledger())
assert st["base"] == 10000 and st["units"] == 90 and st["last_bid"] == 0
p = k.pkp_signals(130.0)
assert p["sell"]["eligible"] and p["sell"]["units"] == int((90 * 130 - 10000) // 130)

# cash-secured put recovery example: 24000 put, close 23800, spot 26203 -> ~Rs 1.4L
inv = k.csp_min_investment(24000, 23800, 26203, 65)
assert 135_000 < inv < 150_000, inv
print("all PKP checks passed")
