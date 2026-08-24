from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from gemini_client import generate_structured_output, is_gemini_configured
from ingestion import REQUIRED_PO_FIELDS, OPTIONAL_PO_FIELDS, REQUIRED_RECEIPT_FIELDS

class SchemaMappingResponse(BaseModel):
    mapping: Dict[str, str] = Field(
        description="A dictionary mapping the internal database field names (keys) to the uploaded file column names (values). Do not include keys that cannot be mapped."
    )
    confidence: float = Field(
        description="Overall confidence score of the mapping, from 0.0 (very low/uncertain) to 1.0 (perfect match)"
    )
    explanation: str = Field(
        description="Short summary of why these columns were mapped and any concerns (e.g. missing columns)."
    )

def get_po_field_descriptions() -> str:
    lines = []
    lines.append("Required Fields:")
    for k, v in REQUIRED_PO_FIELDS.items():
        lines.append(f" - {k}: {v} (e.g., PO number, PO ID, EBELN)")
    lines.append("Optional Fields:")
    for k, v in OPTIONAL_PO_FIELDS.items():
        lines.append(f" - {k}: {v} (e.g., LIFNR, VENDOR_ID for vendor; company code, status, price, value, netwr)")
    return "\n".join(lines)

def get_receipt_field_descriptions() -> str:
    lines = []
    lines.append("Required Fields:")
    for k, v in REQUIRED_RECEIPT_FIELDS.items():
        lines.append(f" - {k}: {v} (e.g., PO number, item number, document type 'GR' or 'IR', GR document number, quantity, value/netwr)")
    return "\n".join(lines)

def propose_schema_mapping(columns: List[str], file_type: str) -> SchemaMappingResponse:
    """
    Leverages Gemini to semantically map the uploaded file columns to our internal schema.
    If Gemini is not configured, returns a basic string-matching fallback mapping.
    """
    if file_type == "PO":
        field_info = get_po_field_descriptions()
        target_keys = list(REQUIRED_PO_FIELDS.keys()) + list(OPTIONAL_PO_FIELDS.keys())
    else: # RECEIPT
        field_info = get_receipt_field_descriptions()
        target_keys = list(REQUIRED_RECEIPT_FIELDS.keys())
        
    if not is_gemini_configured():
        # Fallback to string matching when API key is missing
        return propose_fallback_mapping(columns, target_keys)
        
    system_instruction = (
        "You are an expert SAP data engineer. Your task is to map standard and custom "
        "SAP transaction export headers to our normalized internal database schema. "
        "Be careful with synonyms. For example, EBELN is PO number, EBELP is Item number, LIFNR is Vendor ID, "
        "NETWR is Value, MENGE is Quantity, WERKS is Plant. "
        "Return the mapping in a structured JSON schema."
    )
    
    prompt = f"""
    Analyze the uploaded file columns and map them to our internal database fields.
    
    File Columns: {columns}
    
    Target Schema Fields & Descriptions:
    {field_info}
    
    Instructions:
    1. Identify which uploaded column best maps to each internal schema field.
    2. Do NOT map a target field if there is no matching uploaded column.
    3. Return a confidence score between 0.0 and 1.0 (if standard SAP headers match, score is 1.0; if matching is ambiguous, set lower).
    4. Provide a clear explanation of your decisions.
    """
    
    try:
        response = generate_structured_output(
            prompt=prompt,
            response_schema=SchemaMappingResponse,
            system_instruction=system_instruction
        )
        return response
    except Exception as e:
        # Fallback in case of API failure
        return propose_fallback_mapping(columns, target_keys, explanation=f"LLM mapping failed: {str(e)}")

def propose_fallback_mapping(columns: List[str], target_keys: List[str], explanation: str = "Fallback string mapping used.") -> SchemaMappingResponse:
    """Basic string-matching fallback when LLM is unavailable."""
    mapping = {}
    normalized_cols = {c.lower().replace(" ", "").replace("_", "").replace("-", ""): c for c in columns}
    
    # Common SAP abbreviations mapping
    sap_synonyms = {
        "ebeln": ["ponumber", "po", "poid", "purchasingdocument"],
        "ebelp": ["itemnumber", "item", "poitem", "lineitem"],
        "lifnr": ["vendorid", "vendor", "vendorno"],
        "name1": ["vendorname", "name"],
        "aedat": ["podate", "date", "createdon"],
        "bukrs": ["companycode", "company"],
        "waers": ["currency", "curr"],
        "loekz": ["status", "po_status"],
        "matnr": ["materialid", "material", "mat"],
        "txz01": ["description", "materialdescription", "desc"],
        "menge": ["quantity", "orderedquantity", "qty"],
        "netpr": ["unitprice", "price", "rate"],
        "netwr": ["value", "povalue", "amount"]
    }
    
    for key in target_keys:
        # Try exact matching on key name
        norm_key = key.lower().replace("_", "")
        if norm_key in normalized_cols:
            mapping[key] = normalized_cols[norm_key]
            continue
            
        # Try common synonyms
        matched = False
        synonyms = [key.lower()]
        
        # Add standard synonyms
        if key == "po_number":
            synonyms.extend(["po number", "po", "po_num", "po_id", "ebeln", "ponumber"])
        elif key == "item_number":
            synonyms.extend(["item", "po item", "item_num", "item number", "ebelp", "itemnumber"])
        elif key == "vendor_id":
            synonyms.extend(["vendor", "vendor id", "vendor_num", "lifnr", "vendorid"])
        elif key == "vendor_name":
            synonyms.extend(["vendor name", "name", "vendor_name", "vendorname"])
        elif key == "po_date":
            synonyms.extend(["date", "po date", "order date", "aedat", "podate"])
        elif key == "ordered_quantity":
            synonyms.extend(["quantity", "qty", "ordered quantity", "menge", "orderedquantity"])
        elif key == "unit_price":
            synonyms.extend(["unit price", "price", "rate", "netpr", "unitprice"])
        elif key == "po_value":
            synonyms.extend(["value", "po value", "netwr", "amount", "povalue"])
        elif key == "company_code":
            synonyms.extend(["company code", "company", "bukrs", "companycode"])
        elif key == "currency":
            synonyms.extend(["currency", "curr", "waers"])
        elif key == "status":
            synonyms.extend(["status", "po status", "postatus"])
        elif key == "material_id":
            synonyms.extend(["material", "material id", "material_num", "matnr", "materialid"])
        elif key == "description":
            synonyms.extend(["description", "material description", "desc", "txz01"])
        elif key == "type":
            synonyms.extend(["type", "doc type", "document type", "gr/ir type", "doctype"])
        elif key == "document":
            synonyms.extend(["document", "document number", "doc", "doc_num", "gr/ir number", "documentnumber"])
        elif key == "date":
            synonyms.extend(["date", "doc date", "document date", "posting date"])
        elif key == "quantity":
            synonyms.extend(["quantity", "qty", "quantity received", "quantity invoiced"])
        elif key == "value":
            synonyms.extend(["value", "amount", "netwr", "value received", "value invoiced"])
            
        for syn in synonyms:
            clean_syn = syn.replace(" ", "").replace("_", "").replace("-", "")
            if clean_syn in normalized_cols:
                mapping[key] = normalized_cols[clean_syn]
                matched = True
                break
                
        if not matched:
            # Try to see if any column contains the key
            for col in columns:
                if key.lower().replace("_", "") in col.lower().replace(" ", "").replace("_", ""):
                    mapping[key] = col
                    break
                    
    return SchemaMappingResponse(
        mapping=mapping,
        confidence=0.5,
        explanation=explanation
    )
