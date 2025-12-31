# app/chatbot/response_guard.py

import re

PHI_PATTERNS = [
    r"\b\d{2}/\d{2}/\d{4}\b",           # dates
    r"\b\d{10}\b",                      # phone numbers
    r"\b\S+@\S+\.\S+\b",                # emails
    r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",     # full names
    r"\b[A-Z0-9]{6,}\b"                 # MRN / IDs
]

def sanitize_response(text: str) -> str:
    """
    Final PHI safety net before response leaves system.
    """
    if not text:
        return text

    for pattern in PHI_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)

    return text
