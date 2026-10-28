# PKP 3.0 – Paiso Ka Ped signals

A signal engine and Streamlit dashboard based on the **Paiso Ka Ped (PKP) 3.0 with Option Trading** videos
(Fire in India, Parts 1 & 2).

> Educational tool, not financial advice. Options carry real risk, especially cash-secured puts.

## What it does

**ETF tree (Part 1)** – accumulate a Nifty ETF (default `NIFTYBEES.NS`) and book profits:

| Signal | Rule |
|---|---|
| SIP | On every SIP day buy `sip_amount / price` units |
| BID (buy the dip) | Bid #n fires when notional P/L ≤ −(first dip % × n) of the PKP average price; amount = n × first bid amount |
| SELL | When notional profit ≥ minimum profit, sell just under the profit; base investment never shrinks; bid count resets to 0 |

**Option selling (Part 2)** – Nifty and Bank Nifty:

- Strikes from the largest / second-largest expiry-to-expiry move (monthly: 2 years; weekly: 12 and 52 weeks), pro-rated for days left.
- **Covered-call flag:** green only if ETF holding ≥ 1 lot of the index *and* the ETF breaks even before the safest strike.
- Premium filter: monthly ≥ ₹1,000 per lot, weekly ≥ ₹400 per lot.
- Cash-secured put recovery calculator, RSI, and up/down-week bias.

## Daily signal screen

The **📅 Today** tab (the landing tab) shows what to do today: SIP due, buy-the-dip bid, profit-booking sell,
and whether covered calls are allowed with the safest strikes. Set your SIP schedule (weekly or monthly) in the
sidebar; a missed SIP stays "due" until you log it in the ledger. Each day's signals are appended to
`daily_signals.csv` (shown under *Signal history*). Prices refresh every 15 minutes, or use *Refresh data now*.

## Paper vs real ledger

The sidebar **Ledger** switch toggles between **Real** (your `pkp_ledger.csv`) and **Paper (simulated)**. Paper mode
replays the signal engine on history (`paper_tree.py`) so you can watch the signals without risking money; generate it
with the sidebar button. Paper mode keeps its own ledger and signal history and shows a warning banner.

## Files

| File | Purpose |
|---|---|
| `pkp_signals.py` | Signal engine + CLI |
| `app.py` | Streamlit UI |
| `test_pkp.py` | Checks the maths against the videos' worked examples |
| `pkp_ledger.csv` | Your trades: `date,type,price,units` (type = SIP / BID / SELL) |

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

streamlit run app.py            # dashboard
python pkp_signals.py signals   # CLI signals
python pkp_signals.py backtest --years 5
python test_pkp.py              # sanity checks
```

## Deploy on Streamlit Community Cloud (free)

1. Make sure the code is on GitHub (this repo: `yash1709/pkpOT`, branch `main`).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Click **Create app** → **Deploy a public app from GitHub**.
4. Fill in:
   - **Repository:** `yash1709/pkpOT`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **Python version:** 3.11 or 3.12 (under *Advanced settings*)
5. Click **Deploy**. Streamlit installs `requirements.txt` and gives you a URL like
   `https://<your-app>.streamlit.app`. Every `git push` to `main` redeploys automatically.

If the repo is private, grant Streamlit access to private repos when GitHub asks.

### Things to know when deployed

- **The ledger is not permanent.** The Cloud filesystem resets when the app restarts or redeploys, so trades saved
  from the UI can disappear. Keep the real ledger in `pkp_ledger.csv` and commit it to the repo, or ask for a
  database / Google Sheets backend.
- **Public apps are visible to anyone with the URL.** Your trades would be too. Use a private app (invite only),
  or run locally for real positions.
- **Data comes from Yahoo Finance** (`yfinance`) and can be delayed or occasionally rate-limited; the app caches
  prices for 15 minutes.
- **Premiums are manual.** No free live option chain is wired in; enter premium per unit from your broker.
- **Verify lot sizes** in the sidebar (Nifty 65 per the video; Bank Nifty 30 is an assumption).

### Other ways to deploy

- **Docker / any VPS:** `pip install -r requirements.txt && streamlit run app.py --server.port 8501 --server.address 0.0.0.0`
- **Hugging Face Spaces:** create a Streamlit Space and push the same files.

