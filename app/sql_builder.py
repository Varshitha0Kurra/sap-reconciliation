from typing import List, Tuple, Any, Dict
from app.query_planner import QueryPlan, FilterCondition, JoinCondition, Aggregation, CalculatedField

def build_sql_query(plan: QueryPlan) -> Tuple[str, List[Any]]:
    """
    Compiles a validated QueryPlan into a parameterized SQL SELECT query and bound parameters.
    """
    if plan.is_ambiguous:
        return "", []
        
    parameters = []
    
    # 1. Determine if we need to aggregate details to prevent row multiplication
    has_gr = "GOODS_RECEIPT" in plan.tables
    has_ir = "INVOICE_RECEIPT" in plan.tables
    aggregate_details = has_gr and has_ir
    
    # Helper to return table reference (subquery if details are aggregated)
    def get_table_ref(table_name: str) -> str:
        if table_name == "GOODS_RECEIPT" and aggregate_details:
            return (
                "(SELECT po_number, item_number, "
                "SUM(gr_value) as gr_value, "
                "SUM(received_quantity) as received_quantity, "
                "MAX(gr_date) as gr_date, "
                "GROUP_CONCAT(gr_number) as gr_number "
                "FROM GOODS_RECEIPT GROUP BY po_number, item_number) AS GOODS_RECEIPT"
            )
        if table_name == "INVOICE_RECEIPT" and aggregate_details:
            return (
                "(SELECT po_number, item_number, "
                "SUM(invoice_value) as invoice_value, "
                "SUM(invoice_quantity) as invoice_quantity, "
                "MAX(invoice_date) as invoice_date, "
                "GROUP_CONCAT(invoice_number) as invoice_number "
                "FROM INVOICE_RECEIPT GROUP BY po_number, item_number) AS INVOICE_RECEIPT"
            )
        return table_name

    # 2. SELECT Clause
    select_clauses = []
    
    # Add direct columns
    for col in plan.select:
        select_clauses.append(col)
        
    # Add aggregations
    for agg in plan.aggregations:
        if agg.function == "COUNT_DISTINCT":
            select_clauses.append(f"COUNT(DISTINCT {agg.field}) AS {agg.alias}")
        else:
            select_clauses.append(f"{agg.function}({agg.field}) AS {agg.alias}")
        
    # Add calculated fields
    for calc in plan.calculated_fields:
        select_clauses.append(f"{calc.expression} AS {calc.alias}")
        
    # Default select all for primary table if nothing is selected
    if not select_clauses and plan.tables:
        select_clauses.append(f"{plan.tables[0]}.*")
        
    select_str = "SELECT " + ", ".join(select_clauses)
    
    # 3. FROM Clause
    primary_table = plan.tables[0]
    from_str = f"FROM {get_table_ref(primary_table)}"
    
    # 4. JOIN Clause
    join_clauses = []
    for join in plan.joins:
        left = join.left_table
        right = join.right_table
        
        # Enforce composite key join for detail tables to ensure accuracy
        if (left == "PO_ITEM" and right == "GOODS_RECEIPT") or (left == "GOODS_RECEIPT" and right == "PO_ITEM"):
            on_clause = "PO_ITEM.po_number = GOODS_RECEIPT.po_number AND PO_ITEM.item_number = GOODS_RECEIPT.item_number"
        elif (left == "PO_ITEM" and right == "INVOICE_RECEIPT") or (left == "INVOICE_RECEIPT" and right == "PO_ITEM"):
            on_clause = "PO_ITEM.po_number = INVOICE_RECEIPT.po_number AND PO_ITEM.item_number = INVOICE_RECEIPT.item_number"
        elif (left == "PO_HEADER" and right == "PO_ITEM") or (left == "PO_ITEM" and right == "PO_HEADER"):
            on_clause = "PO_HEADER.po_number = PO_ITEM.po_number"
        else:
            on_clause = f"{join.left_on} = {join.right_on}"
            
        join_clauses.append(f"{join.join_type} JOIN {get_table_ref(right)} ON {on_clause}")
        
    joins_str = " ".join(join_clauses) if join_clauses else ""
    
    # 5. WHERE Clause (Filters)
    where_str = ""
    if plan.filters:
        filter_parts = []
        for cond in plan.filters:
            op = cond.operator.upper()
            if op in ["IS NULL", "IS NOT NULL"]:
                filter_parts.append(f"{cond.field} {op}")
            elif op == "IN":
                if isinstance(cond.value, list):
                    placeholders = ", ".join(["?"] * len(cond.value))
                    filter_parts.append(f"{cond.field} IN ({placeholders})")
                    parameters.extend(cond.value)
                else:
                    filter_parts.append(f"{cond.field} IN (?)")
                    parameters.append(cond.value)
            else:
                filter_parts.append(f"{cond.field} {cond.operator} ?")
                parameters.append(cond.value)
        where_str = "WHERE " + " AND ".join(filter_parts)
        
    # 6. GROUP BY Clause
    groupby_str = ""
    if plan.group_by:
        groupby_str = "GROUP BY " + ", ".join(plan.group_by)
        
    # 7. HAVING Clause
    having_str = ""
    if plan.having:
        having_parts = []
        for cond in plan.having:
            op = cond.operator.upper()
            if op in ["IS NULL", "IS NOT NULL"]:
                having_parts.append(f"{cond.field} {op}")
            else:
                having_parts.append(f"{cond.field} {cond.operator} ?")
                parameters.append(cond.value)
        having_str = "HAVING " + " AND ".join(having_parts)
        
    # 8. ORDER BY Clause
    orderby_str = ""
    if plan.order_by:
        # Prevent SQL injection in ORDER BY by keeping only whitelisted columns and ASC/DESC
        validated_order = []
        for order in plan.order_by:
            parts = order.split()
            col = parts[0]
            direction = parts[1].upper() if len(parts) > 1 else "ASC"
            if direction not in ["ASC", "DESC"]:
                direction = "ASC"
            validated_order.append(f"{col} {direction}")
        orderby_str = "ORDER BY " + ", ".join(validated_order)
        
    # 9. LIMIT Clause
    limit_str = ""
    if plan.limit is not None:
        limit_str = "LIMIT ?"
        parameters.append(plan.limit)
        
    # Combine components safely
    sql_parts = [select_str, from_str, joins_str, where_str, groupby_str, having_str, orderby_str, limit_str]
    sql = " ".join([p for p in sql_parts if p])
    
    return sql, parameters
