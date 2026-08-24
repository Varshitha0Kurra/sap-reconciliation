import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv

# Ensure database is initialized before importing other app modules
from app.database import init_db, get_database_stats, clear_database, get_schema_metadata, get_connection
init_db()

from app.ingestion import (
    load_file_preview, 
    read_full_file,
    validate_po_data, 
    validate_receipt_data, 
    load_pos_to_db, 
    load_receipts_to_db,
    REQUIRED_PO_FIELDS,
    OPTIONAL_PO_FIELDS,
    REQUIRED_RECEIPT_FIELDS
)
from app.schema_mapper import propose_schema_mapping
from app.conversation import ConversationManager
from app.reconciliation import run_reconciliation_flow
from app.gemini_client import is_gemini_configured

# 1. Page Configuration
st.set_page_config(
    page_title="SAP Reconciliation Assistant",
    page_icon="🪻",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Inject CSS for the "Cute + Pretty + Pastel" visual design system
st.markdown("""
<style>
    /* Global Styles */
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        background-color: #FCFAFF !important;
        color: #34313D;
    }
    
    /* Clean Main Container */
    .stApp {
        background-color: #FCFAFF !important;
    }
    
    /* Headers */
    .title-header {
        font-size: 2.0rem;
        font-weight: 700;
        color: #4C3C75;
        letter-spacing: -0.02em;
        margin-bottom: 0.1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .subtitle-header {
        font-size: 0.95rem;
        color: #777180;
        margin-bottom: 1.5rem;
    }
    
    /* Soft Pastel Cards */
    .pane-card {
        background-color: #FFFFFF;
        border: 1px solid #E8E1EE;
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 20px rgba(184, 167, 232, 0.08);
    }
    
    .pane-title {
        font-size: 1.0rem;
        font-weight: 600;
        color: #4C3C75;
        margin-bottom: 0.75rem;
        border-bottom: 1px solid #F1EDF5;
        padding-bottom: 0.4rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    
    /* Soft Green Pill for Ready status */
    .status-badge-ready {
        background-color: #DDF3EA;
        color: #2D6A4F;
        border: 1px solid #C4ECDB;
        padding: 0.25rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        display: inline-block;
    }
    
    .status-badge-empty {
        background-color: #FBE5D2;
        color: #A0522D;
        border: 1px solid #F7D0B4;
        padding: 0.25rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        display: inline-block;
    }
    
    /* DB Stats Indicator Table */
    .stat-row {
        display: flex;
        justify-content: space-between;
        padding: 0.4rem 0;
        border-bottom: 1px solid #FAF8FC;
        font-size: 0.85rem;
    }
    
    .stat-label {
        color: #777180;
    }
    
    .stat-val {
        font-weight: 500;
        color: #4C3C75;
    }
    
    /* Chat Bubbles */
    .chat-bubble {
        padding: 0.9rem 1.1rem;
        border-radius: 12px;
        margin-bottom: 0.8rem;
        line-height: 1.5;
        font-size: 0.92rem;
        max-width: 85%;
        box-shadow: 0 2px 10px rgba(184, 167, 232, 0.04);
    }
    
    .chat-user {
        background-color: #E9E2FA;
        color: #34313D;
        border: 1px solid #D8CCF2;
        margin-left: auto;
        border-bottom-right-radius: 2px;
    }
    
    .chat-assistant {
        background-color: #FFFFFF;
        color: #34313D;
        border: 1px solid #E8E1EE;
        margin-right: auto;
        border-bottom-left-radius: 2px;
    }
    
    .chat-name {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.25rem;
        color: #8C7DAF;
    }
    
    /* Center Empty State */
    .empty-state {
        text-align: center;
        padding: 3rem 1.5rem;
        background-color: #FFFFFF;
        border: 1px solid #E8E1EE;
        border-radius: 16px;
        box-shadow: 0 6px 24px rgba(184, 167, 232, 0.05);
        margin-bottom: 2rem;
    }
    
    .empty-title {
        font-size: 1.4rem;
        font-weight: 700;
        color: #4C3C75;
        margin-bottom: 0.5rem;
    }
    
    .empty-desc {
        font-size: 0.95rem;
        color: #777180;
        margin-bottom: 2rem;
    }
    
    /* Styled Pastel Data Tables */
    .table-container {
        border: 1px solid #E8E1EE;
        border-radius: 10px;
        overflow: hidden;
        margin: 1.25rem 0;
        box-shadow: 0 4px 16px rgba(184, 167, 232, 0.05);
    }
    
    .pastel-table {
        width: 100%;
        border-collapse: collapse;
        color: #34313D;
        font-size: 0.85rem;
        background-color: #FFFFFF;
    }
    
    .pastel-table th {
        background-color: #E9E2FA;
        color: #4C3C75;
        font-weight: 600;
        padding: 0.75rem 1rem;
        border-bottom: 2px solid #D6CAEF;
        text-align: left;
    }
    
    .pastel-table td {
        padding: 0.7rem 1rem;
        border-bottom: 1px solid #F1EDF5;
        background-color: #FFFFFF;
    }
    
    .pastel-table tr:last-child td {
        border-bottom: none;
    }
    
    .pastel-table tr:hover td {
        background-color: #FAF9FD;
    }
    
    .align-left {
        text-align: left;
    }
    
    .align-right {
        text-align: right;
    }
    
    /* Cute Aggregate Metric Cards */
    .metric-card {
        background-color: #E9E2FA;
        border: 1px solid #D6CAEF;
        border-radius: 12px;
        padding: 1.5rem;
        text-align: center;
        max-width: 250px;
        margin: 1rem auto;
        box-shadow: 0 4px 14px rgba(184, 167, 232, 0.12);
    }
    
    .metric-val {
        font-size: 2.2rem;
        font-weight: 700;
        color: #4C3C75;
        line-height: 1.1;
    }
    
    .metric-label {
        font-size: 0.85rem;
        color: #777180;
        font-weight: 500;
        margin-top: 0.4rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Styled Buttons override */
    div.stButton > button {
        background-color: #FFFFFF;
        color: #4C3C75;
        border: 1px solid #D6CAEF;
        border-radius: 20px;
        padding: 0.4rem 1.1rem;
        font-size: 0.88rem;
        font-weight: 500;
        transition: all 0.2s ease-in-out;
        box-shadow: 0 2px 5px rgba(184, 167, 232, 0.08);
    }
    
    div.stButton > button:hover {
        background-color: #E9E2FA;
        border-color: #B8A7E8;
        color: #4C3C75;
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(184, 167, 232, 0.15);
    }
    
    /* Highlight Action Button (Primary) */
    div.stButton > button[kind="primary"] {
        background-color: #B8A7E8 !important;
        color: #FFFFFF !important;
        border: 1px solid #A492DC !important;
        box-shadow: 0 4px 10px rgba(184, 167, 232, 0.2);
    }
    
    div.stButton > button[kind="primary"]:hover {
        background-color: #A492DC !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(184, 167, 232, 0.3);
    }
    
    /* Ambiguity option cards */
    .ambiguity-option {
        background-color: #FFFFFF;
        border: 1px solid #E8E1EE;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        cursor: pointer;
        transition: all 0.2s ease;
        margin-bottom: 0.5rem;
    }
    
    .ambiguity-option:hover {
        background-color: #E9E2FA;
        border-color: #B8A7E8;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(184, 167, 232, 0.15);
    }
    
    .ambiguity-title {
        font-weight: 600;
        color: #4C3C75;
        font-size: 0.95rem;
        margin-bottom: 0.25rem;
    }
    
    .ambiguity-desc {
        font-size: 0.8rem;
        color: #777180;
    }
    
    /* Section headings used for real Streamlit widgets (avoids empty HTML wrapper cards) */
    .section-title {
        font-size: 0.86rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #6B5A8E;
        margin: 0.35rem 0 0.7rem 0;
        padding: 0.35rem 0.15rem 0.55rem 0.15rem;
        border-bottom: 1px solid #EDE6F5;
    }

    .upload-title {
        margin-top: 1rem;
    }

    /* Streamlit uploader: ensure labels and controls remain readable */
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border: 1px solid #E8E1EE;
        border-radius: 12px;
        padding: 0.45rem 0.55rem;
        box-shadow: 0 3px 12px rgba(184, 167, 232, 0.06);
    }

    [data-testid="stFileUploader"] label,
    [data-testid="stFileUploader"] label p {
        color: #4C3C75 !important;
        font-weight: 600 !important;
    }

    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {
        color: #777180 !important;
    }

    [data-testid="stFileUploader"] section {
        background: #FCFAFF !important;
        border: 1px dashed #CFC1E8 !important;
        border-radius: 10px !important;
    }

    [data-testid="stFileUploader"] button {
        color: #4C3C75 !important;
        border-color: #D6CAEF !important;
        background: #FFFFFF !important;
    }

    /* Chat input: soft lavender focus instead of Streamlit red/error styling */
    [data-testid="stChatInput"] {
        background: #FFFFFF !important;
        border: 1px solid #D8CCF2 !important;
        border-radius: 16px !important;
        box-shadow: 0 5px 18px rgba(184, 167, 232, 0.10) !important;
    }

    [data-testid="stChatInput"]:focus-within {
        border-color: #B8A7E8 !important;
        box-shadow: 0 0 0 3px rgba(184, 167, 232, 0.16), 0 5px 18px rgba(184, 167, 232, 0.10) !important;
    }

    [data-testid="stChatInput"] textarea {
        color: #34313D !important;
        background: #FFFFFF !important;
    }

    [data-testid="stChatInput"] textarea::placeholder {
        color: #9B93A8 !important;
    }

    /* Expander labels and uploader headings */
    [data-testid="stExpander"] summary p {
        color: #4C3C75 !important;
        font-weight: 600 !important;
    }

    /* Evidence Technical Panel */
    .evidence-box {
        background-color: #FAF9FC;
        border: 1px solid #E8E1EE;
        border-radius: 8px;
        padding: 0.9rem;
        font-size: 0.85rem;
        color: #34313D;
        margin-top: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# 3. Initialize Session State
if "convo" not in st.session_state:
    st.session_state.convo = ConversationManager()

if "po_upload_df" not in st.session_state:
    st.session_state.po_upload_df = None
if "po_filename" not in st.session_state:
    st.session_state.po_filename = ""
if "po_mapping" not in st.session_state:
    st.session_state.po_mapping = {}

if "receipt_upload_df" not in st.session_state:
    st.session_state.receipt_upload_df = None
if "receipt_filename" not in st.session_state:
    st.session_state.receipt_filename = ""
if "receipt_mapping" not in st.session_state:
    st.session_state.receipt_mapping = {}

if "active_ambiguity" not in st.session_state:
    st.session_state.active_ambiguity = None

# Deterministic helpers for simple record-count questions
def is_invoice_count_question(prompt_text: str) -> bool:
    """Return True only for simple questions asking for the invoice count."""
    q = " ".join(prompt_text.lower().strip().split())
    patterns = [
        "how many invoices are there",
        "how many invoices",
        "number of invoices",
        "count of invoices",
        "invoice count",
    ]
    return any(pattern in q for pattern in patterns) and not any(
        token in q for token in ["po ", "vendor", "value", "amount", "date", "for "]
    )


def get_deterministic_invoice_count():
    """Count actual invoice rows directly from SQLite; do not rely on the LLM plan."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS invoice_count FROM INVOICE_RECEIPT").fetchone()
        return int(row["invoice_count"] if hasattr(row, "keys") else row[0])
    finally:
        conn.close()


def apply_deterministic_invoice_count(prompt_text: str):
    """Build a minimal result object for the simple invoice-count demo question."""
    from types import SimpleNamespace

    count = get_deterministic_invoice_count()
    data = pd.DataFrame({"invoice_count": [count]})
    plan = SimpleNamespace(
        aggregations=[SimpleNamespace(function="COUNT", alias="invoice_count", field="INVOICE_RECEIPT.invoice_number")],
        group_by=[],
        tables=["INVOICE_RECEIPT"],
        filters=[],
    )
    return data, "SELECT COUNT(*) AS invoice_count FROM INVOICE_RECEIPT", plan, count


# Custom suggestion execution function
def execute_selected_prompt(prompt_text: str):
    st.session_state.convo.add_user_message(prompt_text)

    if is_invoice_count_question(prompt_text):
        data, sql, plan, count = apply_deterministic_invoice_count(prompt_text)
        st.session_state.convo.add_assistant_response(
            summary=f"There are {count:,} invoice record(s) in the loaded dataset.",
            sql_executed=sql,
            results_summary=data.to_dict(orient="records"),
        )
        st.session_state.last_result_df = data
        st.session_state.last_result_sql = sql
        st.session_state.last_result_plan = plan
        return
    with st.spinner("✦ Checking your SAP data..."):
        context = st.session_state.convo.get_context_for_prompt()
        res = run_reconciliation_flow(prompt_text, context)
        
        if res["status"] == "ambiguous":
            st.session_state.active_ambiguity = {
                "original_query": prompt_text,
                "reason": res["ambiguity_reason"],
                "choices": res["ambiguity_choices"]
            }
        elif res["status"] == "success":
            st.session_state.convo.add_assistant_response(
                summary=res["answer"],
                sql_executed=res["sql"],
                results_summary=res["results_summary"]
            )
            st.session_state.last_result_df = res["data"]
            st.session_state.last_result_sql = res["sql"]
            st.session_state.last_result_plan = res["plan"]
        else:
            st.error(res.get("error_message", "Error compiling query"))

# 4. Title Header Bar
st.markdown('<div class="title-header">SAP RECONCILIATION ✦</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle-header">Data Intelligence Assistant</div>', unsafe_allow_html=True)

# 5. UI Column Structure: Chat (Left) vs Data Workspace (Right)
col_chat, col_data = st.columns([7.5, 2.5])

# ==========================================
# RIGHT PANEL: Data Sources & SQLite Stats
# ==========================================
with col_data:
    st.markdown('<div class="section-title">♡ DATA STATUS</div>', unsafe_allow_html=True)
    
    db_stats = get_database_stats()
    total_rows = sum(db_stats.values())
    
    if total_rows > 0:
        st.markdown('<span class="status-badge-ready">● Ready to analyze</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-badge-empty">○ Not loaded</span>', unsafe_allow_html=True)
        
    st.markdown("<div style='margin-top: 0.75rem;'></div>", unsafe_allow_html=True)
    
    # Display table records count
    st.markdown(f'<div class="stat-row"><span class="stat-label">Purchase Orders</span><span class="stat-val">{db_stats["PO_HEADER"]:,} rows</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat-row"><span class="stat-label">Receipt Records</span><span class="stat-val">{db_stats["GOODS_RECEIPT"]:,} rows</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat-row"><span class="stat-label">Invoice Records</span><span class="stat-val">{db_stats["INVOICE_RECEIPT"]:,} rows</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat-row"><span class="stat-label">Database Type</span><span class="stat-val">SQLite</span></div>', unsafe_allow_html=True)
    
    # Clear / Load actions
    st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Clear Data", use_container_width=True, key="btn_clear"):
            clear_database()
            st.session_state.convo.clear()
            if "last_result_df" in st.session_state:
                del st.session_state.last_result_df
            st.rerun()
    with col_btn2:
        if st.button("Load Demo", use_container_width=True, key="btn_load_demo"):
            # Demo mode should represent exactly the demo files, so remove
            # stale/manual records before loading them.
            clear_database()

            po_path = "data/mock_po_data.csv"
            receipt_path = "data/mock_receipt_data.csv"
            if not os.path.exists(po_path) or not os.path.exists(receipt_path):
                from scripts.generate_mock_data import generate_data
                generate_data()
                
            # Load PO mock
            df_po = pd.read_csv(po_path)
            po_map = {
                "po_number": "PO Number", "item_number": "Item", "company_code": "Company Code",
                "vendor_id": "Vendor ID", "vendor_name": "Vendor Name", "po_date": "Date",
                "ordered_quantity": "Quantity", "unit_price": "Unit Price", "po_value": "Value",
                "material_id": "Material", "description": "Description", "status": "Status"
            }
            v_po, _ = validate_po_data(df_po, po_map)
            load_pos_to_db(v_po)
            
            # Load Receipts mock
            df_rc = pd.read_csv(receipt_path)
            rc_map = {
                "po_number": "PO Number", "item_number": "Item", "type": "Type",
                "document": "Document", "date": "Date", "quantity": "Quantity", "value": "Value"
            }
            v_rc, invalid_rc = validate_receipt_data(df_rc, rc_map)
            gr_cnt, ir_cnt, fk_warns = load_receipts_to_db(v_rc)

            expected_ir = int(
                df_rc["Type"].astype(str).str.strip().str.upper().isin(
                    ["IR", "INVOICE", "INVOICE RECEIPT"]
                ).sum()
            )

            if invalid_rc:
                st.warning(f"{len(invalid_rc)} receipt/invoice row(s) were rejected during validation.")
                with st.expander("View rejected receipt/invoice rows"):
                    st.write(invalid_rc)

            if fk_warns:
                st.warning(f"{len(fk_warns)} receipt/invoice row(s) were not loaded because their PO/item could not be matched.")
                with st.expander("View unmatched receipt/invoice rows"):
                    st.write(fk_warns)

            if ir_cnt != expected_ir:
                st.error(
                    f"Demo data mismatch: source file contains {expected_ir} invoice row(s), "
                    f"but only {ir_cnt} were loaded into SQLite. Check the validation/FK warnings above."
                )
            else:
                st.success(f"Loaded {gr_cnt} goods receipt(s) and {ir_cnt} invoice(s) from the demo file.")
            
            st.session_state.convo.clear()
            st.toast("Demo data loaded!")
            st.rerun()
            

    # Manual SAP Data Entry
    st.markdown('<div class="section-title upload-title">♡ ENTER SAP DATA</div>', unsafe_allow_html=True)
    st.caption("Type or paste your SAP records directly below — no CSV/Excel upload needed.")

    with st.expander("✦ 1. Purchase Orders", expanded=total_rows == 0):
        st.markdown("**Enter PO header + item data**")
        st.caption("Use one row per PO item. Required fields are marked by the validation step.")

        po_columns = [
            "PO Number", "Item", "Company Code", "Vendor ID", "Vendor Name", "Date",
            "Quantity", "Unit Price", "Value", "Material", "Description", "Status"
        ]
        if "manual_po_df" not in st.session_state:
            st.session_state.manual_po_df = pd.DataFrame([{c: "" for c in po_columns}])

        manual_po = st.data_editor(
            st.session_state.manual_po_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="manual_po_editor",
            column_config={
                "PO Number": st.column_config.TextColumn("PO Number *"),
                "Item": st.column_config.TextColumn("Item *"),
                "Company Code": st.column_config.TextColumn("Company Code"),
                "Vendor ID": st.column_config.TextColumn("Vendor ID"),
                "Vendor Name": st.column_config.TextColumn("Vendor Name"),
                "Date": st.column_config.TextColumn("Date *", help="Use YYYY-MM-DD"),
                "Quantity": st.column_config.NumberColumn("Quantity"),
                "Unit Price": st.column_config.NumberColumn("Unit Price"),
                "Value": st.column_config.NumberColumn("Value"),
                "Material": st.column_config.TextColumn("Material"),
                "Description": st.column_config.TextColumn("Description"),
                "Status": st.column_config.SelectboxColumn("Status", options=["OPEN", "CLOSED", ""], default="OPEN")
            }
        )
        st.session_state.manual_po_df = manual_po

        if st.button("Add Purchase Orders to Database", type="primary", use_container_width=True, key="btn_manual_po"):
            try:
                df_po = manual_po.copy()
                df_po = df_po.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")
                po_map = {
                    "po_number": "PO Number", "item_number": "Item", "company_code": "Company Code",
                    "vendor_id": "Vendor ID", "vendor_name": "Vendor Name", "po_date": "Date",
                    "ordered_quantity": "Quantity", "unit_price": "Unit Price", "po_value": "Value",
                    "material_id": "Material", "description": "Description", "status": "Status"
                }
                valid_rows, invalid_rows = validate_po_data(df_po, po_map)
                if invalid_rows:
                    st.error(f"Validation failed for {len(invalid_rows)} row(s).")
                    with st.expander("View validation errors"):
                        st.write(invalid_rows)
                if valid_rows:
                    load_pos_to_db(valid_rows)
                    st.success(f"Loaded {len(valid_rows)} PO row(s) successfully!")
                    st.session_state.manual_po_df = pd.DataFrame([{c: "" for c in po_columns}])
                    st.rerun()
            except Exception as e:
                st.error(str(e))

    with st.expander("✦ 2. Goods Receipts & Invoices", expanded=total_rows > 0 and db_stats["GOODS_RECEIPT"] == 0):
        st.markdown("**Enter GR and invoice records**")
        st.caption("Set Type to **GR** for a goods receipt or **IR** for an invoice.")

        receipt_columns = ["PO Number", "Item", "Type", "Document", "Date", "Quantity", "Value"]
        if "manual_receipt_df" not in st.session_state:
            st.session_state.manual_receipt_df = pd.DataFrame([{c: "" for c in receipt_columns}])

        manual_receipts = st.data_editor(
            st.session_state.manual_receipt_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="manual_receipt_editor",
            column_config={
                "PO Number": st.column_config.TextColumn("PO Number *"),
                "Item": st.column_config.TextColumn("Item *"),
                "Type": st.column_config.SelectboxColumn("Type *", options=["GR", "IR"], default="GR"),
                "Document": st.column_config.TextColumn("Document *"),
                "Date": st.column_config.TextColumn("Date *", help="Use YYYY-MM-DD"),
                "Quantity": st.column_config.NumberColumn("Quantity"),
                "Value": st.column_config.NumberColumn("Value")
            }
        )
        st.session_state.manual_receipt_df = manual_receipts

        if st.button("Add GR / Invoice Records", type="primary", use_container_width=True, key="btn_manual_receipts"):
            try:
                df_rc = manual_receipts.copy()
                df_rc = df_rc.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")
                rc_map = {
                    "po_number": "PO Number", "item_number": "Item", "type": "Type",
                    "document": "Document", "date": "Date", "quantity": "Quantity", "value": "Value"
                }
                valid_rows, invalid_rows = validate_receipt_data(df_rc, rc_map)
                if invalid_rows:
                    st.error(f"Validation failed for {len(invalid_rows)} row(s).")
                    with st.expander("View validation errors"):
                        st.write(invalid_rows)
                if valid_rows:
                    gr_cnt, ir_cnt, fk_warns = load_receipts_to_db(valid_rows)
                    st.success(f"Loaded {gr_cnt} goods receipt(s) and {ir_cnt} invoice(s)!")
                    if fk_warns:
                        st.warning(fk_warns)
                    st.session_state.manual_receipt_df = pd.DataFrame([{c: "" for c in receipt_columns}])
                    st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("<div class='manual-note'>Tip: You can paste values into the grid, add as many rows as you need, and then load everything into SQLite.</div>", unsafe_allow_html=True)

# ==========================================
# LEFT PANEL: Chat Experience & Metrics (Hero)
# ==========================================
with col_chat:
    if total_rows == 0:
        # Beautiful centered empty state
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-title">✦ SAP Data Reconciliation</div>'
            '<div class="empty-desc">Ask anything about your purchase orders, goods receipts, and invoices using natural language.</div>'
            '</div>',
            unsafe_allow_html=True
        )
        
        st.markdown("##### ♡ Try asking:")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("How many invoices are there?", use_container_width=True, key="q_invoice_cnt"):
                execute_selected_prompt("How many invoices are there?")
                st.rerun()
            if st.button("Which POs have unmatched receipts over $1,000?", use_container_width=True, key="q_unmatched"):
                execute_selected_prompt("Which POs have unmatched receipts over $1,000?")
                st.rerun()
        with col_s2:
            if st.button("Which vendor has the highest total PO value?", use_container_width=True, key="q_vendor_highest"):
                execute_selected_prompt("Which vendor has the highest total PO value?")
                st.rerun()
            if st.button("Show invoices for PO 45000131", use_container_width=True, key="q_invoice_po"):
                execute_selected_prompt("Show invoices for PO 45000131")
                st.rerun()
    else:
        # Render Chat History
        chat_container = st.container()
        with chat_container:
            if not st.session_state.convo.history:
                st.markdown(
                    '<div class="chat-bubble chat-assistant">'
                    '<div class="chat-name">Assistant</div>'
                    '✦ Hello! I have loaded your SAP data successfully. Ask me anything about your records.'
                    '</div>',
                    unsafe_allow_html=True
                )
                
            for msg in st.session_state.convo.history:
                role_class = "chat-user" if msg["role"] == "user" else "chat-assistant"
                role_name = "User" if msg["role"] == "user" else "Assistant"
                st.markdown(
                    f'<div class="chat-bubble {role_class}">'
                    f'<div class="chat-name">{role_name}</div>'
                    f'{msg["content"]}'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
        # Ambiguity Clarification Options UI
        if st.session_state.active_ambiguity:
            amb = st.session_state.active_ambiguity
            st.markdown(f"✦ **Clarification Required:** {amb['reason']}")
            
            # Stylized columns for ambiguity cards
            choice_cols = st.columns(len(amb["choices"]))
            for idx, choice in enumerate(amb["choices"]):
                with choice_cols[idx]:
                    # Create a card layout that responds to click
                    if st.button(choice, key=f"choice_btn_{idx}", use_container_width=True):
                        clarified_query = f"{amb['original_query']} (Context: I mean {choice})"
                        st.session_state.active_ambiguity = None
                        st.session_state.convo.add_user_message(clarified_query)
                        
                        with st.spinner("✦ Reconciling records..."):
                            context = st.session_state.convo.get_context_for_prompt()
                            res = run_reconciliation_flow(clarified_query, context)
                            
                            if res["status"] == "success":
                                st.session_state.convo.add_assistant_response(
                                    summary=res["answer"],
                                    sql_executed=res["sql"],
                                    results_summary=res["results_summary"]
                                )
                                st.session_state.last_result_df = res["data"]
                                st.session_state.last_result_sql = res["sql"]
                                st.session_state.last_result_plan = res["plan"]
                            else:
                                st.error(res.get("error_message", "Error executing query"))
                        st.rerun()
                        
        # Free-form Text Input
        user_query = st.chat_input("Ask anything about your SAP data...")
        if user_query:
            st.session_state.convo.add_user_message(user_query)

            if is_invoice_count_question(user_query):
                data, sql, plan, count = apply_deterministic_invoice_count(user_query)
                st.session_state.convo.add_assistant_response(
                    summary=f"There are {count:,} invoice record(s) in the loaded dataset.",
                    sql_executed=sql,
                    results_summary=data.to_dict(orient="records"),
                )
                st.session_state.last_result_df = data
                st.session_state.last_result_sql = sql
                st.session_state.last_result_plan = plan
                st.rerun()

            with st.spinner("✦ Reconciling the records..."):
                context = st.session_state.convo.get_context_for_prompt()
                res = run_reconciliation_flow(user_query, context)
                
                if res["status"] == "ambiguous":
                    st.session_state.active_ambiguity = {
                        "original_query": user_query,
                        "reason": res["ambiguity_reason"],
                        "choices": res["ambiguity_choices"]
                    }
                elif res["status"] == "success":
                    st.session_state.convo.add_assistant_response(
                        summary=res["answer"],
                        sql_executed=res["sql"],
                        results_summary=res["results_summary"]
                    )
                    st.session_state.last_result_df = res["data"]
                    st.session_state.last_result_sql = res["sql"]
                    st.session_state.last_result_plan = res["plan"]
                else:
                    err_msg = res.get("error_message", "Unknown error")
                    st.session_state.convo.add_assistant_response(
                        summary=f"Unable to answer this question. {err_msg}"
                    )
            st.rerun()
            
        # Display Result Table or Metric Aggregation Card
        if "last_result_df" in st.session_state and st.session_state.last_result_df is not None:
            df = st.session_state.last_result_df
            sql = st.session_state.last_result_sql
            plan = st.session_state.last_result_plan
            
            if not df.empty:
                # Check if it is a scalar aggregate query (exactly one row and one column, and plan contains aggregations without GROUP BY)
                is_scalar_aggregate = len(plan.aggregations) > 0 and not plan.group_by
                
                if is_scalar_aggregate:
                    # Render as an elegant metric card
                    val = df.iloc[0, 0]
                    # Format value
                    col_name = df.columns[0]
                    agg_func = plan.aggregations[0].function
                    
                    # COUNT is always a plain number.
                    # Check it FIRST because aliases such as `count_value`
                    # contain the word "value" and would otherwise be
                    # incorrectly formatted as currency.
                    if str(agg_func).upper() == "COUNT":
                        formatted_val = f"{int(val):,}"
                    elif "value" in col_name.lower() or "price" in col_name.lower() or str(agg_func).upper() in ["SUM", "AVG"]:
                        formatted_val = f"${float(val):,.2f}"
                    elif pd.api.types.is_number(val):
                        numeric_val = float(val)
                        formatted_val = f"{numeric_val:,.0f}" if numeric_val.is_integer() else f"{numeric_val:,.2f}"
                    else:
                        formatted_val = str(val)
                        
                    label = plan.aggregations[0].alias.replace("_", " ").title()
                    
                    st.markdown(
                        f'<div class="metric-card">'
                        f'<div class="metric-val">{formatted_val}</div>'
                        f'<div class="metric-label">{label}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                else:
                    # Render as a beautiful custom styled HTML table
                    st.markdown("##### Database Results:")
                    
                    # Format cell items for visual consistency
                    fmt_df = df.copy()
                    right_align_cols = []
                    for col in fmt_df.columns:
                        if "value" in col.lower() or "price" in col.lower() or "amount" in col.lower():
                            try:
                                fmt_df[col] = fmt_df[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
                                right_align_cols.append(col)
                            except Exception:
                                pass
                        elif "quantity" in col.lower() or "qty" in col.lower() or "count" in col.lower() or "ordered" in col.lower() or "received" in col.lower() or "invoiced" in col.lower():
                            try:
                                fmt_df[col] = fmt_df[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) and x % 1 == 0 else (f"{x:,.2f}" if pd.notna(x) else ""))
                                right_align_cols.append(col)
                            except Exception:
                                pass
                                
                    # Generate HTML table
                    table_html = "<div class='table-container'><table class='pastel-table'><thead><tr>"
                    for col in fmt_df.columns:
                        align_class = "align-right" if col in right_align_cols else "align-left"
                        table_html += f"<th class='{align_class}'>{col}</th>"
                    table_html += "</tr></thead><tbody>"
                    for idx, row in fmt_df.iterrows():
                        table_html += "<tr>"
                        for col in fmt_df.columns:
                            align_class = "align-right" if col in right_align_cols else "align-left"
                            table_html += f"<td class='{align_class}'>{row[col]}</td>"
                        table_html += "</tr>"
                    table_html += "</tbody></table></div>"
                    
                    st.markdown(table_html, unsafe_allow_html=True)
                
                # View Evidence Expandable Section
                with st.expander("⌄ View Evidence"):
                    st.markdown('<div class="evidence-box">', unsafe_allow_html=True)
                    st.markdown(f"**Business Entities Used:** {', '.join([f'`{t}`' for t in plan.tables])}")
                    st.markdown(f"**Physical Tables Query:** {', '.join([f'`{t}`' for t in plan.tables])}")
                    if plan.filters:
                        st.markdown("**Applied Filters:**")
                        for cond in plan.filters:
                            st.markdown(f"- `{cond.field} {cond.operator} {cond.value}`")
                    st.markdown("**Query Logic & Aggregations:**")
                    for agg in plan.aggregations:
                        st.markdown(f"- `{agg.function}({agg.field}) AS {agg.alias}`")
                    st.markdown("**Safe Parameterized SQL:**")
                    st.code(sql, language="sql")
                    st.markdown("**Raw Returned Rows:**")
                    st.dataframe(df, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("I couldn't find any records matching those conditions in the database.")