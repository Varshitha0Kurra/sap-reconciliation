import sqlite3
import os
from typing import Dict, List, Tuple, Any

DB_PATH = os.path.join("data", "sap_reconciliation.db")

def get_connection(read_only: bool = False) -> sqlite3.Connection:
    """Gets a connection to the SQLite database. Creates directory if missing."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if read_only and os.path.exists(DB_PATH):
        # Open in read-only mode for query execution safety
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    
    conn.execute("PRAGMA foreign_keys = ON;")
    # Return rows as dict-like objects for easier JSON conversion
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite database with schemas and indexes."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. PO_HEADER table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PO_HEADER (
        po_number TEXT PRIMARY KEY,
        company_code TEXT,
        vendor_id TEXT,
        vendor_name TEXT,
        po_date TEXT,
        currency TEXT,
        status TEXT
    );
    """)
    
    # 2. PO_ITEM table with composite primary key
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PO_ITEM (
        po_number TEXT,
        item_number TEXT,
        material_id TEXT,
        description TEXT,
        ordered_quantity REAL,
        unit_price REAL,
        po_value REAL,
        PRIMARY KEY (po_number, item_number),
        FOREIGN KEY (po_number) REFERENCES PO_HEADER(po_number) ON DELETE CASCADE
    );
    """)
    
    # 3. GOODS_RECEIPT table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS GOODS_RECEIPT (
        po_number TEXT,
        item_number TEXT,
        gr_number TEXT PRIMARY KEY,
        gr_date TEXT,
        received_quantity REAL,
        gr_value REAL,
        FOREIGN KEY (po_number, item_number) REFERENCES PO_ITEM(po_number, item_number) ON DELETE CASCADE
    );
    """)
    
    # 4. INVOICE_RECEIPT table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS INVOICE_RECEIPT (
        po_number TEXT,
        item_number TEXT,
        invoice_number TEXT PRIMARY KEY,
        invoice_date TEXT,
        invoice_quantity REAL,
        invoice_value REAL,
        FOREIGN KEY (po_number, item_number) REFERENCES PO_ITEM(po_number, item_number) ON DELETE CASCADE
    );
    """)
    
    # Create indexes for optimal join performance on composite columns
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_po_item_po ON PO_ITEM(po_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gr_po_item ON GOODS_RECEIPT(po_number, item_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ir_po_item ON INVOICE_RECEIPT(po_number, item_number);")
    
    conn.commit()
    conn.close()

def clear_database():
    """Drops all records in the database safely."""
    conn = get_connection()
    cursor = conn.cursor()
    # Temporarily disable foreign keys to drop tables cleanly or delete rows in order
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DELETE FROM INVOICE_RECEIPT;")
    cursor.execute("DELETE FROM GOODS_RECEIPT;")
    cursor.execute("DELETE FROM PO_ITEM;")
    cursor.execute("DELETE FROM PO_HEADER;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    conn.close()

def get_database_stats() -> Dict[str, int]:
    """Returns row counts for each database table."""
    stats = {}
    if not os.path.exists(DB_PATH):
        return {"PO_HEADER": 0, "PO_ITEM": 0, "GOODS_RECEIPT": 0, "INVOICE_RECEIPT": 0}
        
    conn = get_connection()
    cursor = conn.cursor()
    tables = ["PO_HEADER", "PO_ITEM", "GOODS_RECEIPT", "INVOICE_RECEIPT"]
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {t}")
            stats[t] = cursor.fetchone()["cnt"]
        except sqlite3.OperationalError:
            stats[t] = 0
    conn.close()
    return stats

def get_schema_metadata() -> Dict[str, List[str]]:
    """Returns a mapping of table names to lists of column names for query validation."""
    metadata = {}
    conn = get_connection()
    cursor = conn.cursor()
    tables = ["PO_HEADER", "PO_ITEM", "GOODS_RECEIPT", "INVOICE_RECEIPT"]
    for t in tables:
        try:
            cursor.execute(f"PRAGMA table_info({t})")
            columns = [row["name"] for row in cursor.fetchall()]
            metadata[t] = columns
        except sqlite3.OperationalError:
            metadata[t] = []
    conn.close()
    return metadata
