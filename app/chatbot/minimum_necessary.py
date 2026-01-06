# app/chatbot/minimum_necessary.py

import logging
from typing import Dict, Any, List, Set
import re
from app.chatbot.llm_retriever import LLMDataRetriever

# Configure logging
logger = logging.getLogger(__name__)

class MinimumNecessaryFilter:
    """
    Enforces HIPAA minimum necessary rule with LLM enhancement.
    """
    
    def __init__(self):
        # Initialize LLM retriever
        self.llm_retriever = LLMDataRetriever()
        
        # Keep the original keyword matching as fallback
        self.use_keywords_fallback = True
        
        # Dynamic synonym mappings - these will be expanded during runtime
        self.term_mappings = {}
        self.initialize_term_mappings()
    
    def initialize_term_mappings(self):
        """
        Initialize dynamic term mappings with base synonyms.
        These will be expanded as the system encounters new terms.
        """
        self.term_mappings = {
            "medications": ["medication", "medicine", "drug", "prescription", "med", "meds", 
                           "pill", "pills", "rx"],
            "labs": ["lab", "laboratory", "test", "tests", "blood test", "bloodwork", 
                    "blood work", "result", "results"],
            "vitals": ["vital", "vital sign", "sign", "signs", "reading", "readings", 
                      "measurement", "measurements", "stats", "statistics"],
            "appointments": ["appointment", "visit", "schedule", "scheduled", "meeting", 
                            "consultation", "appt", "appts"],
            "wearable_data": ["wearable", "watch", "device", "monitor", "tracker", "band", 
                             "fitbit", "apple watch", "sensor", "gadget"],
            "heart_rate": ["heart", "pulse", "bpm", "beat", "heartbeat", "heart rate", 
                          "cardiac", "hr", "heart-rate"],
            "temperature": ["temp", "temperature", "fever", "hot", "cold", "celsius", 
                           "fahrenheit", "degree", "degrees", "thermometer"],
            "blood_pressure": ["blood pressure", "bp", "systolic", "diastolic", "hypertension", 
                              "pressure", "mmhg", "mm hg", "blood-pressure"],
            "oxygen_level": ["oxygen", "o2", "spo2", "saturation", "pulse ox", "oximeter", 
                            "oxygen level", "oxygen saturation"]
        }
        
        # Common typos mapping
        self.typo_mappings = {
            "medicne": "medications",
            "medicnes": "medications",
            "medcine": "medications",
            "medcines": "medications",
            "medisin": "medications",
            "apointment": "appointments",
            "apointments": "appointments",
            "appt": "appointments",
            "appts": "appointments",
            "labtests": "labs",
            "labtest": "labs",
            "bloodtest": "labs",
            "hart": "heart_rate",
            "hart rate": "heart_rate",
            "blod pressure": "blood_pressure",
            "oxigen": "oxygen_level"
        }
    
    def learn_new_term(self, term: str, category: str):
        """
        Dynamically learn new terms and their mappings.
        
        Args:
            term: The new term to learn.
            category: The category it belongs to.
        """
        if category in self.term_mappings and term not in self.term_mappings[category]:
            self.term_mappings[category].append(term)
            logger.info(f"Learned new term: '{term}' for category '{category}'")
    
    async def extract(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract relevant data based on the message using LLM understanding.
        Falls back to keyword matching if LLM fails.
        
        Args:
            message: The user's message.
            data: The available data.
            
        Returns:
            Filtered data based on the message.
        """
        try:
            # Primary method: Use LLM to understand the query
            logger.info(f"Using LLM to extract data needs from: {message}")
            filtered_data = await self.llm_retriever.extract_data_needs(message, data)
            
            # If LLM returned meaningful results, use those
            if filtered_data and filtered_data != {"summary": "Clinical summary available."} and not any(
                "error" in value for value in filtered_data.values() if isinstance(value, str)
            ):
                logger.info(f"Using LLM results: {list(filtered_data.keys())}")
                return filtered_data
            
            # Otherwise fall back to keyword matching
            if self.use_keywords_fallback:
                logger.info("Falling back to keyword matching")
                return self._keyword_extract(message, data)
            
            return filtered_data
            
        except Exception as e:
            logger.error(f"Error in LLM extraction, falling back to keywords: {str(e)}")
            return self._keyword_extract(message, data)
    
    def _keyword_extract(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhanced keyword-based extraction as fallback.
        Uses dynamic term mappings and typo detection.
        
        Args:
            message: The user's message.
            data: The available data.
            
        Returns:
            Filtered data based on keyword matching.
        """
        message = message.lower()
        filtered = {}
        
        # Check each data type using expanded term matching
        for data_type, synonyms in self.term_mappings.items():
            if any(term in message for term in synonyms):
                if data_type in data:
                    filtered[data_type] = data[data_type]
        
        # Check for typos
        for typo, data_type in self.typo_mappings.items():
            if typo in message and data_type in data and data_type not in filtered:
                filtered[data_type] = data[data_type]
        
        # Try fuzzy matching for terms not found
        if not filtered:
            filtered.update(self._fuzzy_match(message, data))
        
        # fallback → summary only
        if not filtered:
            filtered["summary"] = "Clinical summary available."
        
        return filtered
    
    def _fuzzy_match(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform fuzzy matching for terms not found by exact matching.
        
        Args:
            message: The user's message.
            data: The available data.
            
        Returns:
            Filtered data based on fuzzy matching.
        """
        filtered = {}
        words = message.split()
        
        # For each word in the message, check if it's similar to any known term
        for word in words:
            if len(word) <= 3:  # Skip very short words
                continue
                
            for data_type, synonyms in self.term_mappings.items():
                # Check if the word is similar to any synonym
                for synonym in synonyms:
                    if self._is_similar(word, synonym) and data_type in data and data_type not in filtered:
                        filtered[data_type] = data[data_type]
                        # Learn this new term for future use
                        self.learn_new_term(word, data_type)
                        break
        
        return filtered
    
    def _is_similar(self, word1: str, word2: str) -> bool:
        """
        Check if two words are similar using a simple similarity metric.
        
        Args:
            word1: First word.
            word2: Second word.
            
        Returns:
            True if the words are similar, False otherwise.
        """
        # If one word is a substring of the other, they're similar
        if word1 in word2 or word2 in word1:
            return True
            
        # If the words are very short, require more similarity
        min_len = min(len(word1), len(word2))
        if min_len <= 3:
            return False
            
        # Calculate Levenshtein distance
        distance = self._levenshtein_distance(word1, word2)
        
        # Words are similar if the distance is less than half the length of the shorter word
        return distance <= min_len / 2
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """
        Calculate the Levenshtein distance between two strings.
        
        Args:
            s1: First string.
            s2: Second string.
            
        Returns:
            The Levenshtein distance.
        """
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
            
        if len(s2) == 0:
            return len(s1)
            
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
            
        return previous_row[-1]
