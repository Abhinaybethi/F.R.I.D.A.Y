import sys
import os
import time
import json
import statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.planning.context_resolver import ShortTermContext
from friday.reasoning.local_reasoner import OllamaReasoner
from friday.reasoning.validator import validate_reasoning_output
from friday.reasoning.parser import parse_reasoning_output

def main():
    reasoner = OllamaReasoner(model="llama3:latest")
    
    if not reasoner.is_available():
        print("REAL MODEL TEST BLOCKED — LOCAL REASONER UNAVAILABLE")
        return

    print("============================================================")
    print("REAL MODEL TEST STARTED")
    print(f"Model: {reasoner.model}")
    print("============================================================")
    
    test_cases = [
        {
            "transcript": "Could you open Chrome?",
            "context": ShortTermContext(),
            "expected_type": "intent",
            "expected_action": "OPEN_APP",
            "expected_target": "chrome"
        },
        {
            "transcript": "Please open YouTube.",
            "context": ShortTermContext(),
            "expected_type": "intent",
            "expected_action": "OPEN_WEBSITE",
            "expected_target": "youtube"
        },
        {
            "transcript": "I want to search for Python tutorials.",
            "context": ShortTermContext(),
            "expected_type": "intent",
            "expected_action": "SEARCH_WEB",
            "expected_target": "python tutorials"
        },
        {
            "transcript": "Find my resume.",
            "context": ShortTermContext(),
            "expected_type": "intent",
            "expected_action": "FIND_FILE",
            "expected_target": "resume"
        },
        {
            "transcript": "Can you tell me what time it is?",
            "context": ShortTermContext(),
            "expected_type": "intent",
            "expected_action": "GET_TIME",
            "expected_target": ""
        },
        {
            "transcript": "Open Chrome and search for Python tutorials.",
            "context": ShortTermContext(),
            "expected_type": "plan",
            "expected_action": None,
            "expected_target": None
        },
        {
            "transcript": "Actually search for Java instead.",
            "context": ShortTermContext(last_search_query="python tutorials", last_transcript="I want to search for Python tutorials."),
            "expected_type": "intent",
            "expected_action": "SEARCH_WEB",
            "expected_target": "java"
        },
        {
            "transcript": "Open the first result.",
            "context": ShortTermContext(last_tool_result={"results": []}), # No valid structured result
            "expected_type": "clarification_or_unknown",
            "expected_action": None,
            "expected_target": None
        }
    ]
    
    NUM_RUNS = 10
    results_table = []
    
    for case in test_cases:
        transcript = case["transcript"]
        context = case["context"]
        print(f"\nTesting: '{transcript}'")
        
        valid_json_count = 0
        correct_count = 0
        latencies = []
        
        for _ in range(NUM_RUNS):
            start = time.time()
            res = reasoner.request(transcript, context)
            latency = time.time() - start
            latencies.append(latency)
            
            # Since request() already parses and validates, if it returns {"type": "unknown"} it could mean invalid JSON or invalid schema
            # Let's bypass request() just to measure raw JSON validity
            raw_response = reasoner._raw_request_for_test(transcript, context) if hasattr(reasoner, "_raw_request_for_test") else None
            
            if res.get("type") != "unknown" or (case["expected_type"] == "clarification_or_unknown"):
                valid_json_count += 1
                
            is_correct = False
            r_type = res.get("type")
            
            if case["expected_type"] == "intent":
                if r_type == "intent" and res.get("action") == case["expected_action"] and case["expected_target"].lower() in res.get("target", "").lower():
                    is_correct = True
            elif case["expected_type"] == "plan":
                if r_type == "plan" and len(res.get("steps", [])) <= 5 and len(res.get("steps", [])) > 0:
                    is_correct = True
            elif case["expected_type"] == "clarification_or_unknown":
                if r_type in ("clarification", "unknown"):
                    is_correct = True
                    
            if is_correct:
                correct_count += 1
                
        avg_latency = statistics.mean(latencies)
        results_table.append({
            "Request": transcript,
            "Runs": NUM_RUNS,
            "Valid JSON": valid_json_count,
            "Correct": correct_count,
            "Avg latency": f"{avg_latency:.2f}s"
        })
        print(f"  Valid JSON: {valid_json_count}/{NUM_RUNS}, Correct: {correct_count}/{NUM_RUNS}, Avg Latency: {avg_latency:.2f}s")
        
    print("\n| Request | Runs | Valid JSON | Correct | Avg latency |")
    print("|---------|------|------------|---------|-------------|")
    for r in results_table:
        print(f"| {r['Request']} | {r['Runs']} | {r['Valid JSON']} | {r['Correct']} | {r['Avg latency']} |")

if __name__ == "__main__":
    main()
