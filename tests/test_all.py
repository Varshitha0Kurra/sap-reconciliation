import unittest
import pandas as pd
import sqlite3
import os
import sys

# Ensure project root is in the path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import init_db, clear_database, get_database_stats, get_schema_metadata, get_connection
from app.ingestion import validate_po_data, validate_receipt_data, load_pos_to_db, load_receipts_to_db
from app.schema_mapper import propose_fallback_mapping
from app.query_planner import QueryPlan, FilterCondition, JoinCondition, Aggregation, CalculatedField
from app.query_validator import validate_query_plan, validate_calculated_expression
from app.sql_builder import build_sql_query
from app.conversation import ConversationManager
from app.reconciliation import run_reconciliation_flow, generate_grounded_answer

class TestSAPReconciliationChatbot(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Initialize the DB schema once
        init_db()
        
    def setUp(self):
        # Clear the database before each test
        clear_database()
        
    def test_fallback_schema_mapping(self):
        """Tests that fallback mapping successfully identifies synonyms."""
        columns = ["EBELN", "EBELP", "LIFNR", "NAME1", "AEDAT", "MENGE", "NETPR", "NETWR"]
        res = propose_fallback_mapping(columns, ["po_number", "item_number", "vendor_id", "vendor_name", "po_date", "ordered_quantity", "unit_price", "po_value"])
        
        self.assertEqual(res.mapping.get("po_number"), "EBELN")
        self.assertEqual(res.mapping.get("item_number"), "EBELP")
        self.assertEqual(res.mapping.get("vendor_id"), "LIFNR")
        self.assertEqual(res.mapping.get("po_value"), "NETWR")
        self.assertGreaterEqual(res.confidence, 0.5)

    def test_po_ingestion_valid_and_invalid(self):
        """Tests PO validation with clean and error rows."""
        po_data = {
            "PO_NUM": ["450001", "450002", ""], # Row 3 is invalid (missing PO)
            "ITEM_NUM": ["10", "20", "30"],
            "COMPANY": ["1000", "1000", "1000"],
            "LIFNR": ["V001", "V002", "V003"],
            "V_NAME": ["Vendor A", "Vendor B", "Vendor C"],
            "DATE": ["2026-08-01", "2026-08-02", "invalid_date"], # Row 3 has invalid date
            "QTY": [10, 20, 30],
            "PRICE": [15.5, 10.0, 5.0]
        }
        df = pd.DataFrame(po_data)
        mapping = {
            "po_number": "PO_NUM",
            "item_number": "ITEM_NUM",
            "company_code": "COMPANY",
            "vendor_id": "LIFNR",
            "vendor_name": "V_NAME",
            "po_date": "DATE",
            "ordered_quantity": "QTY",
            "unit_price": "PRICE"
        }
        
        valid_rows, invalid_rows = validate_po_data(df, mapping)
        self.assertEqual(len(valid_rows), 2)
        self.assertEqual(len(invalid_rows), 1)
        self.assertEqual(invalid_rows[0]["row_index"], 3)
        self.assertIn("PO Number is required", invalid_rows[0]["errors"])

    def test_receipt_ingestion_valid_and_invalid(self):
        """Tests Receipt validation."""
        rc_data = {
            "PO": ["450001", "450001", "450002"],
            "ITEM": ["10", "10", "20"],
            "DOCTYPE": ["GR", "IR", "invalid_type"],
            "DOCNUM": ["50001", "90001", "50002"],
            "DOCDATE": ["2026-08-03", "2026-08-05", "2026-08-06"],
            "QTY": [10, 10, 5],
            "VAL": [155.0, 155.0, 50.0]
        }
        df = pd.DataFrame(rc_data)
        mapping = {
            "po_number": "PO",
            "item_number": "ITEM",
            "type": "DOCTYPE",
            "document": "DOCNUM",
            "date": "DOCDATE",
            "quantity": "QTY",
            "value": "VAL"
        }
        
        valid_rows, invalid_rows = validate_receipt_data(df, mapping)
        self.assertEqual(len(valid_rows), 2)
        self.assertEqual(len(invalid_rows), 1)
        self.assertIn("Document Type must be GR or IR", invalid_rows[0]["errors"][0])

    def test_query_plan_validator_safety(self):
        """Tests whitelist checking and SQL injection block on QueryPlan."""
        # 1. Invalid Table
        plan_bad_table = QueryPlan(tables=["PO_HEADER", "USERS"], select=["PO_HEADER.po_number"])
        is_valid, errors = validate_query_plan(plan_bad_table)
        self.assertFalse(is_valid)
        self.assertTrue(any("whitelist" in e for e in errors))
        
        # 2. Invalid Operator
        plan_bad_op = QueryPlan(
            tables=["PO_HEADER"],
            select=["PO_HEADER.po_number"],
            filters=[FilterCondition(field="PO_HEADER.status", operator="DELETE", value="OPEN")]
        )
        is_valid, errors = validate_query_plan(plan_bad_op)
        self.assertFalse(is_valid)
        self.assertTrue(any("whitelisted" in e for e in errors))
        
        # 3. SQL Injection in Calculation Field
        plan_injection = QueryPlan(
            tables=["PO_ITEM"],
            select=["PO_ITEM.po_number"],
            calculated_fields=[CalculatedField(expression="PO_ITEM.po_value; DROP TABLE PO_ITEM;--", alias="injected")]
        )
        is_valid, errors = validate_query_plan(plan_injection)
        self.assertFalse(is_valid)
        self.assertTrue(any("forbidden SQL tokens" in e for e in errors))

    def test_sql_builder_compilation(self):
        """Tests SQL statement compilation and parameterization."""
        plan = QueryPlan(
            tables=["PO_HEADER", "PO_ITEM"],
            select=["PO_HEADER.po_number", "PO_ITEM.po_value"],
            joins=[JoinCondition(left_table="PO_HEADER", right_table="PO_ITEM", left_on="PO_HEADER.po_number", right_on="PO_ITEM.po_number")],
            filters=[FilterCondition(field="PO_HEADER.status", operator="=", value="OPEN")]
        )
        sql, params = build_sql_query(plan)
        
        self.assertIn("SELECT PO_HEADER.po_number, PO_ITEM.po_value", sql)
        self.assertIn("FROM PO_HEADER", sql)
        # Check automatic composite join insertion safety
        self.assertIn("ON PO_HEADER.po_number = PO_ITEM.po_number", sql)
        self.assertIn("WHERE PO_HEADER.status = ?", sql)
        self.assertEqual(params, ["OPEN"])

    def test_sql_builder_details_aggregation(self):
        """Tests that joining both GR and IR tables substitutes them with aggregated subqueries."""
        plan = QueryPlan(
            tables=["PO_ITEM", "GOODS_RECEIPT", "INVOICE_RECEIPT"],
            select=["PO_ITEM.po_number", "GOODS_RECEIPT.gr_value", "INVOICE_RECEIPT.invoice_value"],
            joins=[
                JoinCondition(left_table="PO_ITEM", right_table="GOODS_RECEIPT", left_on="PO_ITEM.po_number", right_on="GOODS_RECEIPT.po_number"),
                JoinCondition(left_table="PO_ITEM", right_table="INVOICE_RECEIPT", left_on="PO_ITEM.po_number", right_on="INVOICE_RECEIPT.po_number")
            ]
        )
        sql, params = build_sql_query(plan)
        
        # Verify that subqueries with GROUP BY po_number, item_number are created
        self.assertIn("SELECT po_number, item_number, SUM(gr_value)", sql)
        self.assertIn("SELECT po_number, item_number, SUM(invoice_value)", sql)
        # Ensure joins are constructed correctly
        self.assertIn("PO_ITEM.po_number = GOODS_RECEIPT.po_number AND PO_ITEM.item_number = GOODS_RECEIPT.item_number", sql)
        self.assertIn("PO_ITEM.po_number = INVOICE_RECEIPT.po_number AND PO_ITEM.item_number = INVOICE_RECEIPT.item_number", sql)

    def test_reconciliation_calculations_execution(self):
        """Injects data and tests database calculations for outstanding PO, GRNI, IRND."""
        # 1. Inject PO Data
        po_valid = [
            # PO 1: Fully received and invoiced
            {"po_number": "450001", "item_number": "00010", "company_code": "1000", "vendor_id": "V001", "vendor_name": "Vendor 1", "po_date": "2026-08-01", "currency": "USD", "status": "OPEN", "material_id": "M1", "description": "Desc 1", "ordered_quantity": 10.0, "unit_price": 100.0, "po_value": 1000.0},
            # PO 2: Partially received (Outstanding receipt)
            {"po_number": "450002", "item_number": "00010", "company_code": "1000", "vendor_id": "V002", "vendor_name": "Vendor 2", "po_date": "2026-08-01", "currency": "USD", "status": "OPEN", "material_id": "M2", "description": "Desc 2", "ordered_quantity": 10.0, "unit_price": 100.0, "po_value": 1000.0},
            # PO 3: GRNI (Goods received but not invoiced)
            {"po_number": "450003", "item_number": "00010", "company_code": "1000", "vendor_id": "V003", "vendor_name": "Vendor 3", "po_date": "2026-08-01", "currency": "USD", "status": "OPEN", "material_id": "M3", "description": "Desc 3", "ordered_quantity": 10.0, "unit_price": 100.0, "po_value": 1000.0}
        ]
        load_pos_to_db(po_valid)
        
        # 2. Inject Receipt Data
        receipt_valid = [
            # PO 1: Fully matched ($1000 received, $1000 invoiced)
            {"po_number": "450001", "item_number": "00010", "type": "GR", "document": "GR01", "date": "2026-08-03", "quantity": 10.0, "value": 1000.0},
            {"po_number": "450001", "item_number": "00010", "type": "IR", "document": "IR01", "date": "2026-08-05", "quantity": 10.0, "value": 1000.0},
            
            # PO 2: Partially received ($400 received, outstanding $600)
            {"po_number": "450002", "item_number": "00010", "type": "GR", "document": "GR02", "date": "2026-08-04", "quantity": 4.0, "value": 400.0},
            
            # PO 3: GRNI ($1000 received, $300 invoiced, GRNI = $700)
            {"po_number": "450003", "item_number": "00010", "type": "GR", "document": "GR03", "date": "2026-08-04", "quantity": 10.0, "value": 1000.0},
            {"po_number": "450003", "item_number": "00010", "type": "IR", "document": "IR03", "date": "2026-08-05", "quantity": 3.0, "value": 300.0}
        ]
        gr_cnt, ir_cnt, _ = load_receipts_to_db(receipt_valid)
        self.assertEqual(gr_cnt, 3)
        self.assertEqual(ir_cnt, 2)
        
        # Test 1: Outstanding PO Value (PO value - GR value > 500)
        # Outstanding is $600 for PO 450002. PO 450001 is $0, PO 450003 is $0.
        plan_outstanding = QueryPlan(
            tables=["PO_ITEM", "GOODS_RECEIPT"],
            select=["PO_ITEM.po_number"],
            joins=[JoinCondition(left_table="PO_ITEM", right_table="GOODS_RECEIPT", left_on="PO_ITEM.po_number", right_on="GOODS_RECEIPT.po_number")],
            calculated_fields=[CalculatedField(expression="PO_ITEM.po_value - COALESCE(SUM(GOODS_RECEIPT.gr_value), 0)", alias="outstanding_val")],
            group_by=["PO_ITEM.po_number"],
            having=[FilterCondition(field="outstanding_val", operator=">", value=500.0)]
        )
        sql, params = build_sql_query(plan_outstanding)
        conn = get_connection()
        res_df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        
        self.assertEqual(len(res_df), 1)
        self.assertEqual(res_df.iloc[0]["po_number"], "450002")
        self.assertEqual(res_df.iloc[0]["outstanding_val"], 600.0)
        
        # Test 2: GRNI (GR Value - IR Value > 500)
        # GRNI is $700 for PO 450003. PO 450001 is $0.
        plan_grni = QueryPlan(
            tables=["PO_ITEM", "GOODS_RECEIPT", "INVOICE_RECEIPT"],
            select=["PO_ITEM.po_number"],
            joins=[
                JoinCondition(left_table="PO_ITEM", right_table="GOODS_RECEIPT", left_on="PO_ITEM.po_number", right_on="GOODS_RECEIPT.po_number"),
                JoinCondition(left_table="PO_ITEM", right_table="INVOICE_RECEIPT", left_on="PO_ITEM.po_number", right_on="INVOICE_RECEIPT.po_number")
            ],
            calculated_fields=[CalculatedField(expression="COALESCE(SUM(GOODS_RECEIPT.gr_value), 0) - COALESCE(SUM(INVOICE_RECEIPT.invoice_value), 0)", alias="grni_val")],
            group_by=["PO_ITEM.po_number"],
            having=[FilterCondition(field="grni_val", operator=">", value=500.0)]
        )
        sql_grni, params_grni = build_sql_query(plan_grni)
        conn = get_connection()
        res_grni_df = pd.read_sql_query(sql_grni, conn, params=params_grni)
        conn.close()
        
        self.assertEqual(len(res_grni_df), 1)
        self.assertEqual(res_grni_df.iloc[0]["po_number"], "450003")
        self.assertEqual(res_grni_df.iloc[0]["grni_val"], 700.0)

    def test_grounding_no_records(self):
        """Tests that zero returned rows output a proper non-hallucinated message."""
        df_empty = pd.DataFrame()
        ans = generate_grounded_answer("Which POs have values > $10,000?", df_empty)
        self.assertEqual(ans, "I couldn't find any records matching those conditions in the database.")

    def test_conversation_memory(self):
        """Tests that conversation memory tracks user and assistant queries and contexts."""
        convo = ConversationManager(max_turns=2)
        convo.add_user_message("Show open POs")
        convo.add_assistant_response("I found 5 open POs", sql_executed="SELECT * FROM PO_HEADER WHERE status = 'OPEN'")
        
        context = convo.get_context_for_prompt()
        self.assertIn("User: Show open POs", context)
        self.assertIn("Assistant: I found 5 open POs", context)
        self.assertIn("SELECT * FROM PO_HEADER WHERE status = 'OPEN'", context)
        
        # Test rotation limit (adding more turns clears oldest)
        convo.add_user_message("Query 2")
        convo.add_assistant_response("Response 2")
        convo.add_user_message("Query 3")
        convo.add_assistant_response("Response 3")
        
        new_context = convo.get_context_for_prompt()
        self.assertNotIn("Show open POs", new_context) # Oldest turn rotated out
        self.assertIn("Query 3", new_context)

    def test_sql_builder_count_queries(self):
        """Tests that structured query plans for COUNT and COUNT_DISTINCT compile correctly."""
        # 1. Simple COUNT
        plan_count = QueryPlan(
            tables=["INVOICE_RECEIPT"],
            aggregations=[Aggregation(field="*", function="COUNT", alias="count_value")]
        )
        sql, params = build_sql_query(plan_count)
        self.assertIn("SELECT COUNT(*) AS count_value", sql)
        self.assertIn("FROM INVOICE_RECEIPT", sql)
        
        # 2. COUNT_DISTINCT
        plan_distinct = QueryPlan(
            tables=["GOODS_RECEIPT"],
            aggregations=[Aggregation(field="GOODS_RECEIPT.po_number", function="COUNT_DISTINCT", alias="count_value")]
        )
        sql_dist, params_dist = build_sql_query(plan_distinct)
        self.assertIn("SELECT COUNT(DISTINCT GOODS_RECEIPT.po_number) AS count_value", sql_dist)

    def test_count_reconciliation_execution(self):
        """Injects data and tests counts of invoices, POs, and distinct counts."""
        # Inject PO headers and lines
        po_headers = [
            {"po_number": "450001", "item_number": "00010", "company_code": "1000", "vendor_id": "V001", "vendor_name": "Vendor A", "po_date": "2026-08-01", "currency": "USD", "status": "OPEN", "material_id": "M1", "description": "D1", "ordered_quantity": 1.0, "unit_price": 100.0, "po_value": 100.0},
            {"po_number": "450002", "item_number": "00010", "company_code": "1000", "vendor_id": "V002", "vendor_name": "Vendor B", "po_date": "2026-08-02", "currency": "USD", "status": "OPEN", "material_id": "M2", "description": "D2", "ordered_quantity": 2.0, "unit_price": 50.0, "po_value": 100.0}
        ]
        load_pos_to_db(po_headers)
        
        # Inject receipts
        receipts = [
            {"po_number": "450001", "item_number": "00010", "type": "GR", "document": "GR01", "date": "2026-08-03", "quantity": 1.0, "value": 100.0},
            {"po_number": "450001", "item_number": "00010", "type": "GR", "document": "GR02", "date": "2026-08-04", "quantity": 1.0, "value": 100.0}, # 2 GRs for same PO
            {"po_number": "450001", "item_number": "00010", "type": "IR", "document": "IR01", "date": "2026-08-05", "quantity": 1.0, "value": 100.0},
            {"po_number": "450002", "item_number": "00010", "type": "IR", "document": "IR02", "date": "2026-08-06", "quantity": 2.0, "value": 100.0}
        ]
        load_receipts_to_db(receipts)
        
        # Test 1: Count invoices (should be 2)
        plan_count_ir = QueryPlan(
            tables=["INVOICE_RECEIPT"],
            aggregations=[Aggregation(field="*", function="COUNT", alias="count_value")]
        )
        sql, params = build_sql_query(plan_count_ir)
        conn = get_connection()
        res_df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        self.assertEqual(res_df.iloc[0]["count_value"], 2)
        
        # Test 2: Filtered count: Invoices > $50 (should be 2)
        plan_count_filtered = QueryPlan(
            tables=["INVOICE_RECEIPT"],
            aggregations=[Aggregation(field="*", function="COUNT", alias="count_value")],
            filters=[FilterCondition(field="INVOICE_RECEIPT.invoice_value", operator=">", value=50.0)]
        )
        sql, params = build_sql_query(plan_count_filtered)
        conn = get_connection()
        res_df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        self.assertEqual(res_df.iloc[0]["count_value"], 2)
        
        # Test 3: Count POs with Goods Receipts (should be 1, not 2, because we count distinct POs from GOODS_RECEIPT)
        plan_distinct_pos = QueryPlan(
            tables=["GOODS_RECEIPT"],
            aggregations=[Aggregation(field="GOODS_RECEIPT.po_number", function="COUNT_DISTINCT", alias="count_value")]
        )
        sql, params = build_sql_query(plan_distinct_pos)
        conn = get_connection()
        res_df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        self.assertEqual(res_df.iloc[0]["count_value"], 1)

if __name__ == "__main__":
    unittest.main()
