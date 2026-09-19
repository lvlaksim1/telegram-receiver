#!/usr/bin/env python3
import json
import sys


event = json.load(sys.stdin)
event_id = str(event["event_id"])
update = event.get("update") or {}
message = update.get("message") or {}
text = message.get("text")

if isinstance(text, str) and text:
    action = {
        "schema_version": 1,
        "event_id": event_id,
        "action": "reply",
        "text": "reply: " + text,
    }
else:
    action = {
        "schema_version": 1,
        "event_id": event_id,
        "action": "no_reply",
    }

json.dump(action, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
