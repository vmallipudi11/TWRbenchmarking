
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
import matplotlib.pyplot as plt
import msoffcrypto
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from datetime import date
current_date = date.today()

LARGE_CAP_THRESHOLD = 900000000000
MID_CAP_THRESHOLD = 300000000000
PIE_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]
PIE_COLOR_MAP = {
    "Large Cap": "#1f77b4",
    "Mid Cap": "#ff7f0e",
    "Small Cap": "#2ca02c"
}

st.set_page_config(page_title="VIKA Portfolio TWR Tracker", layout="wide")
st.title("VIKA Portfolio TWR Tracker")

NIFTY50_PROXY = "0P00005WL6.BO"
NIFTY500_PROXY = "0P0001IAU3.BO"

st.markdown("""
Upload:

1. One Excel workbook with two tabs:
   - Transactions (Portfolio, Date, Ticker, Action, Quantity, Price)
   - Cashflows (Portfolio, Date, Amount)

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

    return f"{sign}{result}"


def format_display_date(value):
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%B %d, %Y")


def format_display_ticker(ticker):
    if pd.isna(ticker):
        return ""

    ticker = str(ticker).strip()

    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker[:-3]

    return ticker


@st.cache_data
def read_workbook(file, password=None):
    file_bytes = BytesIO(file.getvalue())

    if password:
        try:
            office_file = msoffcrypto.OfficeFile(file_bytes)
            office_file.load_key(password=password)

            decrypted_file = BytesIO()
            office_file.decrypt(decrypted_file)
            decrypted_file.seek(0)
            workbook_bytes = decrypted_file
        except Exception as exc:
            raise ValueError(
                "Unable to open the Excel file with the provided password."
            ) from exc
    else:
        workbook_bytes = file_bytes

    try:
        workbook_bytes.seek(0)
        tx = pd.read_excel(
            workbook_bytes,
            sheet_name="Transactions"
        )
        workbook_bytes.seek(0)
        cf = pd.read_excel(
            workbook_bytes,
            sheet_name="Cashflows"
        )
    except ValueError as exc:
        raise ValueError(
            "The workbook must contain tabs named 'Transactions' and 'Cashflows'."
        ) from exc
    except Exception as exc:
        raise ValueError(
            "Unable to open the Excel workbook. If the file is password protected, enter the password in the sidebar."
        ) from exc

    return tx, cf


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


def build_chart_image(chart):

    fig, ax = plt.subplots(figsize=(10, 4.8))

    for column in chart.columns:
        ax.plot(
            chart.index,
            chart[column],
            linewidth=2,
            label=column
        )

    ax.set_title("Growth of Portfolio")
    ax.set_xlabel("Date")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=200,
        bbox_inches="tight"
    )
    plt.close(fig)
    buffer.seek(0)
    return buffer


@st.cache_data
def get_market_caps(tickers):

    market_caps = {}

    for ticker in tickers:

        if not ticker or ticker == "Cash":
            continue

        attempts = [ticker]

        if ticker.endswith(".NS"):
            attempts.append(
                ticker.replace(".NS", ".BO")
            )

        for sym in attempts:
            try:
                ticker_obj = yf.Ticker(sym)

                market_cap = None
                fast_info = getattr(ticker_obj, "fast_info", None)

                if fast_info is not None:
                    if hasattr(fast_info, "get"):
                        market_cap = fast_info.get("market_cap")

                    if market_cap is None:
                        try:
                            market_cap = fast_info["market_cap"]
                        except Exception:
                            pass

                    if market_cap is None:
                        if hasattr(fast_info, "get"):
                            market_cap = fast_info.get("marketCap")

                if market_cap is None:
                    info = ticker_obj.info
                    if isinstance(info, dict):
                        market_cap = info.get("marketCap")

                if market_cap is not None and pd.notna(market_cap):
                    market_caps[ticker] = float(market_cap)
                    break

            except Exception:
                pass

    return market_caps


def classify_market_cap_bucket(market_cap):

    if pd.isna(market_cap):
        return None

    if market_cap > LARGE_CAP_THRESHOLD:
        return "Large Cap"

    if market_cap >= MID_CAP_THRESHOLD:
        return "Mid Cap"

    return "Small Cap"


def build_current_holdings(tx, prices, as_of_date, cash_balance):

    tx = tx.copy()
    tx["Signed Quantity"] = np.where(
        tx["Action"].astype(str).str.upper() == "BUY",
        tx["Quantity"].astype(float),
        -tx["Quantity"].astype(float)
    )

    holdings = (
        tx.groupby("Ticker", as_index=False)["Signed Quantity"]
        .sum()
    )
    holdings = holdings[
        holdings["Signed Quantity"] != 0
    ].copy()

    if not holdings.empty:
        holdings["Value"] = holdings.apply(
            lambda row: row["Signed Quantity"] * prices.loc[as_of_date, row["Ticker"]],
            axis=1
        )
        holdings = holdings[
            holdings["Value"].abs() > 0
        ].copy()
    else:
        holdings["Value"] = pd.Series(dtype=float)

    cash_row = pd.DataFrame(
        [
            {
                "Ticker": "Cash",
                "Value": float(cash_balance)
            }
        ]
    )

    holdings = holdings[["Ticker", "Value"]]
    market_caps = get_market_caps(
        holdings.loc[
            holdings["Ticker"] != "Cash",
            "Ticker"
        ].dropna().astype(str).unique().tolist()
    )
    holdings["Market Cap"] = holdings["Ticker"].map(market_caps).apply(
        classify_market_cap_bucket
    )
    holdings = pd.concat(
        [
            holdings.sort_values("Ticker"),
            cash_row
        ],
        ignore_index=True
    )
    holdings["Market Cap"] = holdings["Market Cap"].fillna("")

    total_value = holdings["Value"].sum()
    holdings["Weight"] = np.where(
        total_value != 0,
        holdings["Value"] / total_value,
        np.nan
    )

    holdings["Is Cash"] = holdings["Ticker"] == "Cash"
    holdings = holdings.sort_values(
        by=["Is Cash", "Weight"],
        ascending=[True, False],
        na_position="last"
    ).reset_index(drop=True)

    holdings["Ticker"] = holdings["Ticker"].apply(
        lambda ticker: (
            "Cash"
            if ticker == "Cash"
            else format_display_ticker(ticker)
        )
    )

    return holdings[["Ticker", "Market Cap", "Weight"]]


def build_market_cap_allocation(tx, prices, as_of_date):

    if tx is None or tx.empty or prices is None or prices.empty:
        return pd.DataFrame(columns=["Bucket", "Value", "Weight"])

    equity_tx = tx.copy()
    equity_tx["Signed Quantity"] = np.where(
        equity_tx["Action"].astype(str).str.upper() == "BUY",
        equity_tx["Quantity"].astype(float),
        -equity_tx["Quantity"].astype(float)
    )
    equity_holdings = (
        equity_tx.groupby("Ticker", as_index=False)["Signed Quantity"]
        .sum()
    )
    equity_holdings = equity_holdings[
        equity_holdings["Signed Quantity"] > 0
    ].copy()

    if equity_holdings.empty:
        return pd.DataFrame(columns=["Bucket", "Value", "Weight"])

    equity_holdings["Value"] = equity_holdings.apply(
        lambda row: row["Signed Quantity"] * prices.loc[as_of_date, row["Ticker"]],
        axis=1
    )
    equity_holdings = equity_holdings[
        equity_holdings["Value"] > 0
    ].copy()

    if equity_holdings.empty:
        return pd.DataFrame(columns=["Bucket", "Value", "Weight"])

    market_caps = get_market_caps(
        equity_holdings["Ticker"].dropna().astype(str).unique().tolist()
    )

    equity_holdings["Market Cap"] = equity_holdings["Ticker"].map(market_caps)
    equity_holdings["Bucket"] = equity_holdings["Market Cap"].apply(classify_market_cap_bucket)
    equity_holdings = equity_holdings[
        equity_holdings["Bucket"].notna()
    ].copy()

    if equity_holdings.empty:
        return pd.DataFrame(columns=["Bucket", "Value", "Weight"])

    allocation = (
        equity_holdings.groupby("Bucket", as_index=False)["Value"]
        .sum()
    )

    bucket_order = ["Large Cap", "Mid Cap", "Small Cap"]
    allocation["Bucket"] = pd.Categorical(
        allocation["Bucket"],
        categories=bucket_order,
        ordered=True
    )
    allocation = allocation.sort_values("Bucket").reset_index(drop=True)

    total_value = allocation["Value"].sum()
    allocation["Weight"] = np.where(
        total_value != 0,
        allocation["Value"] / total_value,
        np.nan
    )

    return allocation


def build_market_cap_pie_image(allocation_data):

    if allocation_data is None or allocation_data.empty:
        return None

    fig, ax = plt.subplots(figsize=(4.6, 3.6))

    ax.pie(
        allocation_data["Value"],
        labels=allocation_data["Bucket"],
        autopct="%1.1f%%",
        startangle=90,
        colors=PIE_COLORS[: len(allocation_data)],
        wedgeprops={"edgecolor": "white", "linewidth": 1},
        textprops={"fontsize": 9}
    )
    ax.set_title(
        "",
        fontsize=11
    )
    ax.axis("equal")

    buffer = BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=200,
        bbox_inches="tight"
    )
    plt.close(fig)
    buffer.seek(0)
    return buffer


def build_market_cap_pie_figure(allocation_data):

    if allocation_data is None or allocation_data.empty:
        return None

    fig = px.pie(
        allocation_data,
        names="Bucket",
        values="Value",
        color="Bucket",
        color_discrete_map=PIE_COLOR_MAP
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        sort=False
    )
    fig.update_layout(
        width=700,
        height=420,
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=False,
        title_x=0.5
    )
    return fig


def normalize_cash_flow_data(cash_flow_data):

    if cash_flow_data is None:
        return pd.DataFrame(columns=["Date", "Amount"])

    normalized = cash_flow_data.copy()

    if normalized.empty:
        return pd.DataFrame(columns=["Date", "Amount"])

    column_map = {}
    for column in normalized.columns:
        normalized_name = str(column).strip().lower()
        if normalized_name == "date":
            column_map[column] = "Date"
        elif normalized_name == "amount":
            column_map[column] = "Amount"

    normalized = normalized.rename(columns=column_map)

    if "Date" not in normalized.columns and normalized.index.name:
        index_name = str(normalized.index.name).strip().lower()
        if index_name == "date":
            normalized = normalized.reset_index()
            normalized = normalized.rename(columns={normalized.columns[0]: "Date"})

    if "Date" not in normalized.columns and len(normalized.columns) >= 1:
        normalized = normalized.rename(columns={normalized.columns[0]: "Date"})

    if "Amount" not in normalized.columns and len(normalized.columns) >= 2:
        second_col = [col for col in normalized.columns if col != "Date"]
        if second_col:
            normalized = normalized.rename(columns={second_col[0]: "Amount"})

    if "Date" not in normalized.columns:
        normalized["Date"] = pd.NaT

    if "Amount" not in normalized.columns:
        normalized["Amount"] = np.nan

    return normalized[["Date", "Amount"]]


def build_pdf_report(
    portfolio_name,
    start_date,
    current_date,
    portfolio_value,
    cash_balance,
    summary,
    chart,
    cash_flow_data,
    holdings_data,
    market_cap_allocation
):

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
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=12,
        leading=14,
        spaceAfter=0,
        spaceBefore=0
    )
    story = [
        Paragraph(
            f"Client Name: {portfolio_name}",
            section_style
        ),
        Spacer(1, 0.05 * inch),
        Paragraph(
            f"Start Date: {format_display_date(start_date)}",
            section_style
        ),
        Spacer(1, 0.05 * inch),
        Paragraph(
            f"Report Date: {format_display_date(current_date)}",
            section_style
        ),
        Spacer(1, 0.1 * inch),
        Paragraph("Performance Summary", section_style),
        Spacer(1, 0.05 * inch)
    ]

    summary_metrics = [
        ["Metric", "Value"],
        ["Portfolio TWR", f"{summary.loc['Actual TWR', 'Portfolio']:.2%}"],
        ["Annualised TWR", f"{summary.loc['Annualised TWR', 'Portfolio']:.2%}"],
        ["Current Portfolio Value", format_inr(portfolio_value)],
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
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("PADDING", (0, 0), (-1, -1), 4)
            ]
        )
    )
    story.extend(
        [
            metrics_table,
            Spacer(1, 0.12 * inch),
            Paragraph("Performance Comparison Table", section_style),
            Spacer(1, 0.05 * inch)
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
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 4)
            ]
        )
    )
    story.extend(
        [
            comparison_table,
            Spacer(1, 0.12 * inch),
            Paragraph("Growth of Portfolio", section_style),
            Spacer(1, 0.05 * inch)
        ]
    )

    chart_bytes = build_chart_image(chart)
    story.append(Image(chart_bytes, width=6.8 * inch, height=2.8 * inch))

    market_cap_chart = build_market_cap_pie_image(market_cap_allocation)
    if market_cap_chart is not None:
        story.extend(
            [
                Spacer(1, 0.12 * inch),
                Paragraph("Market Cap Allocation", section_style),
                Spacer(1, 0.05 * inch)
            ]
        )
        market_cap_image = Image(
            market_cap_chart,
            width=3.6 * inch,
            height=2.8 * inch
        )
        market_cap_image.hAlign = "CENTER"
        story.append(market_cap_image)

    cash_flow_rows = [["Date", "Amount"]]
    normalized_cash_flows = normalize_cash_flow_data(cash_flow_data)

    if not normalized_cash_flows.empty:
        for _, row in normalized_cash_flows.iterrows():
            cash_flow_rows.append(
                [
                    format_display_date(row["Date"]),
                    format_inr(row["Amount"])
                ]
            )
    else:
        cash_flow_rows.append(["", ""])

    cash_flow_table = Table(
        cash_flow_rows,
        colWidths=[3.2 * inch, 2.4 * inch]
    )
    cash_flow_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("PADDING", (0, 0), (-1, -1), 4)
            ]
        )
    )
    story.extend(
        [
            PageBreak(),
            Paragraph("Current Holdings", section_style),
            Spacer(1, 0.05 * inch)
        ]
    )

    holdings_rows = [["Ticker", "Market Cap", "Weight"]]
    for _, row in holdings_data.iterrows():
        holdings_rows.append(
            [
                row["Ticker"],
                row["Market Cap"],
                f"{row['Weight']:.2%}" if pd.notna(row["Weight"]) else ""
            ]
        )

    holdings_table = Table(
        holdings_rows,
        colWidths=[2.5 * inch, 1.6 * inch, 1.5 * inch]
    )
    cash_row_index = len(holdings_rows) - 1
    holdings_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, cash_row_index), (-1, cash_row_index), "Helvetica-Bold")
    ]
    holdings_table.setStyle(TableStyle(holdings_style))
    story.append(holdings_table)

    story.extend(
        [
            Spacer(1, 0.12 * inch),
            Paragraph("External Cash Flows", section_style),
            Spacer(1, 0.05 * inch)
        ]
    )
    story.append(cash_flow_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def build_daily_ledger(tx, cf, prices):

    start = min(
        tx["Date"].min(),
        cf["Date"].min()
    )

    end = prices.index.max()
    activity_dates = pd.DatetimeIndex(
        pd.concat(
            [
                tx["Date"],
                cf["Date"]
            ]
        ).dropna().unique()
    )
    market_dates = pd.DatetimeIndex(prices.index).normalize()
    dates = market_dates.union(activity_dates).sort_values()
    dates = dates[
        (dates >= start)
        & (dates <= end)
    ]
    prices = prices.reindex(dates).ffill()

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

            if ticker in prices.columns:
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

input_file = st.sidebar.file_uploader(
    "Portfolio Workbook",
    ["xlsx"]
)

tx_password = st.sidebar.text_input(
    "Workbook Password",
    type="password"
)

if input_file:

    try:
        tx, cf = read_workbook(
            input_file,
            password=tx_password.strip() or None
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

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
            "Cashflows tab is missing columns: "
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
            "No common portfolios were found in the Transactions and Cashflows tabs."
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
    cash_flow_table = (
        cf.groupby("Date", as_index=False)["Amount"]
        .sum()
        .sort_values("Date")
    )
    inflow_dates = cf.loc[
        cf["Amount"] > 0,
        "Date"
    ].sort_values()
    start_date = (
        inflow_dates.iloc[0]
        if not inflow_dates.empty
        else cf["Date"].min()
    )
    holdings_table = build_current_holdings(
        tx,
        prices,
        ledger.index.max(),
        ledger.iloc[-1]["Cash"]
    )
    market_cap_allocation = build_market_cap_allocation(
        tx,
        prices,
        ledger.index.max()
    )

    st.subheader(f"Start Date: {format_display_date(start_date)}")

    st.subheader(
        "Growth of Portfolio"
    )

    fig = px.line(
        chart,
        x=chart.index,
        y=chart.columns
    )

    st.plotly_chart(fig, use_container_width=True)

    pie_fig = build_market_cap_pie_figure(
        market_cap_allocation
    )
    if pie_fig is not None:
        st.subheader("Market Cap Allocation")
        left_col, center_col, right_col = st.columns([1, 2, 1])
        with center_col:
            st.plotly_chart(
                pie_fig,
                use_container_width=True
            )

    pdf_bytes = build_pdf_report(
        selected_portfolio,
        start_date,
        current_date,
        ledger.iloc[-1]["Portfolio Value"],
        ledger.iloc[-1]["Cash"],
        summary,
        chart,
        cash_flow_table,
        holdings_table,
        market_cap_allocation
    )

    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name=f"{selected_portfolio}_PortfolioReport.pdf",
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

    st.subheader("Current Holdings")

    display_holdings = holdings_table.copy()
    display_holdings["Weight"] = display_holdings["Weight"].map(
        lambda x: f"{x:.2%}" if pd.notna(x) else ""
    )

    def holdings_style(row):
        if row["Ticker"] == "Cash":
            return ["font-weight: bold"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display_holdings.style.apply(
            holdings_style,
            axis=1
        ),
        use_container_width=True,
        hide_index=True
    )

    st.subheader("External Cash Flows")

    display_cf = cash_flow_table.copy()
    display_cf["Date"] = display_cf["Date"].apply(
        format_display_date
    )
    display_cf["Amount"] = display_cf["Amount"].apply(
        format_inr
    )

    st.dataframe(
        display_cf,
        use_container_width=True,
        hide_index=True
    )

else:
    st.info(
        "Upload one workbook with 'Transactions' and 'Cashflows' tabs to begin."
    )
