"""Streamlit UI for the PKP 3.0 signal engine.  Run: streamlit run app.py"""
import os
from datetime import date

import pandas as pd
import streamlit as st

import paper_tree
import pkp_signals as k

REAL_LEDGER = k.LEDGER
PAPER_LEDGER = paper_tree.OUT

st.set_page_config(page_title="PKP 3.0 Signals", page_icon="🌳", layout="wide")
st.title("🌳 PKP 3.0 – Paiso Ka Ped signals")
st.caption("ETF tree (SIP + buy-the-dip + profit booking) and index option selling. Educational, not financial advice.")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# ---- sidebar: the "yellow cells" ------------------------------------------------
with st.sidebar:
    mode = st.radio("Ledger", ["Real", "Paper (simulated)"], help="Paper = simulated tree for testing; Real = your trades.")
    paper = mode.startswith("Paper")
    k.LEDGER = PAPER_LEDGER if paper else REAL_LEDGER  # every ledger read/write in the engine follows this
    if paper:
        st.warning("📝 Paper mode: simulated trades, do not trade on these signals.")
        yrs = st.slider("Simulate years", 1, 7, 5)
        if st.button("⚙️ (Re)generate paper tree"):
            with st.spinner("Replaying the engine on history…"):
                paper_tree.simulate(k.CONFIG["etf"], yrs, 21)
            st.cache_data.clear()
            st.rerun()
    st.header("Settings")
    k.CONFIG["etf"] = st.text_input("ETF ticker (Yahoo)", k.CONFIG["etf"])
    k.CONFIG["sip_amount"] = st.number_input("SIP amount (₹)", 0, step=1000, value=k.CONFIG["sip_amount"])
    k.CONFIG["min_profit"] = st.number_input("Min profit to book (₹)", 0, step=100, value=k.CONFIG["min_profit"])
    k.CONFIG["bid_base_amount"] = st.number_input("First bid amount (₹)", 0, step=500, value=k.CONFIG["bid_base_amount"])
    k.CONFIG["bid_pct"] = st.number_input("First bid dip %", 0.5, 20.0, float(k.CONFIG["bid_pct"]), 0.5)
    st.subheader("SIP schedule")
    sip_freq = st.radio("Frequency", ["Weekly", "Monthly"], horizontal=True)
    if sip_freq == "Weekly":
        sip_wd = WEEKDAYS.index(st.selectbox("SIP weekday", WEEKDAYS))
        sip_md = 1
    else:
        sip_md = st.number_input("SIP day of month", 1, 28, 1)
        sip_wd = 0
    st.subheader("Lot sizes")
    k.INDEXES["NIFTY"]["lot"] = st.number_input("Nifty lot", 1, value=k.INDEXES["NIFTY"]["lot"])
    k.INDEXES["BANKNIFTY"]["lot"] = st.number_input("Bank Nifty lot (verify!)", 1, value=k.INDEXES["BANKNIFTY"]["lot"])
    if st.button("🔄 Refresh data now"):
        st.cache_data.clear()
        st.rerun()

tab_today, tab_tree, tab_opt, tab_bt = st.tabs(["📅 Today", "ETF tree", "Options", "Backtest"])


@st.cache_data(ttl=900, show_spinner="Fetching prices…")
def etf_quote(ticker):
    s = k.close_series(ticker, 1)
    return float(s.iloc[-1]), s.index[-1].date()


@st.cache_data(ttl=900, show_spinner="Computing option signals…")
def opt(name, cp, pp, etf, sip, mp, bb, bp, nlot, blot, ledger_path, ledger_mtime):
    # extra args only exist so the cache refreshes when settings or the ledger change
    return k.option_signals(name, cp or None, pp or None)


def ledger_key():
    return k.LEDGER, os.path.getmtime(k.LEDGER) if os.path.exists(k.LEDGER) else 0.0


price, price_date = etf_quote(k.CONFIG["etf"])
today = date.today()
if paper and not os.path.exists(PAPER_LEDGER):
    st.info("No paper tree yet – click **(Re)generate paper tree** in the sidebar.")
    st.stop()
p = k.pkp_signals(price)
DAILY_LOG = os.path.join(k.HERE, "daily_signals_paper.csv" if paper else "daily_signals.csv")


# ---- Today (daily signal screen) ------------------------------------------------
with tab_today:
    st.subheader(f"Signals for {today:%A, %d %b %Y}" + ("  —  📝 PAPER" if paper else ""))
    if paper:
        st.warning("Paper mode: these signals come from a simulated ledger, not your real trades.")
    stale = (today - price_date).days
    st.caption(f"{k.CONFIG['etf']} last close ₹{price:,.2f} on {price_date:%d %b %Y}"
               + (f" — ⚠️ data is {stale} days old (weekend/holiday or feed delay)" if stale > 3 else ""))

    actions = []  # (kind, text)

    # 1) SIP
    due, sched = k.sip_due(today, sip_freq, sip_wd, sip_md)
    if due:
        actions.append(("buy", f"**SIP due** (scheduled {sched:%d %b}): buy **{p['sip']['buy_units']} units** "
                               f"of {k.CONFIG['etf']} (~₹{k.CONFIG['sip_amount']:,})."))
    else:
        actions.append(("ok", f"SIP: done for the cycle that started {sched:%d %b}. Next one is not due yet."))

    # 2) BID and 3) SELL
    if "next_bid" in p:
        b, sl = p["next_bid"], p["sell"]
        if b["eligible"]:
            actions.append(("buy", f"**BUY THE DIP – bid #{b['n']}:** buy **{b['units']} units** "
                                   f"(₹{b['amount']:,}) at ~₹{price:,.2f}."))
        else:
            actions.append(("ok", f"Bid #{b['n']}: wait. Triggers at ₹{b['trigger_price']:,.2f} "
                                  f"({b['trigger_pct']:.0f}% from PKP avg) – now {p['profit_pct']:.2f}%."))
        if sl["eligible"]:
            actions.append(("sell", f"**BOOK PROFIT:** sell **{sl['units']} units** (~₹{sl['amount']:,.0f}), "
                                    f"then reset bid cycle to 0 in the ledger."))
        else:
            actions.append(("ok", f"Sell: not eligible (notional profit ₹{p['profit']:,.0f} "
                                  f"< ₹{k.CONFIG['min_profit']:,})."))
    else:
        actions.append(("ok", "Bid / sell: no position in the ledger yet – start with the SIP."))

    # 4) Options
    opt_rows = []
    for name in k.INDEXES:
        try:
            r = opt(name, 0.0, 0.0, k.CONFIG["etf"], k.CONFIG["sip_amount"], k.CONFIG["min_profit"],
                    k.CONFIG["bid_base_amount"], k.CONFIG["bid_pct"],
                    k.INDEXES["NIFTY"]["lot"], k.INDEXES["BANKNIFTY"]["lot"], *ledger_key())
        except Exception as e:  # data hiccup should not blank the whole screen
            actions.append(("warn", f"{name}: option signals unavailable ({e})."))
            continue
        mc, mp = r["monthly"]["call"], r["monthly"]["put"]
        if r["covered_call_ok"]:
            actions.append(("buy", f"**{name} covered call allowed:** sell monthly CALL at "
                                   f"**{mc['max']['strike']:,.0f}** (safest) or {mc['2nd_max']['strike']:,.0f} "
                                   f"if premium ≥ ₹{k.MIN_MONTHLY_PREMIUM:,}/lot. Expiry {r['next_monthly_expiry']}."))
        else:
            actions.append(("warn", f"{name} covered calls: **blocked** – {r['covered_call_flag']}"))
        w12 = r["weekly"].get("12w") if r["weekly"] else None
        opt_rows.append({
            "Index": name, "Spot": round(r["spot"], 2), "RSI": round(r["rsi"], 1),
            "Call (monthly safest)": mc["max"]["strike"], "Put (monthly safest)": mp["max"]["strike"],
            "Weekly call 12w": w12["call_strike"] if w12 else None,
            "Weekly put 12w": w12["put_strike"] if w12 else None,
            "Call allowed": "✅" if r["covered_call_ok"] else "⛔",
        })

    # headline banner
    n_act = sum(1 for kd, _ in actions if kd in ("buy", "sell"))
    if n_act:
        st.error(f"🔔 {n_act} action(s) today")
    else:
        st.success("✅ No trades today – nothing to do.")
    for kind, text in actions:
        {"buy": st.warning, "sell": st.error, "ok": st.info, "warn": st.info}[kind](
            ("🟢 " if kind == "buy" else "🔴 " if kind == "sell" else "⚪ ") + text)

    if opt_rows:
        st.markdown("**Option levels**")
        st.dataframe(pd.DataFrame(opt_rows), width="stretch", hide_index=True)
        st.caption("Check the real premium in your option chain: monthly ≥ ₹1,000/lot, weekly ≥ ₹400/lot, else skip. "
                   "Put selling needs cash set aside – see the Options tab.")

    # daily log (one row per date, latest run wins)
    row = {"date": today.isoformat(), "price_date": price_date.isoformat(), "etf_price": round(price, 2),
           "signals": " | ".join(t.replace("**", "") for kd, t in actions if kd in ("buy", "sell", "warn"))}
    try:
        hist = pd.read_csv(DAILY_LOG) if os.path.exists(DAILY_LOG) else pd.DataFrame(columns=row)
        hist = pd.concat([hist[hist["date"] != row["date"]], pd.DataFrame([row])], ignore_index=True)
        hist.to_csv(DAILY_LOG, index=False)
    except OSError:
        hist = pd.DataFrame([row])
    with st.expander("📜 Signal history"):
        st.dataframe(hist.sort_values("date", ascending=False), width="stretch", hide_index=True)


# ---- ETF tree -------------------------------------------------------------------
with tab_tree:
    st.subheader("Trade ledger" + (" (paper)" if paper else ""))
    st.caption("Record every SIP / BID / SELL you actually execute. type ∈ SIP, BID, SELL.")
    led = k.load_ledger()
    edited = st.data_editor(
        led, num_rows="dynamic", width="stretch",
        column_config={"type": st.column_config.SelectboxColumn(options=["SIP", "BID", "SELL"], required=True)},
    )
    if st.button("💾 Save ledger"):
        edited.dropna(how="all").to_csv(k.LEDGER, index=False)
        st.success("Saved.")
        st.rerun()

    st.subheader(f"Position – {k.CONFIG['etf']} @ ₹{price:,.2f}")
    if "value" in p:
        s = p["state"]
        c = st.columns(5)
        c[0].metric("Units", f"{s['units']:,.0f}")
        c[1].metric("Base invested", f"₹{s['base']:,.0f}")
        c[2].metric("PKP avg price", f"₹{p['pkp_avg']:,.2f}")
        c[3].metric("Value", f"₹{p['value']:,.0f}")
        c[4].metric("Notional P/L", f"₹{p['profit']:,.0f}", f"{p['profit_pct']:.2f}%")
    else:
        st.info(p["note"])


# ---- Options --------------------------------------------------------------------
with tab_opt:
    name = st.radio("Index", list(k.INDEXES), horizontal=True)
    c1, c2 = st.columns(2)
    cp = c1.number_input("Call premium per unit (from option chain, 0 = skip)", 0.0, step=1.0)
    pp = c2.number_input("Put premium per unit (0 = skip)", 0.0, step=1.0)
    r = opt(name, cp, pp, k.CONFIG["etf"], k.CONFIG["sip_amount"], k.CONFIG["min_profit"],
            k.CONFIG["bid_base_amount"], k.CONFIG["bid_pct"],
            k.INDEXES["NIFTY"]["lot"], k.INDEXES["BANKNIFTY"]["lot"], *ledger_key())

    c = st.columns(4)
    c[0].metric("Spot", f"{r['spot']:,.2f}")
    c[1].metric("RSI(14)", f"{r['rsi']:.1f}")
    c[2].metric("1 lot value", f"₹{r['one_lot_value']:,.0f}")
    c[3].metric("Next monthly expiry", f"{r['next_monthly_expiry']}", f"{r['days_left']} days", delta_color="off")
    (st.success if r["covered_call_ok"] else st.error)(
        f"{r['covered_call_flag']}  (ETF holding ₹{r['holding_value']:,.0f})")

    rows = []
    for side in ("call", "put"):
        for tag, b in r["monthly"][side].items():
            rows.append({"Expiry": "Monthly", "Side": side.upper(), "Basis": tag,
                         "Strike": b["strike"], "Distance %": round(b["move_pct"], 2)})
    for lab, w in r["weekly"].items():
        if isinstance(w, dict):
            rows.append({"Expiry": f"Weekly ({w['days']}d)", "Side": "CALL", "Basis": lab,
                         "Strike": w["call_strike"], "Distance %": round(w["call_move_pct"], 2)})
            rows.append({"Expiry": f"Weekly ({w['days']}d)", "Side": "PUT", "Basis": lab,
                         "Strike": w["put_strike"], "Distance %": round(w["put_move_pct"], 2)})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if r["weekly"]:
        u, d = r["weekly"]["up_weeks_12"], r["weekly"]["down_weeks_12"]
        st.write(f"Last 12 weeks: **{u} up / {d} down** → {'puts' if u > d else 'calls'} historically safer.")
    for key in ("call_signal", "put_signal"):
        if key in r:
            st.write(f"**{key.replace('_', ' ').title()}:** {r[key]}")
    st.caption("Premium floors from the video: monthly ≥ ₹1,000 per lot, weekly ≥ ₹400 per lot.")

    with st.expander("Cash-secured put recovery calculator"):
        a, b_, c_ = st.columns(3)
        strike = a.number_input("Put strike sold", value=float(r["monthly"]["put"]["max"]["strike"]))
        exp = b_.number_input("Expected expiry close", value=float(strike) - 200)
        spot0 = c_.number_input("Spot when sold", value=float(r["spot"]))
        need = k.csp_min_investment(strike, exp, spot0, k.INDEXES[name]["lot"])
        st.write(f"Minimum ETF investment (secondary ETF) to recover the loss on a rebound: **₹{need:,.0f}**")


# ---- Backtest -------------------------------------------------------------------
with tab_bt:
    years = st.slider("Years", 1, 10, 5)
    every = st.slider("SIP every N trading days", 5, 63, 21)
    if st.button("Run backtest"):
        res = k.backtest(years, sip_every=every)
        c = st.columns(4)
        c[0].metric("Base invested", f"₹{res['base_invested']:,.0f}")
        c[1].metric("Profit booked", f"₹{res['profit_booked']:,.0f}")
        c[2].metric("Holding value", f"₹{res['holding_value']:,.0f}")
        c[3].metric("Total gain", f"₹{res['total_gain']:,.0f}")
        st.write(f"{res['sips']:.0f} SIPs · {res['bids']:.0f} bids · {res['sells']:.0f} sells · "
                 f"{res['units_left']:,.0f} units left")
