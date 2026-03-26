# oracle/schema_metadata.py
#
# Human-readable description of the OracleChat e-commerce schema.
# This is the RAG knowledge base — rag.py reads this and injects
# relevant context into every Gemini prompt.
#
# Rules for maintaining this file:
#   1. Every column gets a description — never leave it blank
#   2. business_questions shows the LLM what each table is FOR
#   3. join_paths tells the LLM exactly how to connect tables
#   4. sample_queries are few-shot examples — the single biggest
#      factor in getting correct Oracle SQL from the LLM

SCHEMA_NAME = "ORACLECHAT"

# ── Table metadata ─────────────────────────────────────────────
TABLES = {

    "CUSTOMERS": {
        "description": (
            "Registered users of the e-commerce platform. "
            "Each row is one unique customer. "
            "Use this table for customer demographics, location analysis, "
            "and filtering orders by customer attributes."
        ),
        "columns": {
            "CUSTOMER_ID":       "Surrogate primary key. Use in JOINs with ORDERS.CUSTOMER_ID.",
            "FIRST_NAME":        "Customer first name.",
            "LAST_NAME":         "Customer last name. Concatenate with FIRST_NAME for full name: FIRST_NAME || ' ' || LAST_NAME.",
            "EMAIL":             "Unique email address — the business identifier for a customer.",
            "PHONE":             "Moroccan phone number in format +212XXXXXXXXX.",
            "CITY":              "Moroccan city where the customer lives. Values: Casablanca, Rabat, Marrakech, Fes, Tangier, Agadir, Meknes, Oujda, Kenitra, Tetouan.",
            "COUNTRY":           "Always 'Morocco' in this dataset.",
            "REGISTRATION_DATE": "DATE when the customer created their account. Use TO_CHAR(registration_date, 'YYYY-MM') for monthly grouping.",
            "STATUS":            "Account status. Values: ACTIVE, INACTIVE, BANNED. Most customers are ACTIVE.",
        },
        "business_questions": [
            "How many customers registered per month?",
            "Which city has the most customers?",
            "How many active vs inactive customers do we have?",
            "Who are our top customers by total spend?",
        ],
    },

    "PRODUCTS": {
        "description": (
            "The product catalog. Each row is one product the store sells. "
            "Use this table to analyze what is being sold, at what price, "
            "and to break down revenue by category."
        ),
        "columns": {
            "PRODUCT_ID":      "Surrogate primary key. Use in JOINs with ORDER_ITEMS.PRODUCT_ID.",
            "NAME":            "Product name, e.g. 'Laptop Pro 15', 'Argan Hair Oil'.",
            "CATEGORY":        "Product category. Values: Electronics, Books, Clothing, 'Home and Kitchen', Sports, Beauty.",
            "UNIT_PRICE":      "Current selling price in MAD (Moroccan Dirham). NUMBER(10,2). Note: ORDER_ITEMS.UNIT_PRICE stores the price at time of purchase which may differ.",
            "STOCK_QUANTITY":  "Current units in stock. NUMBER(10). Can be 0.",
            "STATUS":          "Values: ACTIVE (available for sale), DISCONTINUED (no longer sold).",
        },
        "business_questions": [
            "Which product category generates the most revenue?",
            "What are the top 10 best-selling products?",
            "Which products are out of stock?",
            "What is the average price per category?",
            "Which products have been discontinued?",
        ],
    },

    "ORDERS": {
        "description": (
            "Customer purchase orders. Each row is one order placed by one customer. "
            "An order contains one or more products (see ORDER_ITEMS). "
            "Use this table for revenue analysis, order volume trends, and status tracking."
        ),
        "columns": {
            "ORDER_ID":          "Surrogate primary key. Use in JOINs with ORDER_ITEMS.ORDER_ID and PAYMENTS.ORDER_ID.",
            "CUSTOMER_ID":       "Foreign key to CUSTOMERS.CUSTOMER_ID.",
            "ORDER_DATE":        "DATE the order was placed. Use TO_CHAR(order_date, 'YYYY-MM') for monthly trends.",
            "STATUS":            "Order lifecycle status. Values: PENDING, CONFIRMED, SHIPPED, DELIVERED, CANCELLED, RETURNED. Use DELIVERED for completed revenue calculations.",
            "TOTAL_AMOUNT":      "Total order value in MAD. NUMBER(12,2). Sum of all ORDER_ITEMS.LINE_TOTAL for this order.",
            "SHIPPING_ADDRESS":  "Street address where the order was shipped.",
        },
        "business_questions": [
            "What is the total revenue this month?",
            "How many orders were placed per month?",
            "What is the average order value?",
            "How many orders were cancelled or returned?",
            "What is the revenue trend over the past 12 months?",
        ],
    },

    "ORDER_ITEMS": {
        "description": (
            "Individual line items within an order. "
            "Each row is one product within one order. "
            "This is the central fact table — join it with ORDERS for revenue "
            "and with PRODUCTS for product-level analysis. "
            "One order has one or more order items."
        ),
        "columns": {
            "ITEM_ID":     "Surrogate primary key.",
            "ORDER_ID":    "Foreign key to ORDERS.ORDER_ID.",
            "PRODUCT_ID":  "Foreign key to PRODUCTS.PRODUCT_ID.",
            "QUANTITY":    "Number of units purchased. NUMBER(5). Always >= 1.",
            "UNIT_PRICE":  "Price per unit AT TIME OF PURCHASE in MAD. May differ from PRODUCTS.UNIT_PRICE if the product price changed later.",
            "LINE_TOTAL":  "QUANTITY * UNIT_PRICE. Pre-computed for performance. Use this for revenue calculations, not quantity * products.unit_price.",
        },
        "business_questions": [
            "Which products appear most often in orders?",
            "What is the total quantity sold per product?",
            "What is the revenue contribution of each product?",
            "Which orders contain a specific product?",
        ],
    },

    "PAYMENTS": {
        "description": (
            "Payment transactions against orders. "
            "Each row is one payment attempt. "
            "An order can have multiple payment rows (e.g. a failed attempt followed by a successful one). "
            "Use STATUS = 'COMPLETED' for confirmed revenue. "
            "Use STATUS = 'REFUNDED' for returned order analysis."
        ),
        "columns": {
            "PAYMENT_ID":    "Surrogate primary key.",
            "ORDER_ID":      "Foreign key to ORDERS.ORDER_ID.",
            "PAYMENT_DATE":  "DATE the payment was processed.",
            "AMOUNT":        "Payment amount in MAD. NUMBER(12,2).",
            "METHOD":        "Payment method. Values: CREDIT_CARD, DEBIT_CARD, BANK_TRANSFER, CASH_ON_DELIVERY, MOBILE_PAYMENT.",
            "STATUS":        "Values: COMPLETED (successful), PENDING (processing), FAILED (declined), REFUNDED (returned order).",
        },
        "business_questions": [
            "What is the most popular payment method?",
            "How much revenue was collected via credit card?",
            "Which orders have failed payments?",
            "How many refunds were issued this month?",
        ],
    },
}


# ── Join paths ─────────────────────────────────────────────────
# Explicit join instructions for the LLM.
# Without this, Gemini sometimes invents incorrect join conditions.
JOIN_PATHS = [
    {
        "tables": ["CUSTOMERS", "ORDERS"],
        "condition": "CUSTOMERS.CUSTOMER_ID = ORDERS.CUSTOMER_ID",
        "note": "One customer can have many orders.",
    },
    {
        "tables": ["ORDERS", "ORDER_ITEMS"],
        "condition": "ORDERS.ORDER_ID = ORDER_ITEMS.ORDER_ID",
        "note": "One order contains one or more items.",
    },
    {
        "tables": ["PRODUCTS", "ORDER_ITEMS"],
        "condition": "PRODUCTS.PRODUCT_ID = ORDER_ITEMS.PRODUCT_ID",
        "note": "One product can appear in many order items.",
    },
    {
        "tables": ["ORDERS", "PAYMENTS"],
        "condition": "ORDERS.ORDER_ID = PAYMENTS.ORDER_ID",
        "note": "One order can have one or more payment attempts.",
    },
    {
        "tables": ["CUSTOMERS", "ORDERS", "ORDER_ITEMS", "PRODUCTS"],
        "condition": (
            "CUSTOMERS.CUSTOMER_ID = ORDERS.CUSTOMER_ID "
            "AND ORDERS.ORDER_ID = ORDER_ITEMS.ORDER_ID "
            "AND ORDER_ITEMS.PRODUCT_ID = PRODUCTS.PRODUCT_ID"
        ),
        "note": "Full chain for customer-product analysis.",
    },
]


# ── Oracle-specific rules ──────────────────────────────────────
# These are injected into every prompt to prevent common LLM mistakes
# when generating Oracle SQL specifically.
ORACLE_RULES = [
    "Use Oracle 19c SQL syntax only. Do NOT use MySQL or PostgreSQL syntax.",
    "To limit rows, use FETCH FIRST N ROWS ONLY — not LIMIT N.",
    "To get the current date, use SYSDATE — not NOW() or CURRENT_DATE.",
    "For string concatenation, use || — not + or CONCAT().",
    "For date formatting, use TO_CHAR(date_column, 'YYYY-MM') — not DATE_FORMAT().",
    "Column and table names are uppercase in Oracle. Always write them in uppercase.",
    "Do not use backticks. Oracle uses double quotes for identifiers if needed, but prefer no quoting.",
    "For top-N queries, use FETCH FIRST N ROWS ONLY after ORDER BY.",
    "All monetary values are in MAD (Moroccan Dirham).",
    "When filtering for completed revenue, use ORDERS.STATUS = 'DELIVERED'.",
    "When filtering for confirmed payments, use PAYMENTS.STATUS = 'COMPLETED'.",
]


# ── Few-shot examples ──────────────────────────────────────────
# These are the most powerful part of the RAG context.
# Each example shows the LLM exactly what good Oracle SQL looks like
# for this schema. Include one example per major query pattern.
SAMPLE_QUERIES = [
    {
        "question": "Who are the top 5 customers by total spending?",
        "sql": """
SELECT c.first_name || ' ' || c.last_name AS customer_name,
       c.city,
       COUNT(o.order_id)   AS total_orders,
       SUM(o.total_amount) AS total_spent
FROM   customers c
JOIN   orders o ON o.customer_id = c.customer_id
WHERE  o.status = 'DELIVERED'
GROUP  BY c.customer_id, c.first_name, c.last_name, c.city
ORDER  BY total_spent DESC
FETCH  FIRST 5 ROWS ONLY
""".strip(),
    },
    {
        "question": "What is the monthly revenue trend?",
        "sql": """
SELECT TO_CHAR(order_date, 'YYYY-MM') AS month,
       COUNT(*)                        AS order_count,
       SUM(total_amount)               AS revenue
FROM   orders
WHERE  status = 'DELIVERED'
GROUP  BY TO_CHAR(order_date, 'YYYY-MM')
ORDER  BY month
""".strip(),
    },
    {
        "question": "Which product category generates the most revenue?",
        "sql": """
SELECT p.category,
       SUM(oi.line_total)            AS revenue,
       COUNT(DISTINCT oi.order_id)   AS orders_count,
       SUM(oi.quantity)              AS units_sold
FROM   order_items oi
JOIN   products p ON p.product_id = oi.product_id
JOIN   orders o   ON o.order_id   = oi.order_id
WHERE  o.status = 'DELIVERED'
GROUP  BY p.category
ORDER  BY revenue DESC
""".strip(),
    },
    {
        "question": "What is the most popular payment method?",
        "sql": """
SELECT method,
       COUNT(*)       AS payment_count,
       SUM(amount)    AS total_amount
FROM   payments
WHERE  status = 'COMPLETED'
GROUP  BY method
ORDER  BY payment_count DESC
""".strip(),
    },
    {
        "question": "How many orders were placed per city?",
        "sql": """
SELECT c.city,
       COUNT(o.order_id)   AS total_orders,
       SUM(o.total_amount) AS total_revenue
FROM   customers c
JOIN   orders o ON o.customer_id = c.customer_id
GROUP  BY c.city
ORDER  BY total_orders DESC
""".strip(),
    },
]


# ── Helper used by rag.py ──────────────────────────────────────
def get_full_context() -> str:
    """
    Returns the complete schema context as a formatted string.
    rag.py calls this and injects the result into the Gemini prompt.
    """
    parts = []

    parts.append("=== DATABASE SCHEMA ===")
    parts.append(f"Schema owner: {SCHEMA_NAME}")
    parts.append("")

    for table_name, meta in TABLES.items():
        parts.append(f"TABLE: {table_name}")
        parts.append(f"Description: {meta['description']}")
        parts.append("Columns:")
        for col, desc in meta["columns"].items():
            parts.append(f"  - {col}: {desc}")
        parts.append("")

    parts.append("=== JOIN CONDITIONS ===")
    for jp in JOIN_PATHS:
        tables = " + ".join(jp["tables"])
        parts.append(f"{tables}: {jp['condition']}  -- {jp['note']}")
    parts.append("")

    parts.append("=== ORACLE SQL RULES ===")
    for rule in ORACLE_RULES:
        parts.append(f"- {rule}")
    parts.append("")

    parts.append("=== EXAMPLE QUERIES ===")
    for ex in SAMPLE_QUERIES:
        parts.append(f"Q: {ex['question']}")
        parts.append(f"SQL:\n{ex['sql']}")
        parts.append("")

    return "\n".join(parts)


def get_table_names() -> list:
    """Returns list of all table names. Used by rag.py for keyword matching."""
    return list(TABLES.keys())


def get_tables_for_question(question: str) -> list:
    """
    Simple keyword-based table selector.
    rag.py uses this to inject only relevant tables into the prompt,
    keeping the context window lean for simple questions.
    """
    question_upper = question.upper()
    relevant = []

    keywords = {
        "CUSTOMERS": ["CUSTOMER", "USER", "CLIENT", "WHO", "CITY", "REGISTR"],
        "PRODUCTS":  ["PRODUCT", "ITEM", "CATEGORY", "PRICE", "STOCK", "SELL"],
        "ORDERS":    ["ORDER", "REVENUE", "SALES", "MONTHLY", "TREND", "TOTAL"],
        "ORDER_ITEMS": ["ITEM", "QUANTITY", "UNITS", "LINE", "SOLD", "POPULAR"],
        "PAYMENTS":  ["PAYMENT", "METHOD", "PAID", "REFUND", "CREDIT", "CASH"],
    }

    for table, kws in keywords.items():
        if any(kw in question_upper for kw in kws):
            relevant.append(table)

    # Always include ORDERS — it is the central fact table
    if "ORDERS" not in relevant:
        relevant.append("ORDERS")

    return relevant