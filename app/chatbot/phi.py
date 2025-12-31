# app/chatbot/phi.py

import re
import spacy
from typing import Dict, Any
from uuid import uuid4

# Load spaCy NER model
nlp = spacy.load("en_core_web_sm")

PHI_ENTITY_LABELS = {
    "PERSON", "GPE", "LOC", "ORG",
    "DATE", "TIME", "FAC", "CARDINAL"
}

PHI_REGEX = [
    r"\b\d{2}/\d{2}/\d{4}\b",          # dates
    r"\b\d{10}\b",                     # phone numbers
    r"\b[A-Z0-9]{6,}\b",               # MRN / IDs
    r"\b\S+@\S+\.\S+\b",               # emails
]

class PHIMasker:
    """
    Enterprise-grade PHI masker (NER + regex).
    """

    def __init__(self):
        self.patient_token_map = {}

    def mask_patient(self, patient_id: int) -> str:
        if patient_id not in self.patient_token_map:
            self.patient_token_map[patient_id] = f"PATIENT_{uuid4().hex[:8]}"
        return self.patient_token_map[patient_id]

    def deidentify_text(self, text: str) -> str:
        if not text:
            return text

        # 1️⃣ NER masking
        doc = nlp(text)
        masked = text
        for ent in doc.ents:
            if ent.label_ in PHI_ENTITY_LABELS:
                masked = masked.replace(ent.text, "[REDACTED]")

        # 2️⃣ Regex masking
        for pattern in PHI_REGEX:
            masked = re.sub(pattern, "[REDACTED]", masked)

        return masked

    def deidentify_patient_data(self, data: Any) -> Any:
        """
        Recursively de-identify structured PHI.
        """
        if isinstance(data, dict):
            return {
                key: self.deidentify_patient_data(value)
                for key, value in data.items()
                if key not in {"patient_id", "patient_name"}
            }

        if isinstance(data, list):
            return [self.deidentify_patient_data(item) for item in data]

        if isinstance(data, str):
            return self.deidentify_text(data)

        return data
