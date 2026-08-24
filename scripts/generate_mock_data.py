import os
import csv
from datetime import datetime, timedelta

def generate_data():
    os.makedirs("data", exist_ok=True)
    
    # 1. Generate Purchase Order Export
    # Columns: PO Number, Item, Company Code, Vendor ID, Vendor Name, Date, Material, Description, Quantity, Unit Price, Value, Status
    po_rows = [
        # PO 45000100: Fully matched
        ["45000100", "10", "1000", "V001", "Acme Corp", "2026-08-01", "MAT001", "Steel Pipe", 100, 10.0, 1000.0, "CLOSED"],
        # PO 45000110: Partially received, unmatched receipts > $1000 (PO value - GR value > 1000)
        ["45000110", "10", "1000", "V002", "Tech Solutions", "2026-08-02", "MAT002", "Circuit Board", 50, 100.0, 5000.0, "OPEN"],
        # PO 45000120: Goods Received but Not Invoiced (GRNI > 1000) (GR value - IR value > 1000)
        ["45000120", "10", "1000", "V003", "Global Logistics", "2026-08-05", "MAT003", "Shipping Containers", 5, 2000.0, 10000.0, "OPEN"],
        # PO 45000130: Invoiced but Not Received (IRND > 1000) (IR value - GR value > 1000)
        ["45000130", "10", "1000", "V004", "Office Supplies Ltd", "2026-08-08", "MAT004", "Office Desks", 10, 300.0, 3000.0, "OPEN"],
        # PO 45000131: Vendor V006, Unmatched receipt (Outstanding PO value = $12000 - $9400 = $2600 > 1000)
        ["45000131", "10", "1000", "V006", "Vendor V006", "2026-08-10", "MAT005", "Industrial Pump", 1, 12000.0, 12000.0, "OPEN"],
        ["45000131", "20", "1000", "V006", "Vendor V006", "2026-08-10", "MAT006", "Valves", 10, 150.0, 1500.0, "OPEN"],
        # PO 45000140: No Goods Receipts at all
        ["45000140", "10", "1000", "V005", "Apex Construction", "2026-08-12", "MAT007", "Cement Bags", 500, 8.0, 4000.0, "OPEN"],
        # PO 45000150: Multiple items, some closed, some open. Vendor V006
        ["45000150", "10", "1000", "V006", "Vendor V006", "2026-08-15", "MAT001", "Steel Pipe", 20, 10.0, 200.0, "CLOSED"],
        ["45000150", "20", "1000", "V006", "Vendor V006", "2026-08-15", "MAT008", "Hydraulic Fluid", 50, 40.0, 2000.0, "OPEN"],
        # PO 45000160: Invoice greater than PO value (Invoice = $6000, PO = $5000)
        ["45000160", "10", "1000", "V007", "Alpha Services", "2026-08-18", "MAT009", "Consulting Hours", 50, 100.0, 5000.0, "OPEN"],
        # PO 45000170: High value PO for V006 to test high value queries
        ["45000170", "10", "1000", "V006", "Vendor V006", "2026-08-20", "MAT010", "Generator set", 1, 25000.0, 25000.0, "OPEN"]
    ]
    
    with open("data/mock_po_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["PO Number", "Item", "Company Code", "Vendor ID", "Vendor Name", "Date", "Material", "Description", "Quantity", "Unit Price", "Value", "Status"])
        writer.writerows(po_rows)
        
    # 2. Generate Receipt / Invoice Export
    # Columns: PO Number, Item, Type, Document, Date, Quantity, Value
    receipt_rows = [
        # PO 45000100: Item 10 - Fully received and fully invoiced
        ["45000100", "10", "GR", "50000001", "2026-08-03", 100, 1000.0],
        ["45000100", "10", "IR", "90000001", "2026-08-05", 100, 1000.0],
        
        # PO 45000110: Item 10 - Partially received, GR value = $3000 (PO = $5000). Outstanding receipt = $2000
        ["45000110", "10", "GR", "50000002", "2026-08-04", 30, 3000.0],
        ["45000110", "10", "IR", "90000002", "2026-08-06", 30, 3000.0],
        
        # PO 45000120: Item 10 - Goods received ($8000) but not invoiced (IR = $6000). GRNI = $2000
        ["45000120", "10", "GR", "50000003", "2026-08-07", 4, 8000.0],
        ["45000120", "10", "IR", "90000003", "2026-08-09", 3, 6000.0],
        
        # PO 45000130: Item 10 - Invoiced ($3000) but not received (GR = $1000). IRND = $2000
        ["45000130", "10", "GR", "50000004", "2026-08-10", 3, 900.0], # received 3 units, value $900
        ["45000130", "10", "IR", "90000004", "2026-08-11", 10, 3000.0], # invoiced all 10 units, value $3000
        
        # PO 45000131: Item 10 - Vendor V006, Unmatched receipt (Outstanding PO = $12000 - $9400 = $2600 > 1000)
        # Multiple receipts: GR1 = $5000, GR2 = $4400. Total GR = $9400
        ["45000131", "10", "GR", "50000005", "2026-08-12", 0.4, 4800.0],
        ["45000131", "10", "GR", "50000006", "2026-08-14", 0.38, 4600.0],
        ["45000131", "10", "IR", "90000005", "2026-08-15", 0.78, 9360.0], # Invoiced matching what was received
        # PO 45000131: Item 20 - Fully received ($1500)
        ["45000131", "20", "GR", "50000007", "2026-08-12", 10, 1500.0],
        ["45000131", "20", "IR", "90000006", "2026-08-15", 10, 1500.0],
        
        # PO 45000140: No receipts (no rows)
        
        # PO 45000150: Item 10 - Fully received and invoiced
        ["45000150", "10", "GR", "50000008", "2026-08-17", 20, 200.0],
        ["45000150", "10", "IR", "90000007", "2026-08-19", 20, 200.0],
        # PO 45000150: Item 20 - Outstanding GR of $2000 (no receipts yet)
        
        # PO 45000160: Item 10 - Invoiced greater than PO (Invoice = $6000, PO = $5000)
        ["45000160", "10", "GR", "50000009", "2026-08-20", 50, 5000.0],
        ["45000160", "10", "IR", "90000008", "2026-08-22", 50, 6000.0], # price variance invoice
        
        # PO 45000170: Item 10 - No receipts yet
    ]
    
    with open("data/mock_receipt_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["PO Number", "Item", "Type", "Document", "Date", "Quantity", "Value"])
        writer.writerows(receipt_rows)

    print("Mock data generated successfully in data/ directory.")

if __name__ == "__main__":
    generate_data()
