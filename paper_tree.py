"""Paper-trade a PKP ETF tree by replaying the *real* signal engine day by day.

Writes paper_ledger.csv (never touches your real pkp_ledger.csv) and compares PKP with a plain-SIP benchmark.
Usage: python paper_tree.py [--years 5] [--sip-every 21] [--etf NIFTYBEES.NS]
"""
import argparse
import os
import warnings
from datetime import date

import pandas as pd

import pkp_signals as k

warnings.filterwarnings("ignore")
OUT = os.path.join(k.HERE, "paper_ledger.csv")


def xirr(flows):
    """flows: [(date, amount)], negative = money in. Bisection on annual rate."""
    t0 = flows[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - t0).days / 365) for d, a in flows)
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def simulate(etf, years, sip_every):
    s = k.close_series(etf, years)
    rows = []
    real_load = k.load_ledger
    k.load_ledger = lambda: pd.DataFrame(rows, columns=["date", "type", "price", "units"])  # engine reads this
    try:
        return _run(s, rows, etf, sip_every)
    finally:
        k.load_ledger = real_load  # never leave the engine pointing at the simulation


def _run(s, rows, etf, sip_every):
    flows, sip_flows = [], []
    sip_units = 0
    peak_cash = cash = 0.0
    worst_dd = 0.0
    for i, (dt, px) in enumerate(s.items()):
        px, d = float(px), dt.date()
        if i % sip_every == 0:                                   # SIP day
            q = int(k.CONFIG["sip_amount"] // px)
            if q:
                rows.append((d, "SIP", px, q)); flows.append((d, -q * px)); cash += q * px
                sip_units += q; sip_flows.append((d, -q * px))
        sig = k.pkp_signals(px)                                  # <- real engine
        if "next_bid" in sig and sig["next_bid"]["eligible"] and sig["next_bid"]["units"]:
            q = sig["next_bid"]["units"]
            rows.append((d, "BID", px, q)); flows.append((d, -q * px)); cash += q * px
            sig = k.pkp_signals(px)
        if "sell" in sig and sig["sell"]["eligible"]:
            q = sig["sell"]["units"]
            rows.append((d, "SELL", px, q)); flows.append((d, q * px)); cash -= q * px
        peak_cash = max(peak_cash, cash)
        st = k.pkp_state(k.load_ledger())
        if st["base"]:
            worst_dd = min(worst_dd, (st["units"] * px - st["base"]) / st["base"] * 100)
    last_d, last_px = s.index[-1].date(), float(s.iloc[-1])
    st = k.pkp_state(k.load_ledger())
    flows.append((last_d, st["units"] * last_px))
    sip_flows.append((last_d, sip_units * last_px))
    pd.DataFrame(rows, columns=["date", "type", "price", "units"]).to_csv(OUT, index=False)
    return {
        "rows": rows, "state": st, "last_px": last_px,
        "pkp_invested": -sum(a for _, a in flows if a < 0), "pkp_booked": sum(a for _, a in flows[:-1] if a > 0),
        "pkp_final": st["units"] * last_px, "pkp_xirr": xirr(flows), "peak_net_cash": peak_cash,
        "worst_notional_pct": worst_dd,
        "sip_invested": -sum(a for _, a in sip_flows if a < 0), "sip_final": sip_units * last_px,
        "sip_xirr": xirr(sip_flows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--sip-every", type=int, default=21)
    ap.add_argument("--etf", default=k.CONFIG["etf"])
    a = ap.parse_args()
    k.CONFIG["etf"] = a.etf
    r = simulate(a.etf, a.years, a.sip_every)
    kinds = pd.Series([x[1] for x in r["rows"]]).value_counts()
    print(f"Paper tree on {a.etf}, {a.years}y, SIP every {a.sip_every} trading days -> {OUT}")
    print(f"Trades: {dict(kinds)}")
    st = r["state"]
    print(f"Open position: {st['units']:.0f} units, base Rs {st['base']:,.0f}, "
          f"value Rs {r['pkp_final']:,.0f}, profit already booked Rs {r['pkp_booked']:,.0f}")
    print(f"\n{'':18}{'PKP tree':>14}{'Plain SIP':>14}")
    print(f"{'Cash put in':18}{r['pkp_invested']:>14,.0f}{r['sip_invested']:>14,.0f}")
    print(f"{'Final value':18}{r['pkp_final'] + r['pkp_booked']:>14,.0f}{r['sip_final']:>14,.0f}   (PKP = holding + cash booked)")
    print(f"{'XIRR':18}{r['pkp_xirr'] * 100:>13.1f}%{r['sip_xirr'] * 100:>13.1f}%")
    print(f"{'Peak capital out':18}{r['peak_net_cash']:>14,.0f}")
    print(f"Worst notional drawdown vs base: {r['worst_notional_pct']:.1f}%")


if __name__ == "__main__":
    main()
