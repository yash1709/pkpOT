"""PKP 3.0 (Paiso Ka Ped) signal engine - replica of the Fire in India sheet logic.

Part 1 of the strategy: ETF "tree" (SIP + Buy-the-Dip "bids" + profit booking "sell").
Part 2 of the strategy: option selling on the index (covered calls / cash-secured puts)
                        with strike selection from historical max expiry-to-expiry moves.

Usage:
    python pkp_signals.py signals [--index NIFTY|BANKNIFTY] [--call-premium X] [--put-premium Y]
    python pkp_signals.py backtest [--years 5]

The trade ledger lives in pkp_ledger.csv (date,type,price,units) with type in SIP/BID/SELL.
Educational tool, not financial advice.
"""
import argparse
import math
import os
import warnings

warnings.filterwarnings("ignore")
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "pkp_ledger.csv")

# ---- Yellow cells of the sheet -------------------------------------------------
CONFIG = {
    "etf": "NIFTYBEES.NS",
    "sip_amount": 10000,        # D3
    "min_profit": 1000,         # minimum notional profit (Rs) before a sell is suggested
    "bid_base_amount": 2500,    # first buy-the-dip amount; n-th bid = n * base
    "bid_pct": 2.0,             # first bid at -2% from PKP avg, n-th bid at -2n%
}
INDEXES = {
    "NIFTY": {"ticker": "^NSEI", "lot": 65, "strike_step": 50},
    "BANKNIFTY": {"ticker": "^NSEBANK", "lot": 30, "strike_step": 100},  # lot size: verify
}
# premium floors from the video (Rs per lot)
MIN_MONTHLY_PREMIUM = 1000
MIN_WEEKLY_PREMIUM = 400


# ---- data -----------------------------------------------------------------------
def close_series(ticker, years=3):
    df = yf.download(ticker, period=f"{years}y", interval="1d", auto_adjust=False, progress=False)
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s = s.dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))


# ---- PKP tree (ETF) -------------------------------------------------------------
def load_ledger():
    if not os.path.exists(LEDGER):
        return pd.DataFrame(columns=["date", "type", "price", "units"])
    return pd.read_csv(LEDGER)


def pkp_state(ledger):
    """Base investment never decreases; sells only remove units (so PKP avg price rises)."""
    base, units, booked, last_bid = 0.0, 0, 0.0, 0
    for r in ledger.itertuples():
        t = str(r.type).upper()
        if t in ("SIP", "BID"):
            base += r.price * r.units
            units += r.units
            if t == "BID":
                last_bid += 1
        elif t == "SELL":
            units -= r.units
            booked += r.price * r.units
            last_bid = 0  # bid cycle resets on every sell
    return {"base": base, "units": units, "booked": booked, "last_bid": last_bid}


def pkp_signals(price, cfg=CONFIG):
    st = pkp_state(load_ledger())
    out = {"state": st}
    sip_qty = int(cfg["sip_amount"] // price)
    out["sip"] = {"buy_units": sip_qty, "note": "Do this on every SIP day (weekly/monthly) regardless of price."}
    if st["units"] <= 0:
        out["note"] = "Tree not planted yet: start with SIP (add rows to pkp_ledger.csv after buying)."
        return out
    value = st["units"] * price
    profit = value - st["base"]
    pct = profit / st["base"] * 100
    avg = st["base"] / st["units"]
    out.update(value=value, profit=profit, profit_pct=pct, pkp_avg=avg)

    n = st["last_bid"] + 1
    trig_pct = -cfg["bid_pct"] * n
    amt = cfg["bid_base_amount"] * n
    out["next_bid"] = {"n": n, "trigger_pct": trig_pct, "trigger_price": avg * (1 + trig_pct / 100),
                       "units": int(amt // price), "amount": amt, "eligible": pct <= trig_pct}
    if profit >= cfg["min_profit"]:
        units = min(int(profit // price), st["units"])  # book just under the notional profit
        out["sell"] = {"units": units, "amount": units * price, "eligible": units > 0}
    else:
        out["sell"] = {"units": 0, "amount": 0, "eligible": False}
    return out


# ---- Option selling -------------------------------------------------------------
def monthly_expiries(idx):
    """Last Tuesday of each month; if not a trading day, previous trading day (as in the sheet)."""
    out = []
    for p in pd.period_range(idx[0], idx[-1], freq="M"):
        d = p.end_time.normalize()
        while d.weekday() != 1:
            d -= timedelta(days=1)
        prev = idx[idx <= d]
        if len(prev):
            out.append(prev[-1])
    return sorted(set(out))


def move_series(s, kind):
    if kind == "monthly":
        ex = monthly_expiries(s.index)
        px = s.reindex(ex).dropna()
    else:  # weekly: close on each Tuesday (or last trading day before it)
        px = s.resample("W-TUE").last().dropna()
    return (px.pct_change().dropna() * 100)


def round_strike(x, step, up):
    return (math.ceil(x / step) if up else math.floor(x / step)) * step


def option_signals(name, call_prem=None, put_prem=None):
    ix = INDEXES[name]
    s = close_series(ix["ticker"], 3)
    spot = float(s.iloc[-1])
    today = s.index[-1].date()
    lot = ix["lot"]
    step = ix["strike_step"]
    one_lot_value = spot * lot

    # next monthly expiry = last Tuesday of this/next month
    d = date(today.year, today.month, 28) + timedelta(days=8)
    d = d.replace(day=1) - timedelta(days=1)
    while d.weekday() != 1:
        d -= timedelta(days=1)
    if d <= today:
        d = date(today.year + (today.month == 12), today.month % 12 + 1, 28) + timedelta(days=8)
        d = d.replace(day=1) - timedelta(days=1)
        while d.weekday() != 1:
            d -= timedelta(days=1)
    days_left = (d - today).days

    # 2-year monthly data
    m = move_series(s[s.index >= s.index[-1] - pd.Timedelta(days=730)], "monthly")
    gains = m[m > 0].sort_values(ascending=False)
    losses = m[m < 0].sort_values()
    scale = days_left / 30.0 if days_left < 30 else 1.0
    res = {"index": name, "spot": spot, "rsi": rsi(s), "lot": lot, "one_lot_value": one_lot_value,
           "next_monthly_expiry": d, "days_left": days_left, "monthly": {}, "weekly": {}}

    pkp = pkp_signals(float(close_series(CONFIG["etf"], 1).iloc[-1]))
    holding = pkp.get("value", 0.0)
    npct = pkp.get("profit_pct", 0.0)

    def side_block(moves, scale_):
        r = {}
        for tag, v in (("max", moves.iloc[0]), ("2nd_max", moves.iloc[1])):
            pct = abs(v) * scale_
            r[tag] = {"move_pct": pct}
        return r

    # Monthly CALL / PUT strikes
    mc = side_block(gains, scale)
    mp = side_block(losses, scale)
    for k, b in mc.items():
        b["strike"] = round_strike(spot * (1 + b["move_pct"] / 100), step, up=True)
    for k, b in mp.items():
        b["strike"] = round_strike(spot * (1 - b["move_pct"] / 100), step, up=False)
    res["monthly"] = {"call": mc, "put": mp}

    # Weekly (Nifty only): 12-week and 52-week windows, prorated to days until the *next* week expiry
    if name == "NIFTY":
        w = move_series(s, "weekly")
        nxt = today + timedelta(days=(1 - today.weekday()) % 7 or 7)
        wk_days = (nxt + timedelta(days=7) - today).days  # the expiry after the nearest one
        for lab, n in (("12w", 12), ("52w", 52)):
            ww = w.tail(n)
            g, l = ww[ww > 0].sort_values(ascending=False), ww[ww < 0].sort_values()
            sc = wk_days / 7.0
            res["weekly"][lab] = {
                "days": wk_days,
                "call_strike": round_strike(spot * (1 + g.iloc[0] * sc / 100), step, True),
                "call_move_pct": g.iloc[0] * sc,
                "put_strike": round_strike(spot * (1 - abs(l.iloc[0]) * sc / 100), step, False),
                "put_move_pct": abs(l.iloc[0]) * sc,
            }
        last12 = w.tail(12)
        res["weekly"]["up_weeks_12"] = int((last12 > 0).sum())
        res["weekly"]["down_weeks_12"] = int((last12 < 0).sum())

    # Covered-call safety flag (two checks from the sheet)
    safest = mc["max"]
    c1 = holding >= one_lot_value
    c2 = (npct + safest["move_pct"]) > 0  # ETF breaks even before the strike is reached
    if not c1:
        flag = "RED: ETF holding < 1 lot of the index - do NOT sell calls yet."
    elif not c2:
        flag = "RED: notional loss is bigger than distance to safest strike - call not properly covered."
    else:
        flag = "GREEN: safe to consider covered calls."
    res["covered_call_flag"] = flag
    res["covered_call_ok"] = c1 and c2
    res["holding_value"] = holding

    # Premium screens (user supplies premium per unit from the option chain)
    if call_prem is not None:
        tot = call_prem * lot
        res["call_signal"] = ("SELL CALL" if res["covered_call_ok"] and tot >= MIN_MONTHLY_PREMIUM
                              else "SKIP") + f" (premium/lot Rs {tot:,.0f}, min Rs {MIN_MONTHLY_PREMIUM})"
    if put_prem is not None:
        tot = put_prem * lot
        ps = mp["max"]
        loss = (ps["strike"] - spot * (1 - ps["move_pct"] / 100 * 1.0)) * lot
        res["put_signal"] = ("SELL PUT (needs cash for ETF if ITM)" if tot >= MIN_MONTHLY_PREMIUM
                             else "SKIP") + f" (premium/lot Rs {tot:,.0f}, min Rs {MIN_MONTHLY_PREMIUM})"
    return res


def csp_min_investment(strike, expected_close, spot_at_sale, lot):
    """Cash-secured-put recovery: invest loss / drop% in a *secondary* ETF so a rebound recovers the loss."""
    loss = max(strike - expected_close, 0) * lot
    drop = (spot_at_sale - expected_close) / spot_at_sale
    return loss / drop if drop > 0 else 0.0


# ---- Backtest of the ETF tree ---------------------------------------------------
def backtest(years=5, cfg=CONFIG, sip_every=21):
    s = close_series(cfg["etf"], years)
    base = units = booked = 0.0
    last_bid = 0
    sells = bids = sips = 0
    for i, (dt, p) in enumerate(s.items()):
        p = float(p)
        if i % sip_every == 0:
            q = int(cfg["sip_amount"] // p)
            base += q * p; units += q; sips += 1
        if units > 0:
            avg = base / units
            pct = (units * p - base) / base * 100
            n = last_bid + 1
            if pct <= -cfg["bid_pct"] * n:
                q = int(cfg["bid_base_amount"] * n // p)
                if q:
                    base += q * p; units += q; last_bid = n; bids += 1
            profit = units * p - base
            if profit >= cfg["min_profit"]:
                q = int(profit // p)
                if q:
                    units -= q; booked += q * p; sells += 1; last_bid = 0
    p = float(s.iloc[-1])
    return {"sips": sips, "bids": bids, "sells": sells, "base_invested": base, "units_left": units,
            "profit_booked": booked, "holding_value": units * p,
            "total_gain": booked + units * p - base}


# ---- CLI ------------------------------------------------------------------------
def fmt(x):
    return f"{x:,.2f}"


def cmd_signals(a):
    etf_px = float(close_series(CONFIG["etf"], 1).iloc[-1])
    p = pkp_signals(etf_px)
    print(f"=== PKP TREE ({CONFIG['etf']} @ {fmt(etf_px)}) ===")
    if "value" not in p:
        print(p["note"])
        print(f"SIP signal: buy {p['sip']['buy_units']} units (~Rs {CONFIG['sip_amount']:,}) on your SIP day")
    else:
        st = p["state"]
        print(f"Units {st['units']:.0f} | Base Rs {st['base']:,.0f} | PKP avg {fmt(p['pkp_avg'])} | "
              f"Value Rs {p['value']:,.0f} | Notional P/L Rs {p['profit']:,.0f} ({p['profit_pct']:.2f}%)")
        print(f"SIP    : buy {p['sip']['buy_units']} units on SIP day")
        b = p["next_bid"]
        print(f"BID #{b['n']} : {'*** BUY NOW ***' if b['eligible'] else 'wait'} - trigger {b['trigger_pct']:.0f}% "
              f"(price <= {fmt(b['trigger_price'])}), buy {b['units']} units (Rs {b['amount']:,})")
        s = p["sell"]
        print(f"SELL   : {'*** SELL ' + str(s['units']) + ' units (~Rs ' + format(s['amount'], ',.0f') + ') & reset bids ***' if s['eligible'] else 'not eligible (profit < Rs ' + str(CONFIG['min_profit']) + ')'}")

    for name in ([a.index] if a.index else INDEXES):
        r = option_signals(name, a.call_premium, a.put_premium)
        print(f"\n=== OPTIONS: {name} spot {fmt(r['spot'])} | RSI {r['rsi']:.1f} | lot {r['lot']} "
              f"(1 lot = Rs {r['one_lot_value']:,.0f}) ===")
        print(f"Next monthly expiry {r['next_monthly_expiry']} ({r['days_left']} days)")
        print(f"{r['covered_call_flag']}  (ETF holding Rs {r['holding_value']:,.0f})")
        for side in ("call", "put"):
            for tag, b in r["monthly"][side].items():
                print(f"  monthly {side.upper():4} {tag:7}: strike {b['strike']:>7,.0f}  ({b['move_pct']:.2f}% away)")
        for lab, w in r["weekly"].items():
            if isinstance(w, dict):
                print(f"  weekly {lab:3} ({w['days']}d): CALL {w['call_strike']:,.0f} ({w['call_move_pct']:.2f}%) | "
                      f"PUT {w['put_strike']:,.0f} ({w['put_move_pct']:.2f}%)")
        if r["weekly"]:
            u, d = r["weekly"]["up_weeks_12"], r["weekly"]["down_weeks_12"]
            print(f"  last 12 weeks: {u} up / {d} down -> {'PUTs' if u > d else 'CALLs'} historically safer")
        for k in ("call_signal", "put_signal"):
            if k in r:
                print(f"  {k}: {r[k]}")
    print("\nCheck option-chain premium: monthly >= Rs 1000/lot, weekly >= Rs 400/lot, else skip. "
          "Pass --call-premium/--put-premium (per unit) to screen automatically.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("signals")
    s.add_argument("--index", choices=INDEXES.keys())
    s.add_argument("--call-premium", type=float)
    s.add_argument("--put-premium", type=float)
    b = sub.add_parser("backtest")
    b.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "signals":
        cmd_signals(a)
    else:
        for k, v in backtest(a.years).items():
            print(f"{k:16}: {v:,.2f}")


if __name__ == "__main__":
    main()
