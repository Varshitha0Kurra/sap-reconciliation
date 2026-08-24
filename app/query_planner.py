from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any

from gemini_client import (
    generate_structured_output,
    is_gemini_configured
)

from database import get_schema_metadata


class FilterCondition(BaseModel):
    field: str = Field(
        description="The table-qualified column name, e.g. 'PO_HEADER.status' or 'PO_ITEM.po_number'"
    )
    operator: str = Field(
        description="The operator: =, !=, <, <=, >, >=, LIKE, IS NULL, IS NOT NULL, IN"
    )
    value: Any = Field(
        default=None,
        description="The comparison value."
    )


class JoinCondition(BaseModel):
    left_table: str
    right_table: str
    left_on: str
    right_on: str
    join_type: str = "INNER"


class Aggregation(BaseModel):
    field: str = Field(
        description="Qualified column name, e.g. 'PO_ITEM.po_value' or '*'"
    )
    function: str = Field(
        description="Aggregation function: SUM, COUNT, AVG, MIN, MAX, COUNT_DISTINCT"
    )
    alias: str = Field(
        description="Result column name, e.g. 'count_value'"
    )


class CalculatedField(BaseModel):
    expression: str = Field(
        description="SQL arithmetic formula using qualified columns"
    )
    alias: str = Field(
        description="Alias for the formula"
    )


class QueryPlan(BaseModel):

    # IMPORTANT:
    # Give tables a default so Gemini/Pydantic does not fail
    # simply because Gemini omitted the field.
    tables: List[str] = Field(
        default_factory=list,
        description=(
            "List of tables involved in the query. "
            "Allowed tables: PO_HEADER, PO_ITEM, "
            "GOODS_RECEIPT, INVOICE_RECEIPT"
        )
    )

    select: List[str] = Field(
        default_factory=list,
        description=(
            "Fields to select directly as table-qualified strings. "
            "Example: PO_HEADER.po_number"
        )
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_gemini_output(cls, values):
        """
        Normalize common Gemini variations before Pydantic validation.

        Gemini sometimes returns:
          - None for optional list fields
          - objects for select/order_by items
          - {"field": "...", "direction": "ASC"} for order_by

        QueryPlan keeps these fields in the simple internal formats used
        by the rest of the application:
          select   -> List[str]
          group_by -> List[str]
          order_by -> List[str], e.g. ["PO_HEADER.vendor_name ASC"]
        """
        if not isinstance(values, dict):
            return values

        # Any list field that Gemini omits or explicitly sets to null
        # should become an empty list rather than failing validation.
        list_defaults = [
            "tables",
            "select",
            "joins",
            "filters",
            "aggregations",
            "calculated_fields",
            "group_by",
            "having",
        ]

        for field_name in list_defaults:
            if values.get(field_name) is None:
                values[field_name] = []

        # SELECT: accept strings or Gemini's {"field": ..., "alias": ...}
        # representation. The QueryPlan stores only the field name here.
        normalized_select = []
        for item in values.get("select", []):
            if isinstance(item, str):
                if item.strip():
                    normalized_select.append(item.strip())
            elif isinstance(item, dict):
                field = item.get("field")
                if isinstance(field, str) and field.strip():
                    normalized_select.append(field.strip())
        values["select"] = normalized_select

        # GROUP BY: accept normal strings or {"field": "..."} objects.
        normalized_group_by = []
        for item in values.get("group_by", []):
            if isinstance(item, str):
                if item.strip():
                    normalized_group_by.append(item.strip())
            elif isinstance(item, dict):
                field = item.get("field")
                if isinstance(field, str) and field.strip():
                    normalized_group_by.append(field.strip())
        values["group_by"] = normalized_group_by

        # ORDER BY: the rest of the application expects strings.
        # Convert Gemini's object form into "field DIRECTION".
        normalized_order_by = []
        for item in values.get("order_by", []):
            if isinstance(item, str):
                if item.strip():
                    normalized_order_by.append(item.strip())
            elif isinstance(item, dict):
                field = item.get("field")
                direction = item.get("direction", "ASC")

                if isinstance(field, str) and field.strip():
                    direction = str(direction).upper().strip()
                    if direction not in {"ASC", "DESC"}:
                        direction = "ASC"
                    normalized_order_by.append(
                        f"{field.strip()} {direction}"
                    )

        values["order_by"] = normalized_order_by

        return values

    joins: List[JoinCondition] = Field(
        default_factory=list,
        description="List of joins needed between tables."
    )

    filters: List[FilterCondition] = Field(
        default_factory=list,
        description="Filter conditions."
    )

    aggregations: List[Aggregation] = Field(
        default_factory=list,
        description="Aggregations to perform."
    )

    calculated_fields: List[CalculatedField] = Field(
        default_factory=list,
        description="Calculated expressions."
    )

    group_by: List[str] = Field(
        default_factory=list,
        description=(
            "Columns to group by as table-qualified strings. "
            "Use [] when no grouping is required."
        )
    )

    having: List[FilterCondition] = Field(
        default_factory=list,
        description="Filter conditions on aggregates."
    )

    order_by: List[str] = Field(
        default_factory=list,
        description=(
            "Ordering expressions as strings, for example "
            "'PO_HEADER.vendor_name ASC'. Use [] when no ordering "
            "is required."
        )
    )

    limit: Optional[int] = Field(
        default=None,
        description="Limit rows returned."
    )

    is_ambiguous: bool = Field(
        default=False,
        description="True if the user question is ambiguous."
    )

    ambiguity_reason: Optional[str] = Field(
        default=None,
        description="Explanation of ambiguity."
    )

    ambiguity_choices: Optional[List[str]] = Field(
        default=None,
        description="Possible clarification choices."
    )


def get_planner_system_instruction() -> str:

    schema_info = get_schema_metadata()

    schema_str = ""

    for table, cols in schema_info.items():
        schema_str += f"Table '{table}': columns: {cols}\n"

    return f"""
You are the Lead Data Analyst for an SAP reconciliation chatbot.

Translate the user's natural-language question into a
structured QueryPlan.

Do NOT write raw SQL.

DATABASE SCHEMA:

{schema_str}

IMPORTANT TABLE RULES:

- PO_HEADER contains purchase order header information.
- PO_ITEM contains purchase order line items.
- GOODS_RECEIPT contains goods receipt records.
- INVOICE_RECEIPT contains invoice records.

JOIN RULES:

PO_HEADER -> PO_ITEM:

PO_HEADER.po_number = PO_ITEM.po_number


PO_ITEM -> GOODS_RECEIPT:

PO_ITEM.po_number = GOODS_RECEIPT.po_number
AND
PO_ITEM.item_number = GOODS_RECEIPT.item_number


PO_ITEM -> INVOICE_RECEIPT:

PO_ITEM.po_number = INVOICE_RECEIPT.po_number
AND
PO_ITEM.item_number = INVOICE_RECEIPT.item_number


COUNT RULES:

When the user asks:

- "how many"
- "how many invoices"
- "count"
- "number of"

generate an aggregate query.

For:

"How many invoices are there?"

you MUST generate:

tables:
["INVOICE_RECEIPT"]

select:
[]

aggregations:
[
    {{
        "field": "*",
        "function": "COUNT",
        "alias": "count_value"
    }}
]

Do NOT return invoice detail columns for a count question.

For:

"How many purchase orders are there?"

use:

tables:
["PO_HEADER"]

select:
[]

aggregations:
[
    {{
        "field": "*",
        "function": "COUNT",
        "alias": "count_value"
    }}
]

For unique counts, use COUNT_DISTINCT.

Example:

"How many POs have goods receipts?"

Use:

tables:
["GOODS_RECEIPT"]

aggregations:
[
    {{
        "field": "GOODS_RECEIPT.po_number",
        "function": "COUNT_DISTINCT",
        "alias": "count_value"
    }}
]


AMBIGUITY:

"Show me the receipts" is ambiguous.

Choices:

- Goods Receipts (GR)
- Invoice Receipts (IR)

"Show values over $1000" is ambiguous.

Choices:

- PO Value
- Goods Receipt Value
- Invoice Value

If ambiguous:

is_ambiguous = true

and provide ambiguity_reason and ambiguity_choices.

If clear:

is_ambiguous = false.

Always provide the appropriate tables for a clear query.
"""


def generate_query_plan(
    question: str,
    conversation_context: str
) -> QueryPlan:

    q_lower = question.lower().strip()

    # -----------------------------------------------------
    # DETERMINISTIC SIMPLE COUNT HANDLING
    # -----------------------------------------------------
    # We do NOT need Gemini to figure out something as
    # simple as "How many invoices are there?"
    #
    # This guarantees the database receives the correct
    # table and COUNT operation.
    # -----------------------------------------------------

    if (
        "how many invoices" in q_lower
        or "number of invoices" in q_lower
        or "count of invoices" in q_lower
        or q_lower == "count invoices"
    ):
        return QueryPlan(
            tables=["INVOICE_RECEIPT"],
            select=[],
            aggregations=[
                Aggregation(
                    field="*",
                    function="COUNT",
                    alias="count_value"
                )
            ]
        )

    if (
        "how many purchase orders" in q_lower
        or "how many pos" in q_lower
        or "number of purchase orders" in q_lower
        or "number of pos" in q_lower
        or "count of purchase orders" in q_lower
    ):
        return QueryPlan(
            tables=["PO_HEADER"],
            select=[],
            aggregations=[
                Aggregation(
                    field="*",
                    function="COUNT",
                    alias="count_value"
                )
            ]
        )

    # -----------------------------------------------------
    # AMBIGUOUS RECEIPTS
    # -----------------------------------------------------

    if (
        "receipts" in q_lower
        and "invoice" not in q_lower
        and "goods" not in q_lower
    ):
        return QueryPlan(
            tables=[],
            is_ambiguous=True,
            ambiguity_reason=(
                "Please clarify whether you mean "
                "Goods Receipts or Invoice Receipts."
            ),
            ambiguity_choices=[
                "Goods Receipts (GR)",
                "Invoice Receipts (IR)"
            ]
        )

    # -----------------------------------------------------
    # GEMINI FOR EVERYTHING ELSE
    # -----------------------------------------------------

    system_instruction = get_planner_system_instruction()

    prompt = f"""
CONVERSATION HISTORY:

{conversation_context}

CURRENT USER QUESTION:

"{question}"

Generate the structured QueryPlan.

Remember:
- Include the required tables.
- Use aggregations for count questions.
- Do not select detail columns for count questions.
- The "select" field must be a list of table-qualified strings.
- Example: ["PO_HEADER.po_number", "PO_HEADER.vendor_name"]
- Do NOT return select items as objects with "field" and "alias".
- "group_by" must ALWAYS be a list of strings. Use [] when there is no grouping.
- Example: ["PO_HEADER.vendor_name"]
- "order_by" must ALWAYS be a list of strings. Use [] when there is no ordering.
- Example: ["PO_HEADER.vendor_name ASC"]
- Do NOT return order_by items as objects such as {{"field": "...", "direction": "ASC"}}.
- Do NOT return null for group_by or order_by; return [] instead.
- Use the "aggregations" field when an aggregate needs an alias.
"""

    if not is_gemini_configured():
        return generate_fallback_query_plan(question)

    result = generate_structured_output(
        prompt=prompt,
        response_schema=QueryPlan,
        system_instruction=system_instruction
    )

    # Defensive normalization in case the Gemini client returns a
    # QueryPlan-like object/dict without passing through Pydantic first.
    if isinstance(result, QueryPlan):
        return result

    if isinstance(result, dict):
        return QueryPlan.model_validate(result)

    return result


def generate_fallback_query_plan(question: str) -> QueryPlan:

    q_lower = question.lower()

    if (
        "how many invoices" in q_lower
        or "number of invoices" in q_lower
        or "count of invoices" in q_lower
        or q_lower == "count invoices"
    ):
        return QueryPlan(
            tables=["INVOICE_RECEIPT"],
            select=[],
            aggregations=[
                Aggregation(
                    field="*",
                    function="COUNT",
                    alias="count_value"
                )
            ]
        )

    if (
        "unmatched receipts over" in q_lower
        or "unmatched receipts" in q_lower
    ):
        return QueryPlan(
            tables=["PO_HEADER", "PO_ITEM"],
            is_ambiguous=True,
            ambiguity_reason=(
                "The term 'unmatched receipts' is ambiguous."
            ),
            ambiguity_choices=[
                "PO Ordered vs. Goods Received (Outstanding Receipts)",
                "Goods Received vs. Invoiced (GRNI)",
                "Invoiced vs. Goods Received (IRND)"
            ]
        )

    if (
        "receipts" in q_lower
        and "invoice" not in q_lower
        and "goods" not in q_lower
    ):
        return QueryPlan(
            tables=[],
            is_ambiguous=True,
            ambiguity_reason=(
                "Please clarify whether you mean "
                "Goods Receipts or Invoice Receipts."
            ),
            ambiguity_choices=[
                "Goods Receipts (GR)",
                "Invoice Receipts (IR)"
            ]
        )

    return QueryPlan(
        tables=["PO_HEADER"],
        select=[
            "PO_HEADER.po_number",
            "PO_HEADER.vendor_name",
            "PO_HEADER.status"
        ],
        limit=100
    )