
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
import plotly.io as pio
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

st.set_page_config(page_title="VIKA Portfolio TWR Tracker", layout="wide")
st.title("VIKA Portfolio TWR Tracker")

NIFTY50_PROXY = "0P00005WL6.BO"
NIFTY500_PROXY = "0P0001IAU3.BO"

st.markdown("""
Upload:

1. Transactions (Portfolio, Date, Ticker, Action, Quantity, Price)
2. Cash Flows (Portfolio, Date, Amount)

Benchmarks are automatically pulled from Yahoo Finance.
""")

def format_inr(x):
    if pd.isna(x):
        return ""

    x = round(float(x))
    sign = "-" if x < 0 else ""
    x = abs(x)
    integer = int(x)

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

    return f"{sign}₹{result}"


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


def build_pdf_report(portfolio_name, portfolio_value, cash_balance, summary, fig):

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            f"Client Name: {portfolio_name}",
            styles["Title"]
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Performance Summary", styles["Heading2"]),
        Spacer(1, 0.1 * inch)
    ]

    summary_metrics = [
        ["Metric", "Value"],
        ["Portfolio TWR", f"{summary.loc['Actual TWR', 'Portfolio']:.2%}"],
        ["Annualised TWR", f"{summary.loc['Annualised TWR', 'Portfolio']:.2%}"],
        ["Current Portfolio Value", format_inr(portfolio_value)],
        ["Cash Balance", format_inr(cash_balance)]
    ]

    metrics_table = Table(
        summary_metrics,
        colWidths=[2.8 * inch, 2.8 * inch]
    )
    metrics_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 6)
            ]
        )
    )
    story.extend(
        [
            metrics_table,
            Spacer(1, 0.25 * inch),
            Paragraph("Performance Comparison Table", styles["Heading2"]),
            Spacer(1, 0.1 * inch)
        ]
    )

    comparison_rows = [["Metric", "Portfolio", "Nifty50 TRI", "Nifty500 TRI"]]
    for idx, row in summary.iterrows():
        comparison_rows.append(
            [
                idx,
                f"{row['Portfolio']:.2%}" if pd.notna(row["Portfolio"]) else "",
                f"{row['Nifty50 TRI']:.2%}" if pd.notna(row["Nifty50 TRI"]) else "",
                f"{row['Nifty500 TRI']:.2%}" if pd.notna(row["Nifty500 TRI"]) else ""
            ]
        )

    comparison_table = Table(
        comparison_rows,
        colWidths=[2.2 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch]
    )
    comparison_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.beige]),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 6)
            ]
        )
    )
    story.extend(
        [
            comparison_table,
            Spacer(1, 0.25 * inch),
            Paragraph("Growth of Rs 100 Chart", styles["Heading2"]),
            Spacer(1, 0.1 * inch)
        ]
    )

    chart_bytes = BytesIO(
        pio.to_image(
            fig,
            format="png",
            width=1200,
            height=600,
            scale=2
        )
    )
    story.append(Image(chart_bytes, width=7.2 * inch, height=3.6 * inch))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


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

    required_tx_cols = {
        "Portfolio",
        "Date",
        "Ticker",
        "Action",
        "Quantity",
        "Price"
    }
    required_cf_cols = {
        "Portfolio",
        "Date",
        "Amount"
    }

    missing_tx_cols = required_tx_cols - set(tx.columns)
    missing_cf_cols = required_cf_cols - set(cf.columns)

    if missing_tx_cols:
        st.error(
            "Transactions file is missing columns: "
            + ", ".join(sorted(missing_tx_cols))
        )
        st.stop()

    if missing_cf_cols:
        st.error(
            "Cash flow file is missing columns: "
            + ", ".join(sorted(missing_cf_cols))
        )
        st.stop()

    tx["Portfolio"] = (
        tx["Portfolio"]
        .astype(str)
        .str.strip()
    )

    cf["Portfolio"] = (
        cf["Portfolio"]
        .astype(str)
        .str.strip()
    )

    available_portfolios = sorted(
        set(tx["Portfolio"].dropna())
        & set(cf["Portfolio"].dropna())
    )

    if not available_portfolios:
        st.error(
            "No common portfolios were found in the transactions and cash flow files."
        )
        st.stop()

    selected_portfolio = st.sidebar.selectbox(
        "Portfolio",
        available_portfolios
    )

    tx = tx[
        tx["Portfolio"] == selected_portfolio
    ].copy()

    cf = cf[
        cf["Portfolio"] == selected_portfolio
    ].copy()

    if tx.empty:
        st.error(
            f"No transactions found for portfolio '{selected_portfolio}'."
        )
        st.stop()

    if cf.empty:
        st.error(
            f"No cash flows found for portfolio '{selected_portfolio}'."
        )
        st.stop()

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

    pdf_bytes = build_pdf_report(
        selected_portfolio,
        ledger.iloc[-1]["Portfolio Value"],
        ledger.iloc[-1]["Cash"],
        summary,
        fig
    )

    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name=f"{selected_portfolio}_portfolio_report.pdf",
        mime="application/pdf"
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
