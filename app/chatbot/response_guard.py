# app/chatbot/response_guard.py

import re
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Modified: Updated regex to only target potentially identifiable dates
PHI_PATTERNS = [
    # Only redact birthdates or dates with years before 2000 (likely to be identifiable)
    r"\b(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/(19\d{2}|20[0-1][0-9])\b",
    r"\b\d{10}\b",                      # phone numbers
    r"\b\S+@\S+\.\S+\b",                # emails
    r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",     # full names
    r"\b[A-Z0-9]{6,}\b"                 # MRN / IDs
]

# Medical context terms - dynamically detect medical contexts
MEDICAL_CONTEXT_TERMS = [
    # Appointment related
    "appointment", "scheduled", "visit", "consultation", "meeting", "session",
    # Medication related
    "medication", "medicine", "prescription", "drug", "dose", "dosage", "prescribed",
    # Lab related
    "lab", "test", "result", "blood", "sample", "specimen",
    # Time related
    "next", "last", "previous", "upcoming", "recent", "follow-up", "follow up",
    # Medical events
    "recorded", "measured", "administered", "taken", "prescribed", "ordered"
]

def is_medical_context(line: str) -> bool:
    """
    Dynamically determine if a line contains medical context.
    """
    line_lower = line.lower()
    return any(term in line_lower for term in MEDICAL_CONTEXT_TERMS)

def sanitize_response(text: str) -> str:
    """
    Final PHI safety net before response leaves system.
    With dynamic medical date preservation.
    """
    if not text:
        return text
    
    # Skip date redaction for lines with medical context
    lines = text.split('\n')
    result_lines = []
    
    for line in lines:
        if is_medical_context(line):
            # Preserve medical context lines
            logger.debug(f"Preserving medical context line: {line[:50]}...")
            result_lines.append(line)
        else:
            # Apply PHI patterns to other lines
            processed_line = line
            for pattern in PHI_PATTERNS:
                processed_line = re.sub(pattern, "[REDACTED]", processed_line)
            result_lines.append(processed_line)
    
    return '\n'.join(result_lines)
