# app/chatbot/llm_retriever.py

import os
import json
import logging
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI

# Configure logging
logger = logging.getLogger(__name__)

class LLMDataRetriever:
    """
    LLM-based data retrieval for understanding user queries.
    Uses a smaller LLM to determine which data categories are needed.
    """
    
    def __init__(self):
        # Initialize OpenAI client
        self.client = AsyncOpenAI(api_key=os.getenv("LLM_API_KEY"))
        
        # Cache for performance optimization
        self.cache = {}
        self.cache_size_limit = 100
    
    async def extract_data_needs(self, message: str, available_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use LLM to understand the query and extract relevant data needs.
        
        Args:
            message: The user's message.
            available_data: The available data.
            
        Returns:
            Filtered data based on the query intent.
        """
        # Check cache first
        cache_key = message.lower().strip()
        if cache_key in self.cache:
            logger.info(f"Using cached result for query: {message}")
            cached_categories = self.cache[cache_key]
            return self._filter_data(cached_categories, available_data)
        
        # Dynamically determine available data categories from the data
        data_categories = list(available_data.keys())
        logger.info(f"Available data categories: {data_categories}")
        
        # Use LLM to understand the query
        prompt = f"""
        Analyze the following healthcare query and determine which data categories are needed to answer it.
        
        Query: "{message}"
        
        Available data categories:
        {', '.join(data_categories)}
        
        Return ONLY a JSON array of the required categories, nothing else. For example: ["medications", "labs"]
        """
        
        try:
            logger.info(f"Sending query to LLM for intent classification: {message}")
            
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # Use a smaller, faster model
                messages=[
                    {"role": "system", "content": "You are a healthcare query analyzer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=100
            )
            
            # Parse the response
            response_text = response.choices[0].message.content.strip()
            logger.info(f"LLM response: {response_text}")
            
            try:
                required_categories = json.loads(response_text)
                logger.info(f"Parsed categories: {required_categories}")
                
                # Validate that the response is a list
                if not isinstance(required_categories, list):
                    logger.warning(f"LLM returned non-list response: {required_categories}")
                    required_categories = []
                
                # Update cache
                self._update_cache(cache_key, required_categories)
                
                return self._filter_data(required_categories, available_data)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                return {"summary": "Clinical summary available."}
            
        except Exception as e:
            logger.error(f"Error in LLM data retrieval: {str(e)}")
            # Fallback to a simple summary if LLM fails
            return {"summary": "Clinical summary available."}
    
    def _filter_data(self, categories: List[str], available_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter available data based on required categories.
        
        Args:
            categories: List of required data categories.
            available_data: Available data.
            
        Returns:
            Filtered data.
        """
        filtered_data = {}
        
        for category in categories:
            if category in available_data:
                filtered_data[category] = available_data[category]
                logger.info(f"Including category in response: {category}")
        
        # If no categories matched, return a summary
        if not filtered_data:
            logger.info("No matching categories found, returning summary")
            filtered_data["summary"] = "Clinical summary available."
        
        return filtered_data
    
    def _update_cache(self, key: str, value: Any) -> None:
        """
        Update the cache with a new key-value pair.
        
        Args:
            key: Cache key.
            value: Value to cache.
        """
        # Add to cache
        self.cache[key] = value
        
        # Trim cache if it exceeds the size limit
        if len(self.cache) > self.cache_size_limit:
            # Remove oldest entries (assuming Python 3.7+ where dict insertion order is preserved)
            oldest_keys = list(self.cache.keys())[:-self.cache_size_limit]
            for old_key in oldest_keys:
                del self.cache[old_key]