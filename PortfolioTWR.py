
"""
VIKA Portfolio TWR Tracker - v3
Changes included:
1. DD/MM/YY parsing (dayfirst=True)
2. Auto append .NS to tickers
3. Missing ticker reporting and CSV download
4. Stop calculations if any ticker has no price data
5. Proper cash ledger and portfolio valuation
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px

st.set_page_config(page_title="VIKA Portfolio TWR Tracker", layout="wide")
st.title("VIKA Portfolio TWR Tracker")

st.markdown("""
Upload:
1. Transactions (Date, Ticker, Action, Quantity, Price)
2. Cash Flows (Date, Amount)
3. Optional Nifty TRI CSVs (Date, Value)
""")

@st.cache_data
def read_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)

@st.cache_data
def get_prices(tickers, start, end):
    prices_dict = {}
    missing = []

    for ticker in tickers:
        fetched = False

        # Try ticker as-is and .BO fallback
        attempts = [ticker]
        if ticker.endswith(".NS"):
            attempts.append(ticker.replace(".NS", ".BO"))

        for sym in attempts:
            try:
                data = yf.download(
                    sym,
                    start=start,
                    end=end + pd.Timedelta(days=2),
                    auto_adjust=True,
                    progress=False
                )

                if data.empty:
                    continue

                close = data["Close"]

                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]

                close = close.dropna()

                if close.empty:
                    continue

                prices_dict[ticker] = close
                fetched = True
                break

            except Exception:
                pass

        if not fetched:
            missing.append(ticker)

    if not prices_dict:
        return pd.DataFrame(), missing

    prices = (
        pd.concat(prices_dict, axis=1)
        .sort_index()
        .ffill()
    )

    return prices, sorted(set(missing))


def annualise_twr(twr, days):
    if days <= 0:
        return np.nan
    return (1 + twr) ** (365 / days) - 1


def build_daily_ledger(tx, cf, prices):

    start = min(tx["Date"].min(), cf["Date"].min())
    end = prices.index.max()

    dates = pd.bdate_range(start, end)

    holdings = {t: 0.0 for t in tx["Ticker"].unique()}
    cash = 0.0

    tx_grp = {d: g for d, g in tx.groupby("Date")}
    cf_grp = cf.groupby("Date")["Amount"].sum().to_dict()

    rows = []

    for d in dates:

        if d in cf_grp:
            cash += float(cf_grp[d])

        if d in tx_grp:

            for _, r in tx_grp[d].iterrows():

                ticker = r["Ticker"]
                qty = float(r["Quantity"])
                price = float(r["Price"])
                value = qty * price

                if str(r["Action"]).upper() == "BUY":
                    holdings[ticker] += qty
                    cash -= value
                else:
                    holdings[ticker] -= qty
                    cash += value

        equity = 0.0

        for ticker, qty in holdings.items():

            if qty == 0:
                continue

            if (
                ticker in prices.columns
                and d in prices.index
            ):
                px = prices.loc[d, ticker]

                if pd.notna(px):
                    equity += qty * px

        total = equity + cash

        rows.append({
            "Date": d,
            "Equity Value": equity,
            "Cash": cash,
            "Portfolio Value": total,
            "External Flow": cf_grp.get(d, 0.0)
        })

    return pd.DataFrame(rows).set_index("Date")


def compute_twr(df):

    df = df.copy()
    df["Return"] = 0.0

    for i in range(1, len(df)):

        prev = df.iloc[i - 1]["Portfolio Value"]

        if prev <= 0:
            continue

        curr = df.iloc[i]["Portfolio Value"]
        flow = df.iloc[i]["External Flow"]

        ret = ((curr - flow) / prev) - 1
        df.iloc[i, df.columns.get_loc("Return")] = ret

    df["Growth100"] = (
        (1 + df["Return"]).cumprod() * 100
    )

    twr = (1 + df["Return"]).prod() - 1

    return df, twr


def benchmark_replication(cf, tri):

    flows = (
        cf.groupby("Date")["Amount"]
        .sum()
        .to_dict()
    )

    units = 0.0
    rows = []

    for d in tri.index:

        flow = flows.get(d, 0.0)
        px = tri.loc[d]

        if flow != 0 and px > 0:
            units += flow / px

        value = units * px

        rows.append({
            "Date": d,
            "Portfolio Value": value,
            "External Flow": flow,
            "Cash": 0.0,
            "Equity Value": value
        })

    return pd.DataFrame(rows).set_index("Date")


# --------------------------
# Uploads
# --------------------------

tx_file = st.sidebar.file_uploader(
    "Transactions", ["xlsx", "csv"]
)

cf_file = st.sidebar.file_uploader(
    "Cash Flows", ["xlsx", "csv"]
)

n50_file = st.sidebar.file_uploader(
    "Nifty50 TRI CSV", ["csv"]
)

n500_file = st.sidebar.file_uploader(
    "Nifty500 TRI CSV", ["csv"]
)

if tx_file and cf_file:

    tx = read_file(tx_file)
    cf = read_file(cf_file)

    # DD/MM/YY parsing
    tx["Date"] = pd.to_datetime(
        tx["Date"],
        dayfirst=True,
        errors="coerce"
    ).dt.normalize()

    cf["Date"] = pd.to_datetime(
        cf["Date"],
        dayfirst=True,
        errors="coerce"
    ).dt.normalize()

    if tx["Date"].isna().any():
        st.error(
            "Some transaction dates could not be parsed. Please use DD/MM/YY."
        )
        st.stop()

    if cf["Date"].isna().any():
        st.error(
            "Some cash flow dates could not be parsed. Please use DD/MM/YY."
        )
        st.stop()

    # Auto append .NS
    tx["Ticker"] = (
        tx["Ticker"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    tx["Ticker"] = np.where(
        tx["Ticker"].str.endswith(".NS"),
        tx["Ticker"],
        tx["Ticker"] + ".NS"
    )

    tickers = sorted(tx["Ticker"].unique())

    start = min(
        tx["Date"].min(),
        cf["Date"].min()
    )

    end = pd.Timestamp.today().normalize()

    with st.spinner("Downloading prices..."):
        prices, missing = get_prices(
            tickers,
            start,
            end
        )

    # Missing ticker report
    if missing:

        st.warning(
            f"{len(missing)} ticker(s) could not be fetched."
        )

        missing_df = pd.DataFrame(
            {"Ticker": missing}
        )

        st.subheader("Missing Price Data")
        st.dataframe(
            missing_df,
            use_container_width=True
        )

        st.download_button(
            "Download Missing Tickers",
            missing_df.to_csv(index=False),
            "missing_tickers.csv",
            "text/csv"
        )

        st.error(
            "Returns cannot be calculated because some tickers have no price data."
        )
        st.stop()

    ledger = build_daily_ledger(
        tx,
        cf,
        prices
    )

    ledger, port_twr = compute_twr(
        ledger
    )

    days = (
        ledger.index.max()
        - ledger.index.min()
    ).days + 1

    port_ann = annualise_twr(
        port_twr,
        days
    )

    st.header("Performance Summary")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Portfolio TWR",
        f"{port_twr:.2%}"
    )

    c2.metric(
        "Annualised TWR",
        f"{port_ann:.2%}"
    )

    c3.metric(
        "Current Portfolio Value",
        f"₹{ledger.iloc[-1]['Portfolio Value']:,.0f}"
    )

    st.subheader("Growth of ₹100")

    fig = px.line(
        ledger,
        x=ledger.index,
        y="Growth100"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.subheader("Daily Ledger")
    st.dataframe(
        ledger,
        use_container_width=True
    )

else:
    st.info(
        "Upload Transactions and Cash Flow files to begin."
    )
