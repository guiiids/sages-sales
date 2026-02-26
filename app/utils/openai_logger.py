import json
import time
import os
from threading import Lock

_log_lock = Lock()

def log_openai_call(request: dict, response) -> None:
    """
    Append each OpenAI request and response as a JSON object
    (one per line) into logs/openai_calls.jsonl.
    """
    os.makedirs('logs', exist_ok=True)
    
    # Handle modern OpenAI response objects (Pydantic models)
    if hasattr(response, "model_dump"):
        response_data = response.model_dump()
    elif hasattr(response, "to_dict"):
        response_data = response.to_dict()
    else:
        try:
            response_data = dict(response)
        except (TypeError, ValueError):
            response_data = str(response)
            
    record = {
        "timestamp": time.time(),
        "request": request,
        "response": response_data
    }
    path = os.path.join('logs', 'openai_calls.jsonl')
    with _log_lock, open(path, 'a') as f:
        f.write(json.dumps(record) + "\n")
