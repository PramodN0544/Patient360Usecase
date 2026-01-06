# app/chatbot/phi.py

import re
import spacy
from typing import Dict, Any
from uuid import uuid4
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Load spaCy NER model
try:
    nlp = spacy.load("en_core_web_sm")
except Exception as e:
    logger.error(f"Failed to load spaCy model: {e}")
    # Fallback to a simple NER function if spaCy fails
    nlp = None

# Modified: Removed "DATE" from PHI entity labels
PHI_ENTITY_LABELS = {
    "PERSON", "GPE", "LOC", "ORG",
    "TIME", "FAC", "CARDINAL"  # "DATE" removed
}

# Modified: Updated regex to only target potentially identifiable dates
# Only redact birthdates or dates with years before 2000 (likely to be identifiable)
PHI_REGEX = [
    r"\b(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/(19\d{2}|20[0-1][0-9])\b",
    r"\b\d{10}\b",                     # phone numbers
    r"\b[A-Z0-9]{6,}\b",               # MRN / IDs
    r"\b\S+@\S+\.\S+\b",               # emails
]

class PHIMasker:
    """
    Enterprise-grade PHI masker (NER + regex) with medical date preservation.
    """

    def __init__(self):
        self.patient_token_map = {}
        # Dynamically identify medical date fields based on common naming patterns
        self.medical_date_patterns = [
            "_date", "date_", "_time", "time_", "_at", "at_",
            "start_", "end_", "created_", "updated_", "recorded_",
            "effective_", "expiry_", "follow_up_", "scheduled_"
        ]
        
        # Dynamically identify medication fields that should be preserved
        self.medication_patterns = [
            "medication", "medicine", "drug", "prescription", "rx",
            "dosage", "dose", "frequency", "route", "strength",
            "administration", "sig", "direction", "instruction"
        ]

    def mask_patient(self, patient_id: int) -> str:
        if patient_id not in self.patient_token_map:
            self.patient_token_map[patient_id] = f"PATIENT_{uuid4().hex[:8]}"
        return self.patient_token_map[patient_id]

    def deidentify_text(self, text: str) -> str:
        if not text:
            return text

        # 1️⃣ NER masking
        if nlp:
            try:
                doc = nlp(text)
                masked = text
                for ent in doc.ents:
                    if ent.label_ in PHI_ENTITY_LABELS:
                        masked = masked.replace(ent.text, "[REDACTED]")
            except Exception as e:
                logger.error(f"Error in NER masking: {e}")
                masked = text
        else:
            masked = text

        # 2️⃣ Regex masking
        for pattern in PHI_REGEX:
            masked = re.sub(pattern, "[REDACTED]", masked)

        return masked

    def is_medical_date_field(self, key: str) -> bool:
        """
        Dynamically determine if a field is a medical date field based on naming patterns.
        """
        key_lower = key.lower()
        return any(pattern in key_lower for pattern in self.medical_date_patterns)
        
    def is_medication_field(self, key: str) -> bool:
        """
        Dynamically determine if a field is a medication-related field that should be preserved.
        """
        key_lower = key.lower()
        return any(pattern in key_lower for pattern in self.medication_patterns)
        
    def is_medical_field(self, key: str) -> bool:
        """
        Dynamically determine if a field is a medical field that should be preserved.
        This includes both date fields and medication fields.
        """
        return self.is_medical_date_field(key) or self.is_medication_field(key)

    def is_patient_identifier(self, key: str) -> bool:
        """
        Dynamically determine if a field is a patient identifier.
        """
        key_lower = key.lower()
        identifier_patterns = ["id", "name", "ssn", "mrn", "identifier", "email", "phone"]
        return any(pattern in key_lower for pattern in identifier_patterns)

    def deidentify_patient_data(self, data: Any) -> Any:
        """
        Recursively de-identify structured PHI with dynamic medical date preservation.
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # Skip patient identifiers
                if self.is_patient_identifier(key):
                    continue
                
                # Preserve medical dates and medication information
                if self.is_medical_field(key):
                    result[key] = value
                    logger.debug(f"Preserving medical field: {key}")
                else:
                    result[key] = self.deidentify_patient_data(value)
            return result
        
        if isinstance(data, list):
            return [self.deidentify_patient_data(item) for item in data]
        
        if isinstance(data, str):
            return self.deidentify_text(data)
        
        return data
