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
            
        # Wearable data filtering
        if any(term in message for term in ["wearable", "watch", "device", "monitor"]):
            filtered["wearable_data"] = data.get("wearable_data", {})
        
        # Specific vital signs from wearable devices
        if any(term in message for term in ["heart", "pulse", "bpm"]):
            filtered["heart_rate"] = data.get("heart_rate", {})
        if any(term in message for term in ["temp", "temperature", "fever"]):
            filtered["temperature"] = data.get("temperature", {})
        if any(term in message for term in ["blood pressure", "bp", "systolic", "diastolic", "hypertension"]):
            filtered["blood_pressure"] = data.get("blood_pressure", {})
        if any(term in message for term in ["oxygen", "o2", "spo2", "saturation"]):
            filtered["oxygen_level"] = data.get("oxygen_level", {})

        # fallback → summary only
        if not filtered:
            filtered["summary"] = "Clinical summary available."

        return filtered
