"""
Strict JSON schema validator for the reasoning layer.
"""
from friday.intent.models import Action

def validate_reasoning_output(data: dict) -> dict:
    """
    Validates the structure and content of the parsed JSON.
    Returns the valid dict, or {"type": "unknown"} if it violates security rules.
    """
    resp_type = data.get("type")
    
    if resp_type == "unknown":
        return data
        
    if resp_type == "response":
        if "text" in data and isinstance(data["text"], str):
            return data
        return {"type": "unknown"}
        
    if resp_type == "clarification":
        if "question" in data and isinstance(data["question"], str):
            return data
        return {"type": "unknown"}
        
    valid_actions = {a.name for a in Action if a != Action.UNKNOWN}
    
    def validate_step(step: dict) -> bool:
        if not isinstance(step, dict):
            return False
        action = step.get("action")
        if action not in valid_actions:
            return False
        if not isinstance(step.get("target", ""), str):
            return False
        args = step.get("arguments", {})
        if not isinstance(args, dict):
            return False
        # Prevent shell/command injection arguments
        for k in args:
            if k in ("command", "code", "shell"):
                return False
        return True
        
    if resp_type == "intent":
        if not validate_step(data):
            return {"type": "unknown"}
            
        conf = data.get("confidence", 0.0)
        if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
            return {"type": "unknown"}
            
        return data
        
    if resp_type == "plan":
        steps = data.get("steps", [])
        if not isinstance(steps, list) or len(steps) > 5 or len(steps) == 0:
            return {"type": "unknown"}
            
        for step in steps:
            if not validate_step(step):
                return {"type": "unknown"}
                
        conf = data.get("confidence", 0.0)
        if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
            return {"type": "unknown"}
            
        return data
        
    return {"type": "unknown"}
