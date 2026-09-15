"""
JSON parser for the reasoning layer.
"""
import json

def parse_reasoning_output(output: str) -> dict:
    """
    Strips markdown code blocks and attempts to parse JSON.
    Returns parsed dict or {"type": "unknown"} on failure.
    """
    if not output:
        return {"type": "unknown"}

    text = output.strip()
    
    # Strip markdown code blocks
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        else:
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
        import re
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        
    return {"type": "unknown"}
