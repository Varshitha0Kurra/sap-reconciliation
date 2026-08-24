import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional
from database import get_connection

REQUIRED_PO_FIELDS = {
    "po_number": "PO Number",
    "item_number": "Item Number",
    "vendor_id": "Vendor ID",
    "vendor_name": "Vendor Name",
    "po_date": "PO Date",
    "ordered_quantity": "Quantity",
    "unit_price": "Unit Price"
}

OPTIONAL_PO_FIELDS = {
    "company_code": "Company Code",
    "currency": "Currency",
    "status": "Status",
    "material_id": "Material ID",
    "description": "Description",
    "po_value": "PO Value"
}

REQUIRED_RECEIPT_FIELDS = {
    "po_number": "PO Number",
    "item_number": "Item Number",
    "type": "Document Type (GR/IR)",
    "document": "Document Number",
    "date": "Document Date",
    "quantity": "Quantity",
    "value": "Value"
}


def normalize_item_number(value: Any) -> str:
    """Normalize SAP item numbers consistently across CSV, Excel and SQLite.

    Handles values such as 10, "10", "00010", and 10.0 and converts
    them all to the canonical SAP representation "00010".
    """
    if pd.isna(value):
        return ""

    text = str(value).strip()
    if not text:
        return ""

    # CSV/Excel may turn an integer-looking value into a float string.
    try:
        numeric = float(text)
        if numeric.is_integer():
            return f"{int(numeric):05d}"
    except (TypeError, ValueError):
        pass

    return text.zfill(5) if text.isdigit() else text

def load_file_preview(file_path_or_buffer: Any, is_excel: bool = False) -> Tuple[pd.DataFrame, int]:
    """Reads the first few rows of a file for preview and returns the full row count."""
    try:
        if is_excel:
            df = pd.read_excel(file_path_or_buffer)
        else:
            df = pd.read_csv(file_path_or_buffer)
        
        # Replace NaN with None for consistent JSON/None representation
        preview_df = df.head(10).replace({np.nan: None})
        return preview_df, len(df)
    except Exception as e:
        raise ValueError(f"Failed to read file: {str(e)}")

def read_full_file(file_path_or_buffer: Any, is_excel: bool = False) -> pd.DataFrame:
    """Reads the entire file into a Pandas DataFrame."""
    if is_excel:
        return pd.read_excel(file_path_or_buffer)
    return pd.read_csv(file_path_or_buffer)

def validate_po_data(df: pd.DataFrame, mapping: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Validates PO data against the mapping.
    Returns:
        - valid_rows: list of clean dicts ready for insertion
        - invalid_rows: list of dicts with validation errors
    """
    valid_rows = []
    invalid_rows = []
    
    # Check if required columns are present in mapping
    missing_required = [field for field, col in REQUIRED_PO_FIELDS.items() if field not in mapping or not mapping[field]]
    if missing_required:
        raise ValueError(f"Missing required mappings for: {', '.join([REQUIRED_PO_FIELDS[f] for f in missing_required])}")
        
    for index, row in df.iterrows():
        errors = []
        row_data = {}
        
        # Validate po_number
        po_col = mapping.get("po_number")
        po_val = str(row[po_col]).strip() if pd.notna(row[po_col]) else ""
        if not po_val:
            errors.append("PO Number is required")
        row_data["po_number"] = po_val
        
        # Validate item_number
        item_col = mapping.get("item_number")
        item_val = str(row[item_col]).strip() if pd.notna(row[item_col]) else ""
        if not item_val:
            errors.append("Item Number is required")
        # Standardize item number consistently (handles 10, "10", "00010", 10.0)
        item_val = normalize_item_number(item_val)
        row_data["item_number"] = item_val
        
        # Validate vendor_id and vendor_name
        v_id_col = mapping.get("vendor_id")
        v_id_val = str(row[v_id_col]).strip() if pd.notna(row[v_id_col]) else ""
        if not v_id_val:
            errors.append("Vendor ID is required")
        row_data["vendor_id"] = v_id_val
        
        v_name_col = mapping.get("vendor_name")
        v_name_val = str(row[v_name_col]).strip() if pd.notna(row[v_name_col]) else ""
        if not v_name_val:
            errors.append("Vendor Name is required")
        row_data["vendor_name"] = v_name_val
        
        # Validate po_date
        date_col = mapping.get("po_date")
        date_raw = row[date_col]
        date_val = ""
        if pd.isna(date_raw):
            errors.append("PO Date is required")
        else:
            try:
                # Attempt to parse date
                if isinstance(date_raw, datetime):
                    date_val = date_raw.strftime("%Y-%m-%d")
                else:
                    parsed_date = pd.to_datetime(str(date_raw).strip())
                    date_val = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                errors.append(f"Invalid Date format: {date_raw}")
        row_data["po_date"] = date_val
        
        # Validate quantity and price
        qty_col = mapping.get("ordered_quantity")
        qty_val = 0.0
        try:
            qty_val = float(row[qty_col])
            if qty_val <= 0:
                errors.append("Quantity must be greater than 0")
        except Exception:
            errors.append(f"Invalid Quantity: {row[qty_col]}")
        row_data["ordered_quantity"] = qty_val
        
        price_col = mapping.get("unit_price")
        price_val = 0.0
        try:
            price_val = float(row[price_col])
            if price_val < 0:
                errors.append("Unit Price must be non-negative")
        except Exception:
            errors.append(f"Invalid Unit Price: {row[price_col]}")
        row_data["unit_price"] = price_val
        
        # Handle optional fields
        # company_code
        cc_col = mapping.get("company_code")
        row_data["company_code"] = str(row[cc_col]).strip() if cc_col and pd.notna(row[cc_col]) else "1000"
        
        # currency
        cur_col = mapping.get("currency")
        row_data["currency"] = str(row[cur_col]).strip() if cur_col and pd.notna(row[cur_col]) else "USD"
        
        # status
        stat_col = mapping.get("status")
        row_data["status"] = str(row[stat_col]).strip().upper() if stat_col and pd.notna(row[stat_col]) else "OPEN"
        
        # material_id
        mat_col = mapping.get("material_id")
        row_data["material_id"] = str(row[mat_col]).strip() if mat_col and pd.notna(row[mat_col]) else ""
        
        # description
        desc_col = mapping.get("description")
        row_data["description"] = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else ""
        
        # po_value (calculate if not mapped or empty)
        val_col = mapping.get("po_value")
        val_val = 0.0
        if val_col and pd.notna(row[val_col]):
            try:
                val_val = float(row[val_col])
            except Exception:
                val_val = qty_val * price_val
        else:
            val_val = qty_val * price_val
        row_data["po_value"] = val_val
        
        # Record details
        record_desc = f"PO {row_data.get('po_number') or 'None'} Item {row_data.get('item_number') or 'None'}"
        if errors:
            invalid_rows.append({
                "row_index": index + 1,
                "record": record_desc,
                "errors": errors,
                "raw": row.to_dict()
            })
        else:
            valid_rows.append(row_data)
            
    # Check for duplicate composite keys in valid rows
    seen_keys = set()
    cleaned_valid_rows = []
    for r in valid_rows:
        key = (str(r["po_number"]).strip(), normalize_item_number(r["item_number"]))
        if key in seen_keys:
            invalid_rows.append({
                "row_index": "Duplicate in file",
                "record": f"PO {r['po_number']} Item {r['item_number']}",
                "errors": ["Duplicate PO number and Item Number combination in upload file"],
                "raw": r
            })
        else:
            seen_keys.add(key)
            cleaned_valid_rows.append(r)
            
    return cleaned_valid_rows, invalid_rows

def validate_receipt_data(df: pd.DataFrame, mapping: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Validates Receipt/Invoice data against mapping.
    Returns:
        - valid_rows: list of clean dicts ready for insertion
        - invalid_rows: list of dicts with validation errors
    """
    valid_rows = []
    invalid_rows = []
    
    missing_required = [field for field, col in REQUIRED_RECEIPT_FIELDS.items() if field not in mapping or not mapping[field]]
    if missing_required:
        raise ValueError(f"Missing required mappings for: {', '.join([REQUIRED_RECEIPT_FIELDS[f] for f in missing_required])}")
        
    for index, row in df.iterrows():
        errors = []
        row_data = {}
        
        # po_number
        po_col = mapping.get("po_number")
        po_val = str(row[po_col]).strip() if pd.notna(row[po_col]) else ""
        if not po_val:
            errors.append("PO Number is required")
        row_data["po_number"] = po_val
        
        # item_number
        item_col = mapping.get("item_number")
        item_val = str(row[item_col]).strip() if pd.notna(row[item_col]) else ""
        if not item_val:
            errors.append("Item Number is required")
        item_val = normalize_item_number(item_val)
        row_data["item_number"] = item_val
        
        # type: GR or IR
        type_col = mapping.get("type")
        type_val = str(row[type_col]).strip().upper() if pd.notna(row[type_col]) else ""
        if type_val not in ["GR", "IR", "GOODS RECEIPT", "INVOICE RECEIPT", "INVOICE"]:
            errors.append(f"Document Type must be GR or IR, got: {type_val}")
        
        # Standardize Type
        if type_val in ["GR", "GOODS RECEIPT"]:
            row_data["type"] = "GR"
        elif type_val in ["IR", "INVOICE RECEIPT", "INVOICE"]:
            row_data["type"] = "IR"
        else:
            row_data["type"] = ""
            
        # document
        doc_col = mapping.get("document")
        doc_val = str(row[doc_col]).strip() if pd.notna(row[doc_col]) else ""
        if not doc_val:
            errors.append("Document Number is required")
        row_data["document"] = doc_val
        
        # date
        date_col = mapping.get("date")
        date_raw = row[date_col]
        date_val = ""
        if pd.isna(date_raw):
            errors.append("Document Date is required")
        else:
            try:
                if isinstance(date_raw, datetime):
                    date_val = date_raw.strftime("%Y-%m-%d")
                else:
                    parsed_date = pd.to_datetime(str(date_raw).strip())
                    date_val = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                errors.append(f"Invalid Date format: {date_raw}")
        row_data["date"] = date_val
        
        # quantity
        qty_col = mapping.get("quantity")
        qty_val = 0.0
        try:
            qty_val = float(row[qty_col])
        except Exception:
            errors.append(f"Invalid Quantity: {row[qty_col]}")
        row_data["quantity"] = qty_val
        
        # value
        val_col = mapping.get("value")
        val_val = 0.0
        try:
            val_val = float(row[val_col])
        except Exception:
            errors.append(f"Invalid Value: {row[val_col]}")
        row_data["value"] = val_val
        
        record_desc = f"Type {row_data.get('type') or 'None'} Doc {row_data.get('document') or 'None'} for PO {row_data.get('po_number')} Item {row_data.get('item_number')}"
        if errors:
            invalid_rows.append({
                "row_index": index + 1,
                "record": record_desc,
                "errors": errors,
                "raw": row.to_dict()
            })
        else:
            valid_rows.append(row_data)
            
    # De-duplicate document numbers in valid rows to enforce PRIMARY KEY limits
    seen_grs = set()
    seen_irs = set()
    cleaned_valid_rows = []
    
    for r in valid_rows:
        doc = r["document"]
        if r["type"] == "GR":
            if doc in seen_grs:
                invalid_rows.append({
                    "row_index": "Duplicate in file",
                    "record": f"GR Document {doc}",
                    "errors": [f"Duplicate Goods Receipt document number '{doc}' in file"],
                    "raw": r
                })
            else:
                seen_grs.add(doc)
                cleaned_valid_rows.append(r)
        else: # IR
            if doc in seen_irs:
                invalid_rows.append({
                    "row_index": "Duplicate in file",
                    "record": f"Invoice Document {doc}",
                    "errors": [f"Duplicate Invoice document number '{doc}' in file"],
                    "raw": r
                })
            else:
                seen_irs.add(doc)
                cleaned_valid_rows.append(r)
                
    return cleaned_valid_rows, invalid_rows

def load_pos_to_db(valid_rows: List[Dict[str, Any]]):
    """Inserts validated PO header and line items into SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # We need to de-duplicate headers since we split a single PO header/line row
        headers = {}
        for r in valid_rows:
            po_num = r["po_number"]
            if po_num not in headers:
                headers[po_num] = (
                    r["po_number"],
                    r["company_code"],
                    r["vendor_id"],
                    r["vendor_name"],
                    r["po_date"],
                    r["currency"],
                    r["status"]
                )
                
        # Insert PO Headers
        cursor.executemany("""
            INSERT OR REPLACE INTO PO_HEADER (po_number, company_code, vendor_id, vendor_name, po_date, currency, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, list(headers.values()))
        
        # Insert PO Items
        items_data = [
            (
                r["po_number"],
                r["item_number"],
                r["material_id"],
                r["description"],
                r["ordered_quantity"],
                r["unit_price"],
                r["po_value"]
            )
            for r in valid_rows
        ]
        cursor.executemany("""
            INSERT OR REPLACE INTO PO_ITEM (po_number, item_number, material_id, description, ordered_quantity, unit_price, po_value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, items_data)
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def load_receipts_to_db(valid_rows: List[Dict[str, Any]]) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Inserts validated Receipts/Invoices into SQLite.
    Checks that the referenced PO/Item exists in the database.
    Returns:
        - inserted_gr: count of inserted GRs
        - inserted_ir: count of inserted IRs
        - foreign_key_warnings: list of rows that don't match any PO item in DB
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # First, query all existing PO Items in the DB to check FK integrity
    cursor.execute("SELECT po_number, item_number FROM PO_ITEM")
    existing_po_items = {
        (str(r["po_number"]).strip(), normalize_item_number(r["item_number"]))
        for r in cursor.fetchall()
    }
    
    gr_data = []
    ir_data = []
    warnings = []
    
    for r in valid_rows:
        key = (str(r["po_number"]).strip(), normalize_item_number(r["item_number"]))
        if key not in existing_po_items:
            # We collect these as warnings rather than crashing, so the user sees orphan records
            warnings.append({
                "record": f"{r['type']} Doc {r['document']}",
                "error": f"PO {r['po_number']} Item {r['item_number']} does not exist in PO_ITEM table."
            })
            continue
            
        if r["type"] == "GR":
            gr_data.append((
                r["po_number"],
                r["item_number"],
                r["document"],
                r["date"],
                r["quantity"],
                r["value"]
            ))
        else: # IR
            ir_data.append((
                r["po_number"],
                r["item_number"],
                r["document"],
                r["date"],
                r["quantity"],
                r["value"]
            ))
            
    try:
        if gr_data:
            cursor.executemany("""
                INSERT OR REPLACE INTO GOODS_RECEIPT (po_number, item_number, gr_number, gr_date, received_quantity, gr_value)
                VALUES (?, ?, ?, ?, ?, ?)
            """, gr_data)
            
        if ir_data:
            cursor.executemany("""
                INSERT OR REPLACE INTO INVOICE_RECEIPT (po_number, item_number, invoice_number, invoice_date, invoice_quantity, invoice_value)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ir_data)
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
        
    return len(gr_data), len(ir_data), warnings