
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px

st.set_page_config(page_title="VIKA Portfolio TWR Tracker", layout="wide")
st.title("VIKA Portfolio TWR Tracker")

st.markdown("""
Upload:
1. Transactions: Date, Ticker, Action, Quantity, Price
2. Cash Flows: Date, Amount
3. Optional benchmark TRI CSVs (Date, Value)
""")

@st.cache_data
def read_file(f):
    if f.name.endswith(".csv"):
        return pd.read_csv(f)
    return pd.read_excel(f)

@st.cache_data
def get_prices(tickers, start, end):
    out = {}
    for t in tickers:
        try:
            d = yf.download(
                t,
                start=start,
                end=end + pd.Timedelta(days=2),
                auto_adjust=True,
                progress=False,
                group_by="column"
            )
            if not d.empty:
                close = d["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                out[t] = close
        except:
            pass

    if not out:
        return pd.DataFrame()

    return pd.concat(out, axis=1).ffill()

def annualise(ret, days):
    if days <= 0:
        return np.nan
    return (1 + ret) ** (365 / days) - 1

def build_daily_ledger(tx, cf, prices):

    start = min(tx["Date"].min(), cf["Date"].min())
    end = prices.index.max()

    dates = pd.bdate_range(start, end)

    holdings = {t: 0.0 for t in tx["Ticker"].unique()}
    cash = 0.0

    tx_grp = {
        d: g for d, g in tx.groupby("Date")
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
            trades = tx_grp[d]

            for _, r in trades.iterrows():

                ticker = r["Ticker"]
                qty = float(r["Quantity"])
                price = float(r["Price"])
                value = qty * price

                action = str(
                    r["Action"]
                ).upper()

                if action == "BUY":
                    holdings[ticker] += qty
                    cash -= value

                elif action == "SELL":
                    holdings[ticker] -= qty
                    cash += value

        equity_value = 0.0

        for t, q in holdings.items():

            if q == 0:
                continue

            if (
                t in prices.columns
                and d in prices.index
            ):
                p = prices.loc[d, t]

                if pd.notna(p):
                    equity_value += q * p

        total = equity_value + cash

        rows.append(
            {
                "Date": d,
                "Equity Value": equity_value,
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

        ret = ((curr - flow) / prev) - 1
        df.iloc[i, df.columns.get_loc("Return")] = ret

    df["Growth100"] = (
        (1 + df["Return"]).cumprod()
        * 100
    )

    twr = (
        (1 + df["Return"]).prod()
        - 1
    )

    return df, twr

def benchmark_replication(cf, tri):

    dates = tri.index
    units = 0.0

    flows = (
        cf.groupby("Date")["Amount"]
        .sum()
        .to_dict()
    )

    rows = []

    for d in dates:

        px = tri.loc[d]
        flow = flows.get(d, 0.0)

        if flow != 0 and px > 0:
            units += flow / px

        value = units * px

        rows.append(
            {
                "Date": d,
                "Portfolio Value": value,
                "External Flow": flow
            }
        )

    bm = pd.DataFrame(rows).set_index("Date")
    bm["Cash"] = 0.0
    bm["Equity Value"] = bm["Portfolio Value"]

    return bm

tx_file = st.sidebar.file_uploader(
    "Transactions",
    ["csv", "xlsx"]
)
cf_file = st.sidebar.file_uploader(
    "Cash Flows",
    ["csv", "xlsx"]
)
n50_file = st.sidebar.file_uploader(
    "Nifty50 TRI",
    ["csv"]
)
n500_file = st.sidebar.file_uploader(
    "Nifty500 TRI",
    ["csv"]
)

if tx_file and cf_file:

    tx = read_file(tx_file)
    cf = read_file(cf_file)

    tx["Date"] = pd.to_datetime(tx["Date"]).dt.normalize()
    cf["Date"] = pd.to_datetime(cf["Date"]).dt.normalize()

    tickers = sorted(
        tx["Ticker"].unique()
    )

    start = min(
        tx["Date"].min(),
        cf["Date"].min()
    )

    end = pd.Timestamp.today().normalize()

    with st.spinner("Downloading prices..."):
        prices = get_prices(
            tickers,
            start,
            end
        )

    if prices.empty:
        st.error(
            "Unable to download prices."
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

    port_ann = annualise(
        port_twr,
        days
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Portfolio TWR",
        f"{port_twr:.2%}"
    )

    c2.metric(
        "Annualised TWR",
        f"{port_ann:.2%}"
    )

    if len(ledger):
        c3.metric(
            "Current Portfolio Value",
            f"₹{ledger.iloc[-1]['Portfolio Value']:,.0f}"
        )

    summary = {
        "Portfolio": [
            port_twr,
            port_ann
        ]
    }

    chart = pd.DataFrame(
        index=ledger.index
    )
    chart["Portfolio"] = (
        ledger["Growth100"]
    )

    for label, f in [
        ("Nifty50 TRI", n50_file),
        ("Nifty500 TRI", n500_file)
    ]:

        if f is None:
            continue

        tri = pd.read_csv(f)
        tri["Date"] = pd.to_datetime(
            tri["Date"]
        )
        tri = (
            tri.set_index("Date")
            .sort_index()
        )

        s = (
            tri.iloc[:, 0]
            .reindex(ledger.index)
            .ffill()
        )

        bm = benchmark_replication(
            cf,
            s
        )

        bm, twr = compute_twr(bm)
        ann = annualise(twr, days)

        summary[label] = [twr, ann]
        chart[label] = bm["Growth100"]

    st.subheader(
        "Performance Table"
    )

    df = pd.DataFrame(
        summary,
        index=[
            "Actual TWR",
            "Annualised TWR"
        ]
    ).T

    st.dataframe(
        df.style.format(
            "{:.2%}"
        )
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

    st.subheader(
        "Daily Ledger"
    )

    st.dataframe(
        ledger.tail(50)
    )

else:
    st.info(
        "Upload files to begin."
    )
