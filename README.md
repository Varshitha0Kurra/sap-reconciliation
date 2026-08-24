# SAP-Style Data Reconciliation Chatbot

A production-grade, full-stack AI data reconciliation assistant designed to handle SAP-style exports (purchase orders, goods receipts, and invoice receipts). The application allows users to upload their data (CSV or Excel formats), semantically maps their schema, validates transactions, compiles natural language questions into safe, parameterized SQLite SELECT queries, and displays data-grounded summaries alongside verifiable query evidence.

---

## Technical Stack & Core Modules

- **Interface**: [Streamlit](https://streamlit.io/) (Slate/Navy theme, custom CSS)
- **Data Wrangling & Preview**: [Pandas](https://pandas.pydata.org/), [OpenPyXL](https://openpyxl.readthedocs.io/)
- **Database**: [SQLite](https://www.sqlite.org/) (read-only execution bindings)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/) (Strict schemas)
- **AI Planning Layer**: [Google Gemini API](https://ai.google.dev/) (`gemini-2.5-flash`)
- **Testing**: Python `unittest`

---

## Architectural Pipeline

```
                    USER
                      │
             ┌────────┴────────┐
             │                 │
        UPLOAD DATA          CHAT
             │                 │
             ▼                 ▼
      Preview + Mapping   Natural Language
             │                 │
             ▼                 ▼
          Validate          GEMINI
             │                 │
             ▼                 ▼
          SQLITE       Structured Query Plan
                               │
                               ▼
                        Pydantic Validation
                               │
                               ▼
                       Safe SQL Builder
                               │
                               ▼
                            SQLITE
                               │
                               ▼
                         Actual Results
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              Grounded Answer         Evidence
                    │
                    ▼
                   USER
```

---

## Database Relational Schema

SQLite is the relational engine. The tables are structured to reflect standard SAP tables:

1. **`PO_HEADER`** (Purchase Order Header details)
   - `po_number` (TEXT PRIMARY KEY)
   - `company_code` (TEXT)
   - `vendor_id` (TEXT)
   - `vendor_name` (TEXT)
   - `po_date` (TEXT)
   - `currency` (TEXT)
   - `status` (TEXT)

2. **`PO_ITEM`** (Purchase Order Items / Line details)
   - `po_number` (TEXT, FOREIGN KEY to `PO_HEADER(po_number)`)
   - `item_number` (TEXT)
   - `material_id` (TEXT)
   - `description` (TEXT)
   - `ordered_quantity` (REAL)
   - `unit_price` (REAL)
   - `po_value` (REAL)
   - *Composite Primary Key*: `(po_number, item_number)`

3. **`GOODS_RECEIPT`** (Goods Receipts details)
   - `po_number` (TEXT)
   - `item_number` (TEXT)
   - `gr_number` (TEXT PRIMARY KEY)
   - `gr_date` (TEXT)
   - `received_quantity` (REAL)
   - `gr_value` (REAL)
   - *Foreign Key*: `(po_number, item_number)` references `PO_ITEM(po_number, item_number)`

4. **`INVOICE_RECEIPT`** (Invoice Receipts details)
   - `po_number` (TEXT)
   - `item_number` (TEXT)
   - `invoice_number` (TEXT PRIMARY KEY)
   - `invoice_date` (TEXT)
   - `invoice_quantity` (REAL)
   - `invoice_value` (REAL)
   - *Foreign Key*: `(po_number, item_number)` references `PO_ITEM(po_number, item_number)`

---

## Reconciliation Math & Definitions

The application aggregates multiple detail records (receipts/invoices) grouped by `(po_number, item_number)` *before* performing joins. This mathematically prevents duplicate row multiplication.

- **Outstanding PO Value**: `PO_ITEM.po_value - SUM(GOODS_RECEIPT.gr_value)`
- **Uninvoiced Goods Receipts (GRNI)**: `SUM(GOODS_RECEIPT.gr_value) - SUM(INVOICE_RECEIPT.invoice_value)`
- **Invoiced Not Received (IRND)**: `SUM(INVOICE_RECEIPT.invoice_value) - SUM(GOODS_RECEIPT.gr_value)`

---

## Security & Query Safety (Rejection of Non-SELECT Operations)

The chatbot is strictly **read-only**:
- **Structured Planning**: Gemini acts only as a planning layer. It produces a JSON schema defined by a Pydantic `QueryPlan` model. It cannot output direct SQL commands.
- **Whitelist Checking**: Python code validates that all fields, tables, aggregations, and joins conform to a strict schema whitelist. Non-whitelisted tables or SQL operations (e.g., `INSERT`, `UPDATE`, `DELETE`, `DROP`, `;`, `UNION`) are immediately blocked.
- **Formula Token Verification**: Any math/calculated formula is scanned using token-level regex and parsed to block SQL Injection.
- **Query Parameterization**: Builder compiles the query using `?` parameter placeholders. Bound parameters are executed separate from the SQL string.

---

## Ambiguity Resolution & Context Memory

- **Ambiguity Detection**: If the query planner detects vague nouns (e.g. *"Show receipts"*) or vague numbers (e.g. *"Show values over 1000"*), it marks the plan as ambiguous and provides options. The UI stops execution and presents interactive choices to let the user clarify.
- **Conversational Memory**: The last 5 turns of conversation context are sent to the planner. Pronouns like *"those"* or *"them"* (e.g. *"Which of those are above $5,000?"*) are resolved against the previous results and filters.

---

## Grounding & Evidence

- **Database-Grounded Answers**: Gemini is supplied the SQL result set. It compiles a summary grounded strictly in that data. If SQLite returns 0 rows, the chatbot displays: *"I couldn't find any records matching those conditions."* It never fabricates records.
- **View Evidence Drawer**: A collapsible component below every answer containing:
  - Business entities and physical tables used
  - Applied filters and parameters
  - Parameterized SQL query executed
  - Complete DataFrame of matching records

---

## Local Setup

### 1. Requirements & Configuration
Install Python 3.8+ and clone/setup the directory structure.

### 2. Installation
Run the following in the project root:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

### 4. Running the Chatbot
Start the Streamlit application:
```bash
streamlit run app/main.py
```

### 5. Running Automated Tests
Run the test suite:
```bash
python -m unittest tests/test_all.py
```

---

## Demo Walkthrough Guide

1. Start the application without data. The app shows the empty state.
2. Click **Load Demo Data** in the Database Status panel to instantly populate the SQLite database.
3. Ask: `"Which POs have unmatched receipts over $1,000?"`
   - *Result*: Chatbot detects ambiguity and prompts you to select GRNI, IRND, or Outstanding. Click **Goods Received vs. Invoiced (GRNI)**.
   - *Result*: Renders the matching POs, quantities, and values in a formatted table, alongside a text summary and a **View Evidence** drawer.
4. Ask: `"Which vendor has the highest total PO value?"`
   - *Result*: Identifies Vendor V006.
5. Ask: `"Show me the invoices for that vendor."`
   - *Result*: Resolves "that vendor" as Vendor V006 and pulls invoices.
6. Ask: `"Which of those are above $5,000?"`
   - *Result*: Filters the invoice list to show only records above $5,000.
7. Ask: `"Show me the receipts."`
   - *Result*: Chatbot asks: *"Do you mean Goods Receipts or Invoice Receipts?"*
