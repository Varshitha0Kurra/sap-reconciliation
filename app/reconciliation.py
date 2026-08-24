import sqlite3
import pandas as pd
import logging
from typing import Dict, Any, List, Tuple, Optional
from app.database import get_connection
from app.query_planner import generate_query_plan, QueryPlan
from app.query_validator import validate_query_plan
from app.sql_builder import build_sql_query
from app.gemini_client import generate_text_response, is_gemini_configured

logger = logging.getLogger(__name__)

def execute_reconciliation_query(sql: str, params: List[Any]) -> pd.DataFrame:
    """Executes a SQL SELECT query against the SQLite database and returns a Pandas DataFrame."""
    conn = get_connection(read_only=True)
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df
    except Exception as e:
        logger.error(f"SQL execution failed: {str(e)} \nSQL: {sql} \nParams: {params}")
        raise RuntimeError(f"Database query error: {str(e)}")
    finally:
        conn.close()

def generate_grounded_answer(question: str, df: pd.DataFrame) -> str:
    """
    Uses Gemini to generate a response that is strictly grounded in the database query result.
    Does not invent or extrapolate numbers.
    """
    if df.empty:
        return "I couldn't find any records matching those conditions in the database."
        
    if not is_gemini_configured():
        # Fallback text summary if API is not configured
        return f"Database query returned {len(df)} matching rows. (Gemini offline)"
        
    system_instruction = (
        "You are an SAP data reconciliation chatbot. Your task is to write a concise, professional, "
        "and direct answer to the user's question based ONLY on the provided SQLite query results.\n"
        "Rules:\n"
        "1. Ground all numbers, dates, vendor names, and PO details strictly in the result set.\n"
        "2. Do NOT fabricate, guess, or extrapolate any values.\n"
        "3. If a value cannot be calculated from the result set, state that it is not available.\n"
        "4. Format currency values as $XX,XXX.XX and quantities clearly.\n"
        "5. Keep the explanation professional and concise. Do NOT describe the SQL or the tables in your answer."
    )
    
    # Format the first 50 rows of data as a markdown table for context
    data_md = df.head(50).to_markdown(index=False)
    
    prompt = f"""
    USER QUESTION:
    "{question}"
    
    SQL QUERY RESULTS (Total rows: {len(df)}):
    {data_md}
    
    Write the grounded answer:
    """
    
    try:
        return generate_text_response(prompt, system_instruction)
    except Exception as e:
        logger.error(f"Grounded response generation failed: {str(e)}")
        return f"Database query returned {len(df)} rows. (Error generating summary: {str(e)})"

def run_reconciliation_flow(
    question: str, 
    conversation_context: str
) -> Dict[str, Any]:
    """
    Runs the entire pipeline from question to grounded response or ambiguity clarification.
    """
    try:
        # 1. Generate Structured Query Plan
        plan = generate_query_plan(question, conversation_context)
        
        # 2. Check for Ambiguity
        if plan.is_ambiguous:
            return {
                "status": "ambiguous",
                "ambiguity_reason": plan.ambiguity_reason,
                "ambiguity_choices": plan.ambiguity_choices,
                "plan": plan
            }
            
        # 3. Validate Query Plan
        is_valid, errors = validate_query_plan(plan)
        if not is_valid:
            return {
                "status": "error",
                "error_message": f"Query Plan Validation Failed:\n" + "\n".join(errors),
                "plan": plan
            }
            
        # 4. Build SQL Query
        sql, params = build_sql_query(plan)
        if not sql:
            return {
                "status": "error",
                "error_message": "Failed to compile SQL from query plan.",
                "plan": plan
            }
            
        # 5. Execute SQLite Query
        df = execute_reconciliation_query(sql, params)
        
        # 6. Generate Grounded Answer
        answer = generate_grounded_answer(question, df)
        
        # Format stats for conversational memory
        results_summary = f"{len(df)} rows returned"
        if not df.empty and len(df.columns) > 0:
            sample_val = df.iloc[0].to_dict()
            results_summary += f", sample row: {sample_val}"
            
        # Return evidence packet
        return {
            "status": "success",
            "answer": answer,
            "sql": sql,
            "params": params,
            "data": df,
            "plan": plan,
            "results_summary": results_summary
        }
        
    except Exception as e:
        logger.exception("Error in reconciliation flow")
        return {
            "status": "error",
            "error_message": str(e)
        }
