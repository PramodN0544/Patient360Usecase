# app/chatbot/minimum_necessary.py

from typing import Dict, Any

class MinimumNecessaryFilter:
    """
    Enforces HIPAA minimum necessary rule.
    """

    @staticmethod
    def extract(message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        message = message.lower()
        filtered = {}

        if "lab" in message:
            filtered["labs"] = data.get("labs", [])
        if "medication" in message:
            filtered["medications"] = data.get("medications", [])
        if "vital" in message:
            filtered["vitals"] = data.get("vitals", [])
        if "appointment" in message:
            filtered["appointments"] = data.get("appointments", [])

        # fallback → summary only
        if not filtered:
            filtered["summary"] = "Clinical summary available."

        return filtered
