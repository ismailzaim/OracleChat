# app/formatter.py
#
# Shapes raw Oracle query results into chart-ready JSON.
# Called by routes.py after executor.run_query() succeeds.
#
# Responsibilities:
#   1. Detect the best chart type for the data
#   2. Extract labels and datasets for Chart.js
#   3. Convert Oracle types to JSON-safe Python types
#   4. Return a consistent structure the frontend can always rely on

from datetime import datetime, date
from decimal import Decimal


# ── Type coercion ──────────────────────────────────────────────
def _to_python(value):
    """
    Convert Oracle-specific types to JSON-serialisable Python types.

    Oracle returns Decimal for NUMBER columns and datetime for DATE.
    JSON serialisation fails on both. We normalise here so the rest
    of the code never has to think about Oracle types again.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Preserve decimals as float — acceptable for display purposes
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return value


def _clean_rows(rows: list, columns: list) -> list:
    """Return rows as list of dicts with coerced types."""
    return [
        {col: _to_python(val) for col, val in zip(columns, row)}
        for row in rows
    ]


# ── Chart type detection ───────────────────────────────────────
def _detect_chart_type(columns: list, rows: list) -> str:
    """
    Decide the best Chart.js chart type based on column names and data.

    Rules (in priority order):
    1. If the first column looks like a date/month → LINE chart (trend)
    2. If there are exactly 2 columns and the second is numeric → BAR chart
    3. If there are 2 columns and ≤8 rows → PIE chart (category breakdown)
    4. Default → BAR chart

    Why not let the user choose? They can — this is the smart default.
    The frontend will add a toggle button in a future iteration.
    """
    if not columns or not rows:
        return "bar"

    first_col = columns[0].upper()

    # Date/time patterns → line chart
    time_keywords = ["MONTH", "DATE", "YEAR", "WEEK", "DAY", "PERIOD", "TIME"]
    if any(kw in first_col for kw in time_keywords):
        return "line"

    # Check if first column values look like YYYY-MM date strings
    first_val = str(rows[0].get(columns[0], "")) if rows else ""
    if len(first_val) == 7 and first_val[4] == "-":  # e.g. "2024-01"
        return "line"

    # Few categories → pie chart
    if len(columns) == 2 and len(rows) <= 8:
        return "pie"

    return "bar"


def _extract_chart_data(columns: list, rows: list, chart_type: str) -> dict:
    """
    Build the Chart.js-ready data structure.

    Chart.js expects:
        labels: ["Jan", "Feb", ...]
        datasets: [{ label: "Revenue", data: [100, 200, ...] }]

    We always use the first column as labels and the remaining
    numeric columns as datasets. This handles 1, 2, or 3 numeric
    columns gracefully.
    """
    if not rows:
        return {"labels": [], "datasets": []}

    label_col  = columns[0]
    value_cols = columns[1:]  # Everything after the first column

    labels = [str(row[label_col]) for row in rows]

    # Colour palette — enough for up to 6 datasets
    colours = [
        "rgba(199, 70, 52, 0.8)",    # Oracle red
        "rgba(54, 162, 235, 0.8)",   # blue
        "rgba(75, 192, 192, 0.8)",   # teal
        "rgba(255, 193, 7, 0.8)",    # amber
        "rgba(153, 102, 255, 0.8)",  # purple
        "rgba(255, 159, 64, 0.8)",   # orange
    ]
    border_colours = [c.replace("0.8", "1") for c in colours]

    datasets = []
    for i, col in enumerate(value_cols):
        data = [row.get(col) for row in rows]
        colour = colours[i % len(colours)]
        border = border_colours[i % len(border_colours)]

        dataset = {
            "label":           col.replace("_", " ").title(),
            "data":            data,
            "backgroundColor": colour if chart_type != "line" else "transparent",
            "borderColor":     border,
            "borderWidth":     2,
        }

        if chart_type == "line":
            dataset["fill"]        = False
            dataset["tension"]     = 0.3
            dataset["pointRadius"] = 4

        datasets.append(dataset)

    return {"labels": labels, "datasets": datasets}


# ── Public API ─────────────────────────────────────────────────
def format_result(columns: list, rows: list) -> dict:
    """
    Main entry point — called by routes.py.

    Takes raw executor output and returns a dict containing:
        chart_type  : "bar" | "line" | "pie"
        chart_data  : Chart.js-ready labels + datasets
        table_data  : list of row dicts for the HTML table
        columns     : list of column name strings
        row_count   : int

    The frontend uses chart_data for the visualisation and
    table_data for the raw results table below the chart.
    """
    clean = _clean_rows(rows, columns)
    chart_type = _detect_chart_type(columns, clean)
    chart_data = _extract_chart_data(columns, clean, chart_type)

    return {
        "chart_type": chart_type,
        "chart_data": chart_data,
        "table_data": clean,
        "columns":    columns,
        "row_count":  len(clean),
    }