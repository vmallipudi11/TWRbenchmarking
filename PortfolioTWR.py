
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px

st.set_page_config(page_title="Portfolio TWR Tracker", layout="wide")
st.title("Portfolio TWR vs Nifty Benchmark Tracker")

st.markdown("""
### Required Files

**Transactions**
- Date
- Ticker
- Action (BUY/SELL)
- Quantity
- Price

**Cash Flows**
- Date
- Amount (Positive = Contribution, Negative = Withdrawal)
""")

# ---------------------------
# Helpers
# ---------------------------

@st.cache_data
def read_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)

@st.cache_data
def download_prices(tickers, start, end):
    data = {}
    for ticker in tickers:
        try:
            px_data = yf.download(
                ticker,
                start=start,
                end=end + pd.Timedelta(days=2),
                progress=False,
                auto_adjust=True
            )
            if len(px_data):
                data[ticker] = px_data["Close"]
        except:
            pass

    if not data:
        return pd.DataFrame()

    prices = pd.concat(data, axis=1)
    prices = prices.ffill()
    return prices


def annualise_twr(twr, days):
    if days <= 0:
        return np.nan
    return (1 + twr) ** (365 / days) - 1


def build_holdings(tx):
    tx = tx.sort_values("Date")
    tickers = tx["Ticker"].unique()

    start = tx["Date"].min()
    end = pd.Timestamp.today().normalize()

    dates = pd.bdate_range(start, end)

    holdings = pd.DataFrame(
        index=dates,
        columns=tickers,
        data=0.0
    )

    running = {t: 0.0 for t in tickers}

    grouped = tx.groupby("Date")

    for d in dates:
        if d in grouped.groups:
            day = grouped.get_group(d)

            for _, r in day.iterrows():

                qty = r["Quantity"]

                if str(r["Action"]).upper() == "SELL":
                    qty = -qty

                running[r["Ticker"]] += qty

        for t in tickers:
            holdings.loc[d, t] = running[t]

    return holdings


def build_cash_series(cashflows, dates):
    s = pd.Series(0.0, index=dates)

    for _, r in cashflows.iterrows():
        d = pd.Timestamp(r["Date"])

        if d in s.index:
            s.loc[d] += float(r["Amount"])

    return s


def compute_portfolio_values(holdings, prices, cashflows):

    prices = prices.reindex(holdings.index).ffill()

    common = [c for c in holdings.columns if c in prices.columns]

    if len(common) == 0:
        raise ValueError(
            "No matching tickers found. Use Yahoo Finance symbols "
            "such as RELIANCE.NS, INFY.NS, TCS.NS"
        )

    holdings = holdings[common]
    prices = prices[common]

    values = (holdings * prices).sum(axis=1)

    cash = build_cash_series(
        cashflows,
        values.index
    )

    out = pd.DataFrame(index=values.index)
    out["Portfolio Value"] = values
    out["Cash Flow"] = cash

    return out


def compute_daily_twr(df):
    df = df.copy()

    df["Return"] = 0.0

    for i in range(1, len(df)):

        prev = df.iloc[i - 1]["Portfolio Value"]

        if prev == 0:
            continue

        curr = df.iloc[i]["Portfolio Value"]
        cf = df.iloc[i]["Cash Flow"]

        r = (curr - cf) / prev - 1

        df.iloc[i, df.columns.get_loc("Return")] = r

    df["Growth100"] = (
        (1 + df["Return"]).cumprod()
    ) * 100

    twr = (
        (1 + df["Return"]).prod()
    ) - 1

    return df, twr


def benchmark_replication(
    cashflows,
    benchmark_series
):

    dates = benchmark_series.index

    units = 0
    vals = []

    cf = build_cash_series(
        cashflows,
        dates
    )

    for d in dates:

        px = benchmark_series.loc[d]

        flow = cf.loc[d]

        if flow != 0 and px > 0:
            units += flow / px

        vals.append(units * px)

    out = pd.DataFrame(index=dates)
    out["Portfolio Value"] = vals
    out["Cash Flow"] = cf

    return out


# ---------------------------
# Uploads
# ---------------------------

tx_file = st.sidebar.file_uploader(
    "Transactions",
    type=["csv", "xlsx"]
)

cf_file = st.sidebar.file_uploader(
    "Cash Flows",
    type=["csv", "xlsx"]
)

st.sidebar.markdown(
    "For benchmarks, upload CSVs of daily TRI values."
)

n50_file = st.sidebar.file_uploader(
    "Nifty50 TRI CSV",
    type=["csv"]
)

n500_file = st.sidebar.file_uploader(
    "Nifty500 TRI CSV",
    type=["csv"]
)

if tx_file and cf_file:

    tx = read_file(tx_file)
    cf = read_file(cf_file)

    tx["Date"] = pd.to_datetime(tx["Date"])
    cf["Date"] = pd.to_datetime(cf["Date"])

    st.subheader("Input Preview")

    c1, c2 = st.columns(2)

    with c1:
        st.dataframe(tx.head())

    with c2:
        st.dataframe(cf.head())

    holdings = build_holdings(tx)

    start = holdings.index.min()
    end = holdings.index.max()

    tickers = list(
        tx["Ticker"].unique()
    )

    with st.spinner("Downloading prices..."):
        prices = download_prices(
            tickers,
            start,
            end
        )

    if prices.empty:
        st.error(
            "Could not download prices."
        )
        st.stop()

    portfolio = compute_portfolio_values(
        holdings,
        prices,
        cf
    )

    portfolio, port_twr = compute_daily_twr(
        portfolio
    )

    days = (
        portfolio.index.max()
        - portfolio.index.min()
    ).days + 1

    port_ann = annualise_twr(
        port_twr,
        days
    )

    # -----------------------
    # Benchmarks
    # -----------------------

    n50_twr = np.nan
    n500_twr = np.nan
    n50_ann = np.nan
    n500_ann = np.nan

    benchmark_chart = pd.DataFrame(
        index=portfolio.index
    )

    benchmark_chart["Portfolio"] = (
        portfolio["Growth100"]
    )

    if n50_file:

        n50 = pd.read_csv(
            n50_file
        )

        n50["Date"] = pd.to_datetime(
            n50["Date"]
        )

        n50 = (
            n50
            .set_index("Date")
            .sort_index()
        )

        series = (
            n50.iloc[:, 0]
            .reindex(
                portfolio.index
            )
            .ffill()
        )

        bm = benchmark_replication(
            cf,
            series
        )

        bm, n50_twr = compute_daily_twr(
            bm
        )

        n50_ann = annualise_twr(
            n50_twr,
            days
        )

        benchmark_chart[
            "Nifty50 TRI"
        ] = bm["Growth100"]

    if n500_file:

        n500 = pd.read_csv(
            n500_file
        )

        n500["Date"] = pd.to_datetime(
            n500["Date"]
        )

        n500 = (
            n500
            .set_index("Date")
            .sort_index()
        )

        series = (
            n500.iloc[:, 0]
            .reindex(
                portfolio.index
            )
            .ffill()
        )

        bm = benchmark_replication(
            cf,
            series
        )

        bm, n500_twr = compute_daily_twr(
            bm
        )

        n500_ann = annualise_twr(
            n500_twr,
            days
        )

        benchmark_chart[
            "Nifty500 TRI"
        ] = bm["Growth100"]

    # -----------------------
    # Dashboard
    # -----------------------

    st.header(
        "Performance Summary"
    )

    a, b, c = st.columns(3)

    a.metric(
        "Portfolio TWR",
        f"{port_twr:.2%}"
    )

    b.metric(
        "Annualised TWR",
        f"{port_ann:.2%}"
    )

    if not np.isnan(n500_twr):
        c.metric(
            "Alpha vs Nifty500",
            f"{(port_twr-n500_twr):.2%}"
        )

    summary = pd.DataFrame(
        {
            "Metric": [
                "Actual TWR",
                "Annualised TWR"
            ],
            "Portfolio": [
                port_twr,
                port_ann
            ],
            "Nifty50 TRI": [
                n50_twr,
                n50_ann
            ],
            "Nifty500 TRI": [
                n500_twr,
                n500_ann
            ],
        }
    )

    st.subheader(
        "Performance Table"
    )

    st.dataframe(
        summary.style.format(
            "{:.2%}",
            subset=[
                "Portfolio",
                "Nifty50 TRI",
                "Nifty500 TRI"
            ]
        )
    )

    st.subheader(
        "Growth of ₹100"
    )

    fig = px.line(
        benchmark_chart,
        x=benchmark_chart.index,
        y=benchmark_chart.columns
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.subheader(
        "Daily Returns"
    )

    st.dataframe(
        portfolio[
            [
                "Portfolio Value",
                "Cash Flow",
                "Return"
            ]
        ].tail(30)
    )

else:
    st.info(
        "Upload transactions and cash flow files to begin."
    )
