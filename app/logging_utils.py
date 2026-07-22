import json
import logging
import sys

logger = logging.getLogger("remediator")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def log_event(event: str, correlation_id: str, **fields):
    logger.info(json.dumps({"event": event, "correlation_id": correlation_id, **fields}, default=str))
