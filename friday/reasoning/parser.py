"""
JSON parser for the reasoning layer.
"""
import json

def parse_reasoning_output(output: str) -> dict:
    """
    Strips markdown code blocks and attempts to parse JSON.
    Returns parsed dict or {"type": "unknown"} on failure.
    """
    text = output.strip()
    
    # Strip markdown code blocks
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        
        if text.endswith("```"):
            text = text[:-3].strip()
            
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
        
    return {"type": "unknown"}
