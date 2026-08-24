import re
from typing import Dict, List, Set, Tuple, Any
from query_planner import QueryPlan, FilterCondition, JoinCondition, Aggregation, CalculatedField
from .database import get_schema_metadata

ALLOWED_TABLES = {"PO_HEADER", "PO_ITEM", "GOODS_RECEIPT", "INVOICE_RECEIPT"}
ALLOWED_OPERATORS = {"=", "!=", "<", "<=", ">", ">=", "LIKE", "IS NULL", "IS NOT NULL", "IN"}
ALLOWED_FUNCTIONS = {"SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"}

# Allowed characters and tokens for calculated fields expressions (e.g. COALESCE, SUM, +, -, *, /, columns, decimals)
CALCULATION_WHITELIST_RE = re.compile(
    r'^(?:[A-Za-z0-9_]+\.[A-Za-z0-9_*]+|COALESCE|SUM|DISTINCT|NULL|LIMIT|ORDER|BY|GROUP|HAVING|AND|OR|NOT|[0-9.\s+\-*/(),]+)+$',
    re.IGNORECASE
)

def validate_field_qualification(field: str, metadata: Dict[str, List[str]], active_tables: Set[str]) -> bool:
    """Verifies that a field is properly qualified (TABLE.column) and matches our whitelist/active schema."""
    if field == "*":
        return True
        
    if "." not in field:
        # Check if the field exists in exactly one active table to qualify it, but reject if ambiguous
        matches = []
        for table in active_tables:
            if table in metadata and field in metadata[table]:
                matches.append(table)
        if len(matches) == 1:
            return True
        return False
        
    parts = field.split(".")
    if len(parts) != 2:
        return False
        
    table, col = parts[0], parts[1]
    
    if table not in ALLOWED_TABLES:
        return False
        
    if table not in active_tables:
        return False
        
    if col == "*":
        return True
        
    if col not in metadata.get(table, []):
        return False
        
    return True

def validate_calculated_expression(expression: str, metadata: Dict[str, List[str]], active_tables: Set[str]) -> bool:
    """
    Validates a math expression to ensure it contains only whitelisted tokens and valid columns.
    Prevents SQL injection inside formulas.
    """
    # 1. Regex validation for characters
    if not CALCULATION_WHITELIST_RE.match(expression):
        return False
        
    # Block any dangerous SQL keywords just in case
    forbidden_keywords = ["select", "insert", "update", "delete", "drop", "alter", "create", "truncate", "union", ";", "--"]
    expr_lower = expression.lower()
    for keyword in forbidden_keywords:
        if re.search(r'\b' + re.escape(keyword) + r'\b', expr_lower) or keyword in expr_lower:
            return False
            
    # 2. Extract column references and validate them
    # Find all pattern like TABLE_NAME.column_name
    columns = re.findall(r'\b([A-Za-z0-9_]+\.[A-Za-z0-9_*]+)\b', expression)
    for col in columns:
        if not validate_field_qualification(col, metadata, active_tables):
            return False
            
    return True

def validate_query_plan(plan: QueryPlan) -> Tuple[bool, List[str]]:
    """
    Validates a structured QueryPlan against database metadata.
    Returns:
        - is_valid: True if valid, False otherwise
        - errors: List of validation error strings
    """
    errors = []
    
    # If the plan is signaled as ambiguous, we don't validate columns/SQL
    if plan.is_ambiguous:
        return True, []
        
    metadata = get_schema_metadata()
    active_tables = set(plan.tables)
    
    # 1. Validate tables
    for table in plan.tables:
        if table not in ALLOWED_TABLES:
            errors.append(f"Table '{table}' is not in the allowed schema whitelist.")
            
    if not plan.tables:
        errors.append("Query plan must specify at least one table.")
        return False, errors
        
    # 2. Validate select columns
    for col in plan.select:
        if not validate_field_qualification(col, metadata, active_tables):
            errors.append(f"Selected column '{col}' is invalid or belongs to a table not in the query.")
            
    # 3. Validate joins
    for join in plan.joins:
        if join.left_table not in ALLOWED_TABLES or join.right_table not in ALLOWED_TABLES:
            errors.append(f"Invalid join tables: {join.left_table} or {join.right_table}")
        if join.left_table not in active_tables or join.right_table not in active_tables:
            errors.append(f"Join tables {join.left_table} and {join.right_table} must be listed in active query tables.")
            
        # Validate join fields
        # Note: Join fields can contain composite joins, but in standard models we validate left_on and right_on
        if not validate_field_qualification(join.left_on, metadata, active_tables):
            errors.append(f"Invalid join key: {join.left_on}")
        if not validate_field_qualification(join.right_on, metadata, active_tables):
            errors.append(f"Invalid join key: {join.right_on}")
            
    # 4. Validate filters
    for cond in plan.filters:
        if not validate_field_qualification(cond.field, metadata, active_tables):
            errors.append(f"Filtered column '{cond.field}' is invalid.")
        if cond.operator not in ALLOWED_OPERATORS:
            errors.append(f"Operator '{cond.operator}' is not whitelisted.")
            
    # 5. Validate aggregations
    for agg in plan.aggregations:
        if not validate_field_qualification(agg.field, metadata, active_tables):
            errors.append(f"Aggregated column '{agg.field}' is invalid.")
        if agg.function not in ALLOWED_FUNCTIONS:
            errors.append(f"Aggregation function '{agg.function}' is not whitelisted.")
            
    # 6. Validate calculated fields
    for calc in plan.calculated_fields:
        if not validate_calculated_expression(calc.expression, metadata, active_tables):
            errors.append(f"Calculated field expression '{calc.expression}' contains invalid columns or forbidden SQL tokens.")
            
    # 7. Validate group_by
    for group in plan.group_by:
        if not validate_field_qualification(group, metadata, active_tables):
            errors.append(f"Group by column '{group}' is invalid.")
            
    # 8. Validate having
    for cond in plan.having:
        # Having can reference aggregated columns (e.g. SUM(gr_value)) or aliases
        # To be safe, we allow checking qualified columns in having
        if not validate_calculated_expression(cond.field, metadata, active_tables):
            errors.append(f"HAVING column/expression '{cond.field}' is invalid.")
        if cond.operator not in ALLOWED_OPERATORS:
            errors.append(f"HAVING operator '{cond.operator}' is not whitelisted.")
            
    # 9. Validate order_by
    for order in plan.order_by:
        # Clean order e.g. "PO_HEADER.po_number DESC" -> "PO_HEADER.po_number"
        clean_order = order.replace(" DESC", "").replace(" ASC", "").strip()
        # Order by can refer to selected aliases or qualified fields
        # If it contains dots, validate as qualified field; otherwise, assume it is an alias
        if "." in clean_order:
            if not validate_field_qualification(clean_order, metadata, active_tables):
                errors.append(f"Order by column '{clean_order}' is invalid.")
                
    return len(errors) == 0, errors
