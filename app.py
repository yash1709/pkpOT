"""Streamlit UI for the PKP 3.0 signal engine.  Run: streamlit run app.py"""
import pandas as pd
import streamlit as st

import pkp_signals as k

st.set_page_config(page_title="PKP 3.0 Signals", page_icon="ðŸŒ³", layout="wide")
st.title("ðŸŒ³ PKP 3.0 â€“ Paiso Ka Ped signals")
st.caption("ETF tree (SIP + buy-the-dip + profit booking) and index option selling. Educational, not financial advice.")

# ---- sidebar: the "yellow cells" ------------------------------------------------
with st.sidebar:
    st.header("Settings")
    k.CONFIG["etf"] = st.text_input("ETF ticker (Yahoo)", k.CONFIG["etf"])
    k.CONFIG["sip_amount"] = st.number_input("SIP amount (â‚¹)", 0, step=1000, value=k.CONFIG["sip_amount"])
    k.CONFIG["min_profit"] = st.number_input("Min profit to book (â‚¹)", 0, step=100, value=k.CONFIG["min_profit"])
    k.CONFIG["bid_base_amount"] = st.number_input("First bid amount (â‚¹)", 0, step=500, value=k.CONFIG["bid_base_amount"])
    k.CONFIG["bid_pct"] = st.number_input("First bid dip %", 0.5, 20.0, float(k.CONFIG["bid_pct"]), 0.5)
    st.subheader("Lot sizes")
    k.INDEXES["NIFTY"]["lot"] = st.number_input("Nifty lot", 1, value=k.INDEXES["NIFTY"]["lot"])
    k.INDEXES["BANKNIFTY"]["lot"] = st.number_input("Bank Nifty lot (verify!)", 1, value=k.INDEXES["BANKNIFTY"]["lot"])

tab_tree, tab_opt, tab_bt = st.tabs(["ETF tree", "Options", "Backtest"])


@st.cache_data(ttl=900, show_spinner="Fetching pricesâ€¦")
def etf_price(ticker):
    return float(k.close_series(ticker, 1).iloc[-1])


@st.cache_data(ttl=900, show_spinner="Computing option signalsâ€¦")
def opt(name, cp, pp, etf, sip, mp, bb, bp, nlot, blot):
    # extra args only exist so the cache refreshes when settings change
    return k.option_signals(name, cp or None, pp or None)


# ---- ETF tree -------------------------------------------------------------------
with tab_tree:
    price = etf_price(k.CONFIG["etf"])
    st.subheader("Trade ledger")
    st.caption("Record every SIP / BID / SELL you actually execute. type âˆˆ SIP, BID, SELL.")
    led = k.load_ledger()
    edited = st.data_editor(
        led, num_rows="dynamic", width="stretch",
        column_config={"type": st.column_config.SelectboxColumn(options=["SIP", "BID", "SELL"], required=True)},
    )
    if st.button("ðŸ’¾ Save ledger"):
        edited.dropna(how="all").to_csv(k.LEDGER, index=False)
        st.success("Saved.")
        st.rerun()

    p = k.pkp_signals(price)
    st.subheader(f"Signals â€“ {k.CONFIG['etf']} @ â‚¹{price:,.2f}")
    if "value" in p:
        s = p["state"]
        c = st.columns(5)
        c[0].metric("Units", f"{s['units']:,.0f}")
        c[1].metric("Base invested", f"â‚¹{s['base']:,.0f}")
        c[2].metric("PKP avg price", f"â‚¹{p['pkp_avg']:,.2f}")
        c[3].metric("Value", f"â‚¹{p['value']:,.0f}")
        c[4].metric("Notional P/L", f"â‚¹{p['profit']:,.0f}", f"{p['profit_pct']:.2f}%")
    else:
        st.info(p["note"])

    st.success(f"**SIP:** buy {p['sip']['buy_units']} units (~â‚¹{k.CONFIG['sip_amount']:,}) on your SIP day.")
    if "next_bid" in p:
        b = p["next_bid"]
        msg = (f"**BID #{b['n']}:** trigger {b['trigger_pct']:.0f}% (price â‰¤ â‚¹{b['trigger_price']:,.2f}) â€“ "
               f"buy {b['units']} units (â‚¹{b['amount']:,})")
        (st.error("ðŸ”” BUY NOW â€“ " + msg) if b["eligible"] else st.info("Wait â€“ " + msg))
        sl = p["sell"]
        if sl["eligible"]:
            st.error(f"ðŸ”” **SELL {sl['units']} units** (~â‚¹{sl['amount']:,.0f}) and reset the bid cycle to 0.")
        else:
            st.info(f"**SELL:** not eligible (profit below â‚¹{k.CONFIG['min_profit']:,}).")

# ---- Options --------------------------------------------------------------------
with tab_opt:
    name = st.radio("Index", list(k.INDEXES), horizontal=True)
    c1, c2 = st.columns(2)
    cp = c1.number_input("Call premium per unit (from option chain, 0 = skip)", 0.0, step=1.0)
    pp = c2.number_input("Put premium per unit (0 = skip)", 0.0, step=1.0)
    r = opt(name, cp, pp, k.CONFIG["etf"], k.CONFIG["sip_amount"], k.CONFIG["min_profit"],
            k.CONFIG["bid_base_amount"], k.CONFIG["bid_pct"],
            k.INDEXES["NIFTY"]["lot"], k.INDEXES["BANKNIFTY"]["lot"])

    c = st.columns(4)
    c[0].metric("Spot", f"{r['spot']:,.2f}")
    c[1].metric("RSI(14)", f"{r['rsi']:.1f}")
    c[2].metric("1 lot value", f"â‚¹{r['one_lot_value']:,.0f}")
    c[3].metric("Next monthly expiry", f"{r['next_monthly_expiry']}", f"{r['days_left']} days", delta_color="off")
    (st.success if r["covered_call_ok"] else st.error)(
        f"{r['covered_call_flag']}  (ETF holding â‚¹{r['holding_value']:,.0f})")

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
        st.write(f"Last 12 weeks: **{u} up / {d} down** â†’ {'puts' if u > d else 'calls'} historically safer.")
    for key in ("call_signal", "put_signal"):
        if key in r:
            st.write(f"**{key.replace('_', ' ').title()}:** {r[key]}")
    st.caption("Premium floors from the video: monthly â‰¥ â‚¹1,000 per lot, weekly â‰¥ â‚¹400 per lot.")

    with st.expander("Cash-secured put recovery calculator"):
        a, b_, c_ = st.columns(3)
        strike = a.number_input("Put strike sold", value=float(r["monthly"]["put"]["max"]["strike"]))
        exp = b_.number_input("Expected expiry close", value=float(strike) - 200)
        spot0 = c_.number_input("Spot when sold", value=float(r["spot"]))
        need = k.csp_min_investment(strike, exp, spot0, k.INDEXES[name]["lot"])
        st.write(f"Minimum ETF investment (secondary ETF) to recover the loss on a rebound: **â‚¹{need:,.0f}**")

# ---- Backtest -------------------------------------------------------------------
with tab_bt:
    years = st.slider("Years", 1, 10, 5)
    every = st.slider("SIP every N trading days", 5, 63, 21)
    if st.button("Run backtest"):
        res = k.backtest(years, sip_every=every)
        c = st.columns(4)
        c[0].metric("Base invested", f"â‚¹{res['base_invested']:,.0f}")
        c[1].metric("Profit booked", f"â‚¹{res['profit_booked']:,.0f}")
        c[2].metric("Holding value", f"â‚¹{res['holding_value']:,.0f}")
        c[3].metric("Total gain", f"â‚¹{res['total_gain']:,.0f}")
        st.write(f"{res['sips']:.0f} SIPs Â· {res['bids']:.0f} bids Â· {res['sells']:.0f} sells Â· "
                 f"{res['units_left']:,.0f} units left")

