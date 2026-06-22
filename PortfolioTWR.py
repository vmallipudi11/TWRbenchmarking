
"""
VIKA Portfolio TWR Tracker - v4
Features
- DD/MM/YY parsing
- Automatic .NS mapping with .BO fallback
- Missing ticker reporting
- Portfolio TWR vs benchmark proxies
- Benchmark proxies:
    Nifty50 TRI  -> 0P00005WL6.BO
    Nifty500 TRI -> 0P0001IAU3.BO
- Indian currency formatting
- Cash balance card
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px

st.set_page_config(page_title="VIKA Portfolio TWR Tracker", layout="wide")
st.title("VIKA Portfolio TWR Tracker")

NIFTY50_PROXY = "0P00005WL6.BO"
NIFTY500_PROXY = "0P0001IAU3.BO"

st.markdown("""
Upload:

1. Transactions (Date, Ticker, Action, Quantity, Price)
2. Cash Flows (Date, Amount)

Benchmarks are automatically pulled from Yahoo Finance.
""")

def format_inr(x):
    if pd.isna(x):
        return ""

    x = float(x)
    sign = "-" if x < 0 else ""
    x = abs(x)

    integer = int(x)
    decimal = f"{x:.2f}".split(".")[1]

    s = str(integer)

    if len(s) <= 3:
        result = s
    else:
        result = s[-3:]
        s = s[:-3]

        while len(s) > 2:
            result = s[-2:] + "," + result
            s = s[:-2]

        if s:
            result = s + "," + result

    return f"{sign}₹{result}.{decimal}"


@st.cache_data
def read_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


@st.cache_data
def get_prices(tickers, start, end):

    out = {}
    missing = []

    for ticker in tickers:

        fetched = False

        attempts = [ticker]

        if ticker.endswith(".NS"):
            attempts.append(
                ticker.replace(".NS", ".BO")
            )

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

                out[ticker] = close
                fetched = True
                break

            except Exception:
                pass

        if not fetched:
            missing.append(ticker)

    if not out:
        return pd.DataFrame(), missing

    prices = (
        pd.concat(out, axis=1)
        .sort_index()
        .ffill()
    )

    return prices, sorted(set(missing))


def annualise_twr(twr, days):
    if days <= 0:
        return np.nan
    return (1 + twr) ** (365 / days) - 1


def build_daily_ledger(tx, cf, prices):

    start = min(
        tx["Date"].min(),
        cf["Date"].min()
    )

    end = prices.index.max()
    dates = pd.bdate_range(start, end)

    holdings = {
        t: 0.0
        for t in tx["Ticker"].unique()
    }

    cash = 0.0

    tx_grp = {
        d: g
        for d, g in tx.groupby("Date")
    }

    cf_grp = (
        cf.groupby("Date")["Amount"]
        .sum()
        .to_dict()
    )

    rows = []

    for d in dates:

        if d in cf_grp:
            cash += float(cf_grp[d])

        if d in tx_grp:

            for _, r in tx_grp[d].iterrows():

                ticker = r["Ticker"]
                qty = float(r["Quantity"])
                value = (
                    float(r["Quantity"])
                    * float(r["Price"])
                )

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

        rows.append(
            {
                "Date": d,
                "Equity Value": equity,
                "Cash": cash,
                "Portfolio Value": total,
                "External Flow": cf_grp.get(d, 0.0)
            }
        )

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

        ret = (
            (curr - flow)
            / prev
        ) - 1

        df.iloc[
            i,
            df.columns.get_loc("Return")
        ] = ret

    df["Growth100"] = (
        (1 + df["Return"])
        .cumprod()
        * 100
    )

    twr = (
        (1 + df["Return"])
        .prod()
        - 1
    )

    return df, twr


def benchmark_replication(cf, series):

    flows = (
        cf.groupby("Date")["Amount"]
        .sum()
        .to_dict()
    )

    units = 0.0
    rows = []

    for d in series.index:

        px = series.loc[d]
        flow = flows.get(d, 0.0)

        if flow != 0 and px > 0:
            units += flow / px

        value = units * px

        rows.append(
            {
                "Date": d,
                "Portfolio Value": value,
                "External Flow": flow,
                "Cash": 0.0,
                "Equity Value": value
            }
        )

    return pd.DataFrame(rows).set_index("Date")


# --------------------------
# Uploads
# --------------------------

tx_file = st.sidebar.file_uploader(
    "Transactions",
    ["xlsx", "csv"]
)

cf_file = st.sidebar.file_uploader(
    "Cash Flows",
    ["xlsx", "csv"]
)

if tx_file and cf_file:

    tx = read_file(tx_file)
    cf = read_file(cf_file)

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
            "Some transaction dates could not be parsed. Use DD/MM/YY."
        )
        st.stop()

    if cf["Date"].isna().any():
        st.error(
            "Some cash flow dates could not be parsed. Use DD/MM/YY."
        )
        st.stop()

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

    tickers = sorted(
        tx["Ticker"].unique()
    )

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

    if missing:

        missing_df = pd.DataFrame(
            {"Ticker": missing}
        )

        st.warning(
            f"{len(missing)} ticker(s) could not be fetched."
        )

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

    # --------------------
    # Benchmarks
    # --------------------

    bm_prices, bm_missing = get_prices(
        [
            NIFTY50_PROXY,
            NIFTY500_PROXY
        ],
        start,
        end
    )

    if bm_missing:
        st.error(
            f"Unable to download benchmark data: {bm_missing}"
        )
        st.stop()

    n50 = benchmark_replication(
        cf,
        bm_prices[NIFTY50_PROXY]
        .reindex(ledger.index)
        .ffill()
    )

    n500 = benchmark_replication(
        cf,
        bm_prices[NIFTY500_PROXY]
        .reindex(ledger.index)
        .ffill()
    )

    n50, n50_twr = compute_twr(n50)
    n500, n500_twr = compute_twr(n500)

    n50_ann = annualise_twr(
        n50_twr,
        days
    )

    n500_ann = annualise_twr(
        n500_twr,
        days
    )

    alpha50 = port_twr - n50_twr
    alpha500 = port_twr - n500_twr

    # --------------------
    # Dashboard
    # --------------------

    st.header("Performance Summary")

    c1, c2, c3, c4 = st.columns(4)

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
        format_inr(
            ledger.iloc[-1]["Portfolio Value"]
        )
    )

    c4.metric(
        "Cash Balance",
        format_inr(
            ledger.iloc[-1]["Cash"]
        )
    )

    summary = pd.DataFrame(
        {
            "Portfolio":
                [port_twr,
                 port_ann,
                 alpha50,
                 alpha500],

            "Nifty50 TRI":
                [n50_twr,
                 n50_ann,
                 np.nan,
                 np.nan],

            "Nifty500 TRI":
                [n500_twr,
                 n500_ann,
                 np.nan,
                 np.nan]
        },
        index=[
            "Actual TWR",
            "Annualised TWR",
            "Alpha vs Nifty50",
            "Alpha vs Nifty500"
        ]
    )

    st.subheader(
        "Performance Table"
    )

    st.dataframe(
        summary.style.format(
            "{:.2%}"
        ),
        use_container_width=True
    )

    chart = pd.DataFrame(
        index=ledger.index
    )

    chart["Portfolio"] = (
        ledger["Growth100"]
    )

    chart["Nifty50 TRI"] = (
        n50["Growth100"]
    )

    chart["Nifty500 TRI"] = (
        n500["Growth100"]
    )

    st.subheader(
        "Growth of ₹100"
    )

    fig = px.line(
        chart,
        x=chart.index,
        y=chart.columns
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.subheader("Daily Ledger")

    display = ledger.copy()

    for c in [
        "Equity Value",
        "Cash",
        "Portfolio Value",
        "External Flow"
    ]:
        display[c] = display[c].apply(
            format_inr
        )

    st.dataframe(
        display,
        use_container_width=True
    )

else:
    st.info(
        "Upload Transactions and Cash Flow files to begin."
    )
