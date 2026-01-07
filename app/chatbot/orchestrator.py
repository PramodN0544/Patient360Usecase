"""
Chat Orchestrator for the Patient360 Chatbot.

This module orchestrates the chatbot's interactions, including:
- Query classification
- Data retrieval
- Context building
- LLM interaction
- Response validation
- PHI protection (masking, minimum necessary, response sanitization)
"""

import os
import json
import logging
import re
import dateparser
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, date
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from openai import OpenAI, AsyncOpenAI

from app.models import User
from app.chatbot.rbac import DataScope
from app.chatbot.rag import RAGPipeline
from app.chatbot.phi import PHIMasker
from app.chatbot.minimum_necessary import MinimumNecessaryFilter
from app.chatbot.response_guard import sanitize_response
from app.chatbot.audit import log_chat_interaction
from app.chatbot.consent import has_patient_consent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("LLM_API_KEY"))


class Message(BaseModel):
    """A chat message."""
    role: str  # 'user' or 'assistant'
    content: str


class ChatResponse(BaseModel):
    """A response from the chatbot."""
    response: str
    query_type: str
    data_accessed: Optional[List[str]] = None


class ChatOrchestrator:
    """
    Orchestrates the chatbot's interactions.
    
    This class is responsible for:
    - Classifying user queries
    - Retrieving relevant data
    - Building context for the LLM
    - Interacting with the LLM
    - Validating responses
    - PHI protection and compliance
    """
    
    def __init__(self, rag_pipeline: RAGPipeline):
        """
        Initialize the chat orchestrator.
        
        Args:
            rag_pipeline: The RAG pipeline to use for retrieving information.
        """
        self.rag_pipeline = rag_pipeline
        self.phi_masker = PHIMasker()  # Initialize PHI masker
    
    async def process_chat_request(
        self,
        user: User,
        message: str,
        previous_messages: List[Message],
        data_scope: DataScope,
        db: AsyncSession = None
    ) -> ChatResponse:
        """
        Process a chat request.
        
        Args:
            user: The user making the request.
            message: The user's message.
            previous_messages: Previous messages in the conversation.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            The chatbot's response.
        """
        # Classify query
        query_type = await self._classify_query(message)
        logger.info(f"Query type: {query_type}")
        
        # Retrieve relevant data
        data, data_accessed = await self._retrieve_data(
            user=user,
            message=message,
            query_type=query_type,
            data_scope=data_scope,
            db=db
        )
        
        # Build context with PHI protection
        context = await self._build_context(
            user=user,
            message=message,
            previous_messages=previous_messages,
            query_type=query_type,
            data=data,
            data_scope=data_scope
        )
        
        # Log the context being sent to the LLM
        logger.info(f"Query type: {query_type}")
        logger.info(f"System prompt: {context[0]['content']}")
        if len(context) > 1 and context[1]['role'] == 'system':
            logger.info(f"Data context: {context[1]['content']}")
        
        # Generate response
        response = await self._generate_response(context)
        
        # CRITICAL: Sanitize response to prevent PHI leakage
        response = sanitize_response(response)
        
        # Validate response
        validated_response = self._validate_response(
            response=response,
            data_scope=data_scope
        )
        
        # Ensure data_accessed is always a list before logging
        if not isinstance(data_accessed, list):
            if data_accessed is None:
                data_accessed_for_log = []
            else:
                data_accessed_for_log = [str(data_accessed)]
        else:
            data_accessed_for_log = data_accessed
            
        # CRITICAL: Audit log the interaction for HIPAA compliance
        await log_chat_interaction(
            user_id=user.id,
            message=message,
            response=validated_response,
            query_type=query_type,
            data_accessed=data_accessed_for_log,
            context=context,
            db=db
        )
        # Ensure data_accessed is always a list before creating ChatResponse
        if not isinstance(data_accessed, list):
            if data_accessed is None:
                data_accessed_list = []
            else:
                data_accessed_list = [str(data_accessed)]
        else:
            data_accessed_list = data_accessed
            
        return ChatResponse(
            response=validated_response,
            query_type=query_type,
            data_accessed=data_accessed_list
        )
    
    async def _classify_query(self, message: str) -> str:
        """
        Classify the user's query.
        
        Args:
            message: The user's message.
            
        Returns:
            The query type: Can be a single type ('data', 'explanation', 'analytics')
            or a hybrid type (e.g., 'data+explanation').
        """
        # Use OpenAI to classify the query
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """
                    You are a query classifier for a healthcare chatbot. Analyze the query and determine which categories it falls into.
                    
                    Categories:
                    - data: Requests for specific patient data (labs, medications, vitals, etc.)
                    - explanation: Requests for explanations of medical terms or concepts
                    - analytics: Requests for aggregated statistics or trends
                    - recommendation: Requests for medical advice or recommendations
                    - action: Requests to perform an action (schedule appointment, refill medication, etc.)
                    
                    A query can belong to multiple categories. If it does, join the categories with a plus sign (+).
                    
                    Examples:
                    - "What was my heart rate yesterday?" → "data"
                    - "What does elevated troponin mean?" → "explanation"
                    - "How many patients were admitted last month?" → "analytics"
                    - "What was my blood pressure and what does it mean?" → "data+explanation"
                    - "Should I be concerned about my cholesterol levels?" → "data+explanation+recommendation"
                    
                    Respond with ONLY the category name or combined categories, nothing else.
                    """
                },
                {"role": "user", "content": message}
            ],
            temperature=0.1,
            max_tokens=30
        )
        
        # Extract the query type from the response
        query_type = response.choices[0].message.content.strip().lower()
        
        # Validate query type
        primary_types = ["data", "explanation", "analytics", "recommendation", "action"]
        
        # Check if it's a hybrid type (contains +)
        if "+" in query_type:
            # Split by + and validate each part
            parts = [part.strip() for part in query_type.split("+")]
            valid_parts = [part for part in parts if part in primary_types]
            
            if valid_parts:
                # Reconstruct the hybrid type with valid parts
                query_type = "+".join(valid_parts)
            else:
                query_type = "explanation"  # Default to explanation if no valid parts
        elif query_type not in primary_types:
            query_type = "explanation"  # Default to explanation for invalid single types
        
        logger.info(f"Classified query as: {query_type}")
        return query_type
    
    async def _retrieve_data(
        self,
        user: User,
        message: str,
        query_type: str,
        data_scope: DataScope,
        db: AsyncSession = None
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Retrieve relevant data based on the query type and data scope.
        Now uses LLM-enhanced data retrieval.
        
        Args:
            user: The user making the request.
            message: The user's message.
            query_type: The type of query (can be a hybrid type like 'data+explanation').
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            A tuple of (data, data_accessed).
        """
        data = {}
        data_accessed = []  # Initialize as an empty list
        
        if db is None:
            logger.warning("No database session provided, cannot retrieve real data")
            return data, data_accessed
        
        # Split query_type into components if it's a hybrid type
        query_types = query_type.split("+")
        logger.info(f"Processing query types: {query_types}")
        
        # Import the enhanced minimum necessary filter
        from app.chatbot.minimum_necessary import MinimumNecessaryFilter
        min_necessary_filter = MinimumNecessaryFilter()
        
        # Process each query type component
        if "data" in query_types:
            # For data queries, retrieve specific patient data
            if user.role == "patient":
                # Patient can only access their own data
                patient_data = await self._get_patient_data(
                    patient_id=data_scope.patient_ids[0] if data_scope.patient_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                
                # Get all available data first
                all_patient_data = patient_data.get("data", {})
                
                # Apply the LLM-enhanced filter
                filtered_data = await min_necessary_filter.extract(message, all_patient_data)
                
                # Update the patient_data with filtered data
                patient_data["data"] = filtered_data
                
                data["patient_data"] = patient_data
                data_accessed.append("patient_data")
            
            elif user.role == "doctor":
                # Doctor can access data for patients they have treated
                # First, extract patient name or ID from the message
                patient_id = await self._extract_patient_id(message, data_scope.patient_ids, db)
                
                if patient_id and patient_id in data_scope.patient_ids:
                    patient_data = await self._get_patient_data(
                        patient_id=patient_id,
                        message=message,
                        data_scope=data_scope,
                        db=db
                    )
                    
                    # Get all available data first
                    all_patient_data = patient_data.get("data", {})
                    
                    # Apply the LLM-enhanced filter
                    filtered_data = await min_necessary_filter.extract(message, all_patient_data)
                    
                    # Update the patient_data with filtered data
                    patient_data["data"] = filtered_data
                    
                    data["patient_data"] = patient_data
                    data_accessed.append(f"patient_data:{patient_id}")
            
            elif user.role == "hospital":
                # Hospital admin can access aggregated data
                hospital_data = await self._get_hospital_data(
                    hospital_id=data_scope.hospital_ids[0] if data_scope.hospital_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                
                # Apply the LLM-enhanced filter to hospital data
                filtered_hospital_data = await min_necessary_filter.extract(message, hospital_data)
                
                data["hospital_data"] = filtered_hospital_data
                data_accessed.append("hospital_data")
        
        if "explanation" in query_types:
            # For explanation queries, use RAG to retrieve relevant information
            rag_results = await self.rag_pipeline.query(message)
            data["rag_results"] = rag_results
            data_accessed.append("medical_knowledge")
        
        if "analytics" in query_types:
            # For analytics queries, retrieve aggregated data
            if user.role == "hospital" and data_scope.can_access_analytics:
                analytics_data = await self._get_analytics(
                    hospital_id=data_scope.hospital_ids[0] if data_scope.hospital_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                
                # Apply the LLM-enhanced filter to analytics data
                filtered_analytics = await min_necessary_filter.extract(message, analytics_data)
                
                data["analytics"] = filtered_analytics
                data_accessed.append("analytics")
        
        if "recommendation" in query_types:
            # For recommendation queries, we'll include both patient data and medical knowledge
            # This ensures the LLM has context for making recommendations
            if "rag_results" not in data:
                rag_results = await self.rag_pipeline.query(message)
                data["rag_results"] = rag_results
                data_accessed.append("medical_knowledge")
            
            # Add recommendation context
            data["recommendation_context"] = {
                "query": message,
                "recommendation_requested": True
            }
            data_accessed.append("recommendation_context")
        
        if "action" in query_types:
            # For action queries, we'll include action context
            data["action_context"] = {
                "query": message,
                "action_requested": True,
                "available_actions": ["schedule_appointment", "medication_refill", "message_provider"]
            }
            data_accessed.append("action_context")
        
        logger.info(f"Retrieved data for query types {query_types}: {list(data.keys())}")
        
        # Ensure data_accessed is always a list before returning
        if not isinstance(data_accessed, list):
            if data_accessed is None:
                data_accessed = []
            else:
                data_accessed = [str(data_accessed)]
                
        return data, data_accessed
    
    async def _get_wearable_data(
        self,
        patient_id: Optional[int],
        message: str,
        data_scope: DataScope,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get wearable data for a patient based on the message and data scope.
        
        Args:
            patient_id: The patient ID.
            message: The user's message.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            Wearable data.
        """
        from app.wearable_service import wearable_service
        import logging
        
        logger = logging.getLogger(__name__)
        
        if not patient_id:
            return {"error": "No patient ID provided"}
            
        # Check if wearable data is allowed in the data scope
        wearable_types = {"wearable_data", "heart_rate", "temperature", "blood_pressure", "oxygen_level"}
        if not any(wt in data_scope.allowed_data_types for wt in wearable_types):
            return {"error": "Access to wearable data not allowed"}
            
        # Determine what specific wearable data is being requested
        message_l = message.lower()
        
        # Extract date information from the message
        query_date = self._extract_date_from_message(message_l)
        logger.info(f"Extracted date from message: {query_date}")
        
        # Initialize wearable data container
        wearable_data = {
            "patient_id": patient_id,
            "data_types": [],
            "data": {}
        }
        
        try:
            # Check if a specific date was requested
            if query_date:
                try:
                    # Get data for the specific date
                    daily_data = await wearable_service.get_daily_vitals(
                        patient_id=patient_id,
                        start_date=query_date,
                        end_date=query_date
                    )
                    
                    if isinstance(daily_data, list) and daily_data:
                        wearable_data["data"]["specific_date"] = daily_data[0]
                        wearable_data["data_types"].append("specific_date")
                        wearable_data["query_date"] = query_date.isoformat()
                        
                        # Log the specific date data for debugging
                        logger.info(f"Retrieved specific date data for {query_date}: {daily_data[0]}")
                    else:
                        # If no daily aggregate found, try to get history data for that date
                        start_datetime = datetime.combine(query_date, datetime.min.time())
                        end_datetime = datetime.combine(query_date, datetime.max.time())
                        
                        history_data = await wearable_service.get_vitals_history(
                            patient_id=patient_id,
                            start_time=start_datetime,
                            end_time=end_datetime
                        )
                        
                        if isinstance(history_data, list) and history_data:
                            wearable_data["data"]["specific_date"] = history_data[0]  # Use the first reading of that day
                            wearable_data["data_types"].append("specific_date")
                            wearable_data["query_date"] = query_date.isoformat()
                            
                            # Log the history data for debugging
                            logger.info(f"Retrieved history data for {query_date}: {history_data[0]}")
                        else:
                            error_msg = f"No data found for {query_date.strftime('%B %d, %Y')}"
                            logger.warning(f"No data found for date {query_date} for patient {patient_id}")
                            wearable_data["data"]["specific_date"] = {"error": error_msg}
                            wearable_data["data_types"].append("specific_date")
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error getting data for specific date {query_date}: {error_msg}")
                    wearable_data["data"]["specific_date"] = {"error": f"Error getting data for {query_date.strftime('%B %d, %Y')}: {error_msg}"}
                    wearable_data["data_types"].append("specific_date")
            
            # Get latest wearable data if no specific date or if "latest" is mentioned
            elif "latest" in message_l or "current" in message_l or "now" in message_l or not query_date:
                try:
                    latest = await wearable_service.get_current_vitals(patient_id)
                    if "error" not in latest:
                        wearable_data["data"]["latest"] = latest
                        wearable_data["data_types"].append("latest")
                        
                        # Log the latest data for debugging
                        logger.info(f"Retrieved latest vitals data: {latest}")
                    else:
                        error_msg = latest.get('error', 'Unknown error')
                        logger.warning(f"Could not get latest vitals: {error_msg}")
                        # Add error to wearable data
                        wearable_data["data"]["latest"] = {"error": error_msg}
                        wearable_data["data_types"].append("latest")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error getting latest vitals: {error_msg}")
                    # Add error to wearable data
                    wearable_data["data"]["latest"] = {"error": f"Error getting latest vitals: {error_msg}"}
                    wearable_data["data_types"].append("latest")
                
            # Get daily aggregates for time ranges
            if "daily" in message_l or "week" in message_l or "month" in message_l:
                try:
                    # Determine date range based on message
                    end_date = datetime.now().date()
                    start_date = end_date - timedelta(days=7)  # Default to 7 days
                    
                    if "month" in message_l:
                        start_date = end_date - timedelta(days=30)
                    elif "week" in message_l:
                        start_date = end_date - timedelta(days=7)
                    
                    daily_data = await wearable_service.get_daily_vitals(
                        patient_id=patient_id,
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if isinstance(daily_data, list) and daily_data:
                        wearable_data["data"]["daily"] = daily_data
                        wearable_data["data_types"].append("daily")
                        
                        # Log the daily data for debugging
                        logger.info(f"Retrieved daily vitals data: {daily_data[:2]}...")  # Log first 2 items to avoid excessive logging
                    else:
                        logger.warning(f"No daily aggregates found for patient {patient_id}")
                except Exception as e:
                    logger.error(f"Error getting daily aggregates: {str(e)}")
                
            # Get trends
            if "trend" in message_l or "pattern" in message_l or "history" in message_l:
                # Determine which vital sign to get trends for
                trend_type = None
                if "heart" in message_l or "pulse" in message_l:
                    trend_type = "heart_rate"
                elif "temp" in message_l:
                    trend_type = "temperature"
                elif "blood pressure" in message_l or "bp" in message_l:
                    trend_type = "blood_pressure"
                elif "oxygen" in message_l or "o2" in message_l:
                    trend_type = "oxygen_level"
                else:
                    # Default to heart rate if not specified
                    trend_type = "heart_rate"
                
                try:
                    # Get trend data for the specified vital sign
                    trend_data = await wearable_service.get_vitals_history(
                        patient_id=patient_id,
                        start_time=datetime.now() - timedelta(days=7),
                        end_time=datetime.now()
                    )
                    
                    if isinstance(trend_data, list) and trend_data:
                        # Process the data to extract trends
                        trend = {
                            "vital_type": trend_type,
                            "period": "Last 7 days",
                            "trend": "stable",  # Default
                            "data_points": []
                        }
                        
                        # Extract the relevant data points
                        for point in trend_data:
                            if trend_type == "blood_pressure":
                                value = {
                                    "systolic": point.get("systolic_bp"),
                                    "diastolic": point.get("diastolic_bp")
                                }
                            else:
                                value = point.get(trend_type)
                                
                            trend["data_points"].append({
                                "date": point.get("timestamp"),
                                "value": value
                            })
                        wearable_data["data"]["trends"] = trend
                        wearable_data["data_types"].append("trends")
                        
                        # Log the trend data for debugging
                        logger.info(f"Created trend data for {trend_type}: {trend}")
                    else:
                        logger.warning(f"No trend data found for patient {patient_id}")
                        logger.warning(f"No trend data found for patient {patient_id}")
                except Exception as e:
                    logger.error(f"Error getting trend data: {str(e)}")
                
            # If no specific wearable data was requested, provide a summary
            if not wearable_data["data_types"]:
                wearable_data["data"]["summary"] = "Wearable data is available for heart rate, temperature, blood pressure, and oxygen levels."
                wearable_data["data_types"].append("summary")
            
            # Log the final wearable data structure
            logger.info(f"Final wearable data structure: data_types={wearable_data['data_types']}, keys={list(wearable_data['data'].keys())}")
                
            return wearable_data
            
        except Exception as e:
            logger.error(f"Error retrieving wearable data: {str(e)}")
    def _extract_date_from_message(self, message: str) -> Optional[date]:
        """
        Extract a date from a message.
        
        Args:
            message: The user's message.
            
        Returns:
            The extracted date, or None if no date was found.
        """
        # Try to extract date using dateparser
        try:
            # Common date patterns in queries
            date_patterns = [
                # Patterns with spaces between day and month
                r'on\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4})',
                r'on\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))',
                r'on\s+(\d{4}-\d{1,2}-\d{1,2})',
                r'on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
                r'on\s+(\d{1,2}-\d{1,2}-\d{2,4})',
                r'for\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4})',
                r'for\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))',
                r'for\s+(\d{4}-\d{1,2}-\d{1,2})',
                r'for\s+(\d{1,2}/\d{1,2}/\d{2,4})',
                r'for\s+(\d{1,2}-\d{1,2}-\d{2,4})',
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4})',
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))',
                r'(\d{4}-\d{1,2}-\d{1,2})',
                r'(\d{1,2}/\d{1,2}/\d{2,4})',
                r'(\d{1,2}-\d{1,2}-\d{2,4})',
                
                # Patterns without spaces between day and month (e.g., "25december2025")
                r'(\d{1,2}(?:st|nd|rd|th)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\d{4})',
                r'(\d{1,2}(?:st|nd|rd|th)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\d{2})',
                r'on\s+(\d{1,2}(?:st|nd|rd|th)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\d{4})',
                r'for\s+(\d{1,2}(?:st|nd|rd|th)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\d{4})'
            ]
            
            # Try to match date patterns
            for pattern in date_patterns:
                match = re.search(pattern, message)
                if match:
                    date_str = match.group(1)
                    logging.info(f"Found date pattern match: '{date_str}' using pattern '{pattern}'")
                    parsed_date = dateparser.parse(date_str)
                    if parsed_date:
                        logging.info(f"Successfully parsed date '{date_str}' to {parsed_date.date()}")
                        return parsed_date.date()
                    else:
                        logging.warning(f"Failed to parse matched date string '{date_str}'")
            
            # If no pattern matched, try dateparser directly
            logging.info(f"No pattern matched, trying dateparser directly on message: '{message}'")
            parsed_date = dateparser.parse(message, settings={
                'PREFER_DAY_OF_MONTH': 'first',
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': datetime.now(),
                'DATE_ORDER': 'DMY'  # Prefer day-month-year order
            })
            
            if parsed_date:
                logging.info(f"Successfully parsed date from full message to {parsed_date.date()}")
                return parsed_date.date()
            else:
                logging.warning(f"Failed to parse date from message: '{message}'")
                
            # Check for relative dates
            if "yesterday" in message:
                return (datetime.now() - timedelta(days=1)).date()
            elif "today" in message:
                return datetime.now().date()
            elif "tomorrow" in message:
                return (datetime.now() + timedelta(days=1)).date()
            elif "last week" in message:
                return (datetime.now() - timedelta(days=7)).date()
                
            return None
        except Exception as e:
            logging.error(f"Error extracting date from message: {e}")
            return None
            return {"error": f"Error retrieving wearable data: {str(e)}"}
    
    async def _get_patient_data(
        self,
        patient_id: Optional[int],
        message: str,
        data_scope: DataScope,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get patient data based on the message and data scope.
        Enforces RBAC + Consent + Minimum Necessary.
        
        Args:
            patient_id: The patient ID.
            message: The user's message.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            Patient data.
        """
        from sqlalchemy import select
        from app.models import Patient, Medication, Vitals, Appointment, CarePlan, LabResult, LabOrder
        
        # 1️⃣ Validate patient_id
        if not patient_id:
            return {"error": "No patient ID provided"}

        # 2️⃣ Verify patient exists
        result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        patient = result.scalar_one_or_none()

        if not patient:
            return {"error": "Patient not found"}

        # 3️⃣ RBAC enforcement (defense in depth)
        if patient_id not in data_scope.patient_ids:
            return {"error": "Access denied"}

        # 4️⃣ Consent check (ROLE AWARE)
        if data_scope.user_role in {"doctor", "hospital"}:
            if not await has_patient_consent(patient_id, db):
                return {"error": "Patient consent not granted"}

        # 5️⃣ Determine requested data types
        message_l = message.lower()
        data_types = []

        if "lab" in message_l:
            data_types.append("labs")
        if "medication" in message_l or "med" in message_l:
            data_types.append("medications")
        if "vital" in message_l:
            data_types.append("vitals")
        if "appointment" in message_l:
            data_types.append("appointments")
        if "care plan" in message_l:
            data_types.append("care_plans")

        # Default → allowed scope only
        if not data_types:
            data_types = list(data_scope.allowed_data_types)

        allowed_data_types = [
            dt for dt in data_types if dt in data_scope.allowed_data_types
        ]

        # 6️⃣ Build response shell
        patient_data = {
            "patient_id": patient_id,
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "data_types": allowed_data_types,
            "data": {}
        }

        # 7️⃣ Fetch data (minimum necessary)
        for data_type in allowed_data_types:

            if data_type == "medications":
                result = await db.execute(
                    select(Medication).where(Medication.patient_id == patient_id)
                )
                patient_data["data"]["medications"] = [
                    {
                        "name": med.medication_name,
                        "dosage": med.dosage,
                        "frequency": med.frequency,
                        "status": med.status
                    }
                    for med in result.scalars().all()
                ]

            elif data_type == "vitals":
                result = await db.execute(
                    select(Vitals)
                    .where(Vitals.patient_id == patient_id)
                    .order_by(Vitals.recorded_at.desc())
                )
                patient_data["data"]["vitals"] = [
                    {
                        "date": vital.recorded_at.isoformat() if vital.recorded_at else None,
                        "blood_pressure": vital.blood_pressure,
                        "heart_rate": vital.heart_rate,
                        "bmi": float(vital.bmi) if vital.bmi else None
                    }
                    for vital in result.scalars().all()
                ]

            elif data_type == "appointments":
                result = await db.execute(
                    select(Appointment).where(Appointment.patient_id == patient_id)
                )
                patient_data["data"]["appointments"] = [
                    {
                        "date": appt.appointment_date.isoformat() if appt.appointment_date else None,
                        "status": appt.status,
                        "mode": appt.mode
                    }
                    for appt in result.scalars().all()
                ]

            elif data_type == "care_plans":
                result = await db.execute(
                    select(CarePlan).where(CarePlan.patient_id == patient_id)
                )
                patient_data["data"]["care_plans"] = [
                    {
                        "status": cp.status,
                        "summary": cp.patient_friendly_summary
                    }
                    for cp in result.scalars().all()
                ]

            elif data_type == "labs":
                result = await db.execute(
                    select(LabOrder).where(LabOrder.patient_id == patient_id)
                )

                labs = []
                for order in result.scalars().all():
                    res = await db.execute(
                        select(LabResult).where(LabResult.lab_order_id == order.id)
                    )
                    labs.append({
                        "test": order.test_name,
                        "status": order.status,
                        "results": [
                            {"value": r.result_value}
                            for r in res.scalars().all()
                        ]
                    })

                patient_data["data"]["labs"] = labs
        # Check if wearable data is requested
        if any(term in message_l for term in ["wearable", "watch", "device", "monitor", "heart rate", "temperature", "blood pressure", "bp", "oxygen"]):
            wearable_data = await self._get_wearable_data(patient_id, message, data_scope, db)
            if "error" not in wearable_data:
                # Add wearable data to patient data
                patient_data["data"]["wearable_data"] = wearable_data["data"]
                patient_data["data_types"].extend(["wearable_data"] + wearable_data["data_types"])
                
                # Extract specific vital signs from wearable data and add them directly to patient data
                # This ensures they're available at the top level for the LLM
                
                # Process blood pressure data if requested
                if "blood pressure" in message_l or "bp" in message_l:
                    # Check for specific date data first
                    if "specific_date" in wearable_data["data"]:
                        specific_data = wearable_data["data"]["specific_date"]
                        logger.info(f"Checking specific_data for blood pressure: {specific_data}")
                        
                        # Check if there's an error in the specific_data
                        if "error" in specific_data:
                            logger.warning(f"Error in specific_date data: {specific_data['error']}")
                            patient_data["data"]["blood_pressure"] = {
                                "error": specific_data["error"]
                            }
                        # Check if blood_pressure is directly in specific_data
                        elif "blood_pressure" in specific_data:
                            bp_data = specific_data["blood_pressure"]
                            # Format the blood pressure data
                            patient_data["data"]["blood_pressure"] = {
                                "systolic": {
                                    "average": bp_data["systolic"]["avg"],
                                    "high": bp_data["systolic"]["high"],
                                    "low": bp_data["systolic"]["low"]
                                },
                                "diastolic": {
                                    "average": bp_data["diastolic"]["avg"],
                                    "high": bp_data["diastolic"]["high"],
                                    "low": bp_data["diastolic"]["low"]
                                },
                                "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                            }
                            logger.info(f"Added blood pressure data from specific date: {patient_data['data']['blood_pressure']}")
                        # Check for older format with systolic_bp and diastolic_bp
                        elif "systolic_bp" in specific_data and "diastolic_bp" in specific_data:
                            patient_data["data"]["blood_pressure"] = {
                                "systolic": specific_data["systolic_bp"],
                                "diastolic": specific_data["diastolic_bp"],
                                "date": wearable_data.get("query_date", "recent date")
                            }
                            logger.info(f"Added blood pressure data from specific date (old format): {patient_data['data']['blood_pressure']}")
                    # If no specific date data, check latest
                    elif "latest" in wearable_data["data"]:
                        latest_data = wearable_data["data"]["latest"]
                        logger.info(f"Checking latest_data for blood pressure: {latest_data}")
                        
                        # Check if there's an error in the latest_data
                        if "error" in latest_data:
                            logger.warning(f"Error in latest_data: {latest_data['error']}")
                            patient_data["data"]["blood_pressure"] = {
                                "error": latest_data["error"]
                            }
                        # Check if blood_pressure is directly in latest_data
                        elif "blood_pressure" in latest_data:
                            bp_data = latest_data["blood_pressure"]
                            # Format the blood pressure data
                            patient_data["data"]["blood_pressure"] = {
                                "systolic": {
                                    "average": bp_data["systolic"]["avg"],
                                    "high": bp_data["systolic"]["high"],
                                    "low": bp_data["systolic"]["low"]
                                },
                                "diastolic": {
                                    "average": bp_data["diastolic"]["avg"],
                                    "high": bp_data["diastolic"]["high"],
                                    "low": bp_data["diastolic"]["low"]
                                },
                                "date": latest_data.get("date", "latest reading")
                            }
                            logger.info(f"Added latest blood pressure data: {patient_data['data']['blood_pressure']}")
                        # Check for older format with systolic_bp and diastolic_bp
                        elif "systolic_bp" in latest_data and "diastolic_bp" in latest_data:
                            patient_data["data"]["blood_pressure"] = {
                                "systolic": latest_data["systolic_bp"],
                                "diastolic": latest_data["diastolic_bp"],
                                "date": "latest reading"
                            }
                            logger.info(f"Added latest blood pressure data (old format): {patient_data['data']['blood_pressure']}")
                
                # Process heart rate data if requested
                if "heart rate" in message_l or "pulse" in message_l:
                    if "specific_date" in wearable_data["data"]:
                        specific_data = wearable_data["data"]["specific_date"]
                        logger.info(f"Checking specific_data for heart rate: {specific_data}")
                        
                        # Check if there's an error in the specific_data
                        if "error" in specific_data:
                            logger.warning(f"Error in specific_date data: {specific_data['error']}")
                            patient_data["data"]["heart_rate"] = {
                                "error": specific_data["error"]
                            }
                        elif "heart_rate" in specific_data:
                            hr_data = specific_data["heart_rate"]
                            # Check if heart_rate is a dictionary with avg, high, low
                            if isinstance(hr_data, dict) and "avg" in hr_data:
                                patient_data["data"]["heart_rate"] = {
                                    "average": hr_data["avg"],
                                    "high": hr_data["high"],
                                    "low": hr_data["low"],
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added heart rate data from specific date: {patient_data['data']['heart_rate']}")
                            # Check if heart_rate is a simple value
                            else:
                                patient_data["data"]["heart_rate"] = {
                                    "value": hr_data,
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added heart rate data from specific date (simple value): {patient_data['data']['heart_rate']}")
                    elif "latest" in wearable_data["data"]:
                        latest_data = wearable_data["data"]["latest"]
                        logger.info(f"Checking latest_data for heart rate: {latest_data}")
                        
                        # Check if there's an error in the latest_data
                        if "error" in latest_data:
                            logger.warning(f"Error in latest_data: {latest_data['error']}")
                            patient_data["data"]["heart_rate"] = {
                                "error": latest_data["error"]
                            }
                        elif "heart_rate" in latest_data:
                            hr_data = latest_data["heart_rate"]
                            # Check if heart_rate is a dictionary with avg, high, low
                            if isinstance(hr_data, dict) and "avg" in hr_data:
                                patient_data["data"]["heart_rate"] = {
                                    "average": hr_data["avg"],
                                    "high": hr_data["high"],
                                    "low": hr_data["low"],
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest heart rate data: {patient_data['data']['heart_rate']}")
                            # Check if heart_rate is a simple value
                            else:
                                patient_data["data"]["heart_rate"] = {
                                    "value": hr_data,
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest heart rate data (simple value): {patient_data['data']['heart_rate']}")
                
                # Process temperature data if requested
                if "temperature" in message_l or "temp" in message_l:
                    if "specific_date" in wearable_data["data"]:
                        specific_data = wearable_data["data"]["specific_date"]
                        logger.info(f"Checking specific_data for temperature: {specific_data}")
                        
                        # Check if there's an error in the specific_data
                        if "error" in specific_data:
                            logger.warning(f"Error in specific_date data: {specific_data['error']}")
                            patient_data["data"]["temperature"] = {
                                "error": specific_data["error"]
                            }
                        elif "temperature" in specific_data:
                            temp_data = specific_data["temperature"]
                            # Check if temperature is a dictionary with avg, high, low
                            if isinstance(temp_data, dict) and "avg" in temp_data:
                                patient_data["data"]["temperature"] = {
                                    "average": temp_data["avg"],
                                    "high": temp_data["high"],
                                    "low": temp_data["low"],
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added temperature data from specific date: {patient_data['data']['temperature']}")
                            # Check if temperature is a simple value
                            else:
                                patient_data["data"]["temperature"] = {
                                    "value": temp_data,
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added temperature data from specific date (simple value): {patient_data['data']['temperature']}")
                    elif "latest" in wearable_data["data"]:
                        latest_data = wearable_data["data"]["latest"]
                        logger.info(f"Checking latest_data for temperature: {latest_data}")
                        
                        # Check if there's an error in the latest_data
                        if "error" in latest_data:
                            logger.warning(f"Error in latest_data: {latest_data['error']}")
                            patient_data["data"]["temperature"] = {
                                "error": latest_data["error"]
                            }
                        elif "temperature" in latest_data:
                            temp_data = latest_data["temperature"]
                            # Check if temperature is a dictionary with avg, high, low
                            if isinstance(temp_data, dict) and "avg" in temp_data:
                                patient_data["data"]["temperature"] = {
                                    "average": temp_data["avg"],
                                    "high": temp_data["high"],
                                    "low": temp_data["low"],
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest temperature data: {patient_data['data']['temperature']}")
                            # Check if temperature is a simple value
                            else:
                                patient_data["data"]["temperature"] = {
                                    "value": temp_data,
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest temperature data (simple value): {patient_data['data']['temperature']}")
                
                # Process oxygen level data if requested
                if "oxygen" in message_l or "o2" in message_l:
                    if "specific_date" in wearable_data["data"]:
                        specific_data = wearable_data["data"]["specific_date"]
                        logger.info(f"Checking specific_data for oxygen level: {specific_data}")
                        
                        # Check if there's an error in the specific_data
                        if "error" in specific_data:
                            logger.warning(f"Error in specific_date data: {specific_data['error']}")
                            patient_data["data"]["oxygen_level"] = {
                                "error": specific_data["error"]
                            }
                        elif "oxygen_level" in specific_data:
                            o2_data = specific_data["oxygen_level"]
                            # Check if oxygen_level is a dictionary with avg, high, low
                            if isinstance(o2_data, dict) and "avg" in o2_data:
                                patient_data["data"]["oxygen_level"] = {
                                    "average": o2_data["avg"],
                                    "high": o2_data["high"],
                                    "low": o2_data["low"],
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added oxygen level data from specific date: {patient_data['data']['oxygen_level']}")
                            # Check if oxygen_level is a simple value
                            else:
                                patient_data["data"]["oxygen_level"] = {
                                    "value": o2_data,
                                    "date": specific_data.get("date", wearable_data.get("query_date", "recent date"))
                                }
                                logger.info(f"Added oxygen level data from specific date (simple value): {patient_data['data']['oxygen_level']}")
                    elif "latest" in wearable_data["data"]:
                        latest_data = wearable_data["data"]["latest"]
                        logger.info(f"Checking latest_data for oxygen level: {latest_data}")
                        
                        # Check if there's an error in the latest_data
                        if "error" in latest_data:
                            logger.warning(f"Error in latest_data: {latest_data['error']}")
                            patient_data["data"]["oxygen_level"] = {
                                "error": latest_data["error"]
                            }
                        elif "oxygen_level" in latest_data:
                            o2_data = latest_data["oxygen_level"]
                            # Check if oxygen_level is a dictionary with avg, high, low
                            if isinstance(o2_data, dict) and "avg" in o2_data:
                                patient_data["data"]["oxygen_level"] = {
                                    "average": o2_data["avg"],
                                    "high": o2_data["high"],
                                    "low": o2_data["low"],
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest oxygen level data: {patient_data['data']['oxygen_level']}")
                            # Check if oxygen_level is a simple value
                            else:
                                patient_data["data"]["oxygen_level"] = {
                                    "value": o2_data,
                                    "date": latest_data.get("date", "latest reading")
                                }
                                logger.info(f"Added latest oxygen level data (simple value): {patient_data['data']['oxygen_level']}")

        return patient_data

    
    async def _get_hospital_data(
        self,
        hospital_id: Optional[int],
        message: str,
        data_scope: DataScope,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get hospital data based on the message and data scope.
        
        Args:
            hospital_id: The hospital ID.
            message: The user's message.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            Hospital data.
        """
        from sqlalchemy import select, func
        from app.models import Hospital, Patient, Doctor, Appointment, User
        
        if not hospital_id:
            return {"error": "No hospital ID provided"}
        
        # Get hospital basic info
        result = await db.execute(
            select(Hospital).where(Hospital.id == hospital_id)
        )
        hospital = result.scalar_one_or_none()
        
        if not hospital:
            return {"error": f"Hospital with ID {hospital_id} not found"}
        
        # Count patients in this hospital
        result = await db.execute(
            select(func.count(Patient.id))
            .join(User, User.id == Patient.user_id)
            .where(User.hospital_id == hospital_id)
        )
        patient_count = result.scalar_one_or_none() or 0
        
        # Count doctors in this hospital
        result = await db.execute(
            select(func.count(Doctor.id)).where(Doctor.hospital_id == hospital_id)
        )
        doctor_count = result.scalar_one_or_none() or 0
        
        # Count appointments in this hospital
        result = await db.execute(
            select(func.count(Appointment.id)).where(Appointment.hospital_id == hospital_id)
        )
        appointment_count = result.scalar_one_or_none() or 0
        
        # Return hospital data
        hospital_data = {
            "hospital_id": hospital_id,
            "name": hospital.name,
            "email": hospital.email,
            "phone": hospital.phone,
            "address": hospital.address,
            "city": hospital.city,
            "state": hospital.state,
            "zip_code": hospital.zip_code,
            "country": hospital.country,
            "patient_count": patient_count,
            "doctor_count": doctor_count,
            "appointment_count": appointment_count
        }
        
        return hospital_data
    
    async def _get_analytics(
        self,
        hospital_id: Optional[int],
        message: str,
        data_scope: DataScope,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get analytics data based on the message and data scope.
        
        Args:
            hospital_id: The hospital ID.
            message: The user's message.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            Analytics data.
        """
        from sqlalchemy import select, func, case
        from app.models import Patient, Appointment, Encounter, Doctor, User
        from datetime import datetime, timedelta
        
        if not hospital_id:
            return {"error": "No hospital ID provided"}
        
        # Initialize analytics data
        analytics_data = {
            "hospital_id": hospital_id,
            "patient_demographics": {},
            "appointment_stats": {},
            "encounter_stats": {}
        }
        
        # Get patient demographics
        # Age groups
        result = await db.execute(
            select(
                case(
                    (Patient.age <= 18, "0-18"),
                    (Patient.age <= 35, "19-35"),
                    (Patient.age <= 50, "36-50"),
                    (Patient.age <= 65, "51-65"),
                    else_="65+"
                ).label("age_group"),
                func.count(Patient.id)
            )
            .join(User, User.id == Patient.user_id)
            .where(User.hospital_id == hospital_id)
            .group_by("age_group")
        )
        age_groups = {row[0]: row[1] for row in result.all()}
        analytics_data["patient_demographics"]["age_groups"] = age_groups
        
        # Gender distribution
        result = await db.execute(
            select(
                Patient.gender,
                func.count(Patient.id)
            )
            .join(User, User.id == Patient.user_id)
            .where(User.hospital_id == hospital_id)
            .group_by(Patient.gender)
        )
        gender_distribution = {row[0]: row[1] for row in result.all()}
        analytics_data["patient_demographics"]["gender"] = gender_distribution
        
        # Appointment stats
        # Appointments this month
        now = datetime.utcnow()
        first_day_of_month = datetime(now.year, now.month, 1)
        first_day_of_last_month = first_day_of_month - timedelta(days=1)
        first_day_of_last_month = datetime(first_day_of_last_month.year, first_day_of_last_month.month, 1)
        
        # This month's appointments
        result = await db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.hospital_id == hospital_id)
            .where(Appointment.appointment_date >= first_day_of_month)
        )
        this_month = result.scalar_one_or_none() or 0
        
        # Last month's appointments
        result = await db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.hospital_id == hospital_id)
            .where(Appointment.appointment_date >= first_day_of_last_month)
            .where(Appointment.appointment_date < first_day_of_month)
        )
        last_month = result.scalar_one_or_none() or 0
        
        # Calculate change percentage
        change_percent = 0
        if last_month > 0:
            change_percent = ((this_month - last_month) / last_month) * 100
        
        analytics_data["appointment_stats"] = {
            "this_month": this_month,
            "last_month": last_month,
            "change_percent": round(change_percent, 2)
        }
        
        # Encounter stats
        # Average length of stay (days between encounters)
        # This is a complex calculation that would require more detailed analysis
        # For now, we'll use a simpler metric: encounters per patient
        
        result = await db.execute(
            select(
                func.count(Encounter.id).label("encounter_count"),
                func.count(func.distinct(Encounter.patient_id)).label("patient_count")
            )
            .where(Encounter.hospital_id == hospital_id)
        )
        row = result.one_or_none()
        encounter_count = row[0] if row else 0
        patient_count = row[1] if row else 0
        
        encounters_per_patient = 0
        if patient_count > 0:
            encounters_per_patient = encounter_count / patient_count
        
        analytics_data["encounter_stats"] = {
            "total_encounters": encounter_count,
            "encounters_per_patient": round(encounters_per_patient, 2)
        }
        
        return analytics_data
    
    async def _extract_patient_id(
        self,
        message: str,
        allowed_patient_ids: List[int],
        db: AsyncSession
    ) -> Optional[int]:
        """
        Extract a patient ID from a message.
        
        Args:
            message: The user's message.
            allowed_patient_ids: The list of patient IDs the user can access.
            db: The database session.
            
        Returns:
            The extracted patient ID, or None if no ID was found.
        """
        from sqlalchemy import select, or_, and_
        from app.models import Patient
        import re
        
        # First, check if any patient ID is mentioned directly
        for patient_id in allowed_patient_ids:
            if str(patient_id) in message:
                logger.info(f"Found patient ID {patient_id} directly in message")
                return patient_id
        
        # Get all patients the user can access
        result = await db.execute(
            select(Patient).where(Patient.id.in_(allowed_patient_ids))
        )
        patients = result.scalars().all()
        
        # Extract potential patient names from the message
        # Look for patterns like "patient John Smith" or "for Jane Doe"
        name_patterns = [
            r'patient\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
            r'for\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
            r'about\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
            r'([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:patient|record|data|info)'
        ]
        
        potential_names = []
        for pattern in name_patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            potential_names.extend(matches)
        
        # If no specific patterns matched, check for any words that might be names
        if not potential_names:
            # Split message into words and check each word against patient names
            words = message.lower().split()
            for patient in patients:
                first_name = patient.first_name.lower()
                last_name = patient.last_name.lower()
                
                if first_name in words or last_name in words:
                    potential_names.append(f"{patient.first_name} {patient.last_name}")
        
        logger.info(f"Potential patient names extracted from message: {potential_names}")
        
        # Match potential names against patient database
        matched_patients = []
        seen_patient_ids = set()  # To track which patients we've already added
        
        for name in potential_names:
            name_parts = name.lower().split()
            
            for patient in patients:
                # Skip if we've already added this patient
                if patient.id in seen_patient_ids:
                    continue
                    
                first_name = patient.first_name.lower()
                last_name = patient.last_name.lower()
                
                # Check for exact match (first name + last name)
                if len(name_parts) >= 2 and first_name == name_parts[0] and last_name == name_parts[1]:
                    matched_patients.append((patient, 3))  # High confidence
                    seen_patient_ids.add(patient.id)
                # Check for partial match (first name only or last name only)
                elif first_name in name_parts or last_name in name_parts:
                    matched_patients.append((patient, 1))  # Low confidence
                    seen_patient_ids.add(patient.id)
        
        # Sort by confidence (highest first)
        matched_patients.sort(key=lambda x: x[1], reverse=True)
        
        # Log the matched patients
        logger.info(f"Matched patients: {[(p[0].first_name + ' ' + p[0].last_name, p[1]) for p in matched_patients]}")
        
        if matched_patients:
            # If we have multiple matches with the same confidence, we need to handle ambiguity
            if len(matched_patients) > 1 and matched_patients[0][1] == matched_patients[1][1]:
                logger.warning(f"Ambiguous patient name match: {[p[0].first_name + ' ' + p[0].last_name for p in matched_patients]}")
                # Use the ambiguity resolution method
                return await self._handle_ambiguous_patient_match(matched_patients, message, db)
            else:
                # Return the highest confidence match
                logger.info(f"Matched patient name to ID {matched_patients[0][0].id} ({matched_patients[0][0].first_name} {matched_patients[0][0].last_name})")
                return matched_patients[0][0].id
        
        # If no specific patient is found, return the first allowed ID
        logger.info(f"No patient name match found, defaulting to first allowed ID: {allowed_patient_ids[0] if allowed_patient_ids else None}")
        return allowed_patient_ids[0] if allowed_patient_ids else None
    
    async def _handle_ambiguous_patient_match(
        self,
        matched_patients: List[tuple],
        message: str,
        db: AsyncSession
    ) -> Optional[int]:
        """
        Handle cases where multiple patients match the name in the message.
        
        Args:
            matched_patients: List of (Patient, confidence) tuples.
            message: The user's message.
            db: The database session.
            
        Returns:
            The resolved patient ID, or None if resolution is not possible.
        """
        from app.models import Appointment, Encounter
        from sqlalchemy import select, func
        from datetime import datetime
        
        # If there's only one match or no matches, no ambiguity to resolve
        if len(matched_patients) <= 1:
            return matched_patients[0][0].id if matched_patients else None
            
        logger.info(f"Resolving ambiguity between {len(matched_patients)} patients")
        
        # Strategy 1: Check for recent interactions
        # For each patient, get their most recent appointment or encounter
        patient_recency = []
        for patient, confidence in matched_patients:
            # Get most recent appointment
            try:
                result = await db.execute(
                    select(Appointment.appointment_date)
                    .where(Appointment.patient_id == patient.id)
                    .order_by(Appointment.appointment_date.desc())
                    .limit(1)
                )
                recent_appointment_date = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Error getting recent appointment for patient {patient.id}: {e}")
                recent_appointment_date = None
            
            # Get most recent encounter
            try:
                result = await db.execute(
                    select(Encounter.encounter_date)
                    .where(Encounter.patient_id == patient.id)
                    .order_by(Encounter.encounter_date.desc())
                    .limit(1)
                )
                recent_encounter_date = result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Error getting recent encounter for patient {patient.id}: {e}")
                recent_encounter_date = None
            
            # Determine most recent interaction date
            recent_date = None
            if recent_appointment_date and recent_encounter_date:
                recent_date = max(
                    recent_appointment_date,
                    recent_encounter_date
                )
            elif recent_appointment_date:
                recent_date = recent_appointment_date
            elif recent_encounter_date:
                recent_date = recent_encounter_date
                
            if recent_date:
                patient_recency.append((patient, recent_date))
                logger.info(f"Patient {patient.first_name} {patient.last_name} has recent interaction on {recent_date}")
        
        # Sort by recency (most recent first)
        patient_recency.sort(key=lambda x: x[1], reverse=True)
        
        if patient_recency:
            # Return the most recently interacted with patient
            logger.info(f"Resolved ambiguity using recency: {patient_recency[0][0].first_name} {patient_recency[0][0].last_name}")
            return patient_recency[0][0].id
            
        # Strategy 2: If recency doesn't help, use the highest confidence match
        highest_confidence = max(matched_patients, key=lambda x: x[1])
        logger.info(f"Resolved ambiguity using confidence: {highest_confidence[0].first_name} {highest_confidence[0].last_name}")
        return highest_confidence[0].id
    
    async def _build_context(
        self,
        user: User,
        message: str,
        previous_messages: List[Message],
        query_type: str,
        data: Dict[str, Any],
        data_scope: DataScope
    ) -> List[Dict[str, str]]:
        """
        Build context for the LLM with PHI protection.
        
        This method applies:
        1. Minimum necessary filtering (only include data relevant to the query)
        2. PHI de-identification (mask sensitive information)
        
        Args:
            user: The user making the request.
            message: The user's message.
            previous_messages: Previous messages in the conversation.
            query_type: The type of query.
            data: The retrieved data.
            data_scope: The user's data scope.
            
        Returns:
            The context for the LLM.
        """
        # Start with system message
        context = [
            {
                "role": "system",
                "content": self._get_system_prompt(user.role, query_type, data_scope)
            }
        ]
        
        # Add data context with PHI protection
        if data:
            # Apply minimum necessary filtering and PHI masking
            protected_data = await self._apply_phi_protection(data, message, query_type)
            
            data_context = self._format_data_for_context(protected_data, query_type)
            if data_context:
                context.append({
                    "role": "system",
                    "content": f"De-identified clinical summary:\n{data_context}"
                })
        
        # Add previous messages
        for msg in previous_messages:
            context.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Add current message
        context.append({
            "role": "user",
            "content": message
        })
        
        return context
    
    async def _apply_phi_protection(
        self,
        data: Dict[str, Any],
        message: str,
        query_type: str
    ) -> Dict[str, Any]:
        """
        Apply PHI protection to data before sending to LLM.
        
        This includes:
        1. Minimum necessary filtering - only include data relevant to the query
        2. De-identification - mask PHI elements
        
        Args:
            data: The raw data retrieved from the database.
            message: The user's message (to determine what's necessary).
            query_type: The type of query.
            
        Returns:
            Protected data ready for LLM context.
        """
        protected_data = {}
        
        for key, value in data.items():
            if key == "patient_data" and isinstance(value, dict):
                # Extract the raw patient data
                raw_data = value.get("data", {})
                
                # Log the raw data types for debugging
                logger.info(f"Raw data keys before PHI protection: {list(raw_data.keys())}")
                
                # Apply minimum necessary filtering with LLM enhancement
                min_necessary_filter = MinimumNecessaryFilter()
                filtered_data = await min_necessary_filter.extract(message, raw_data)
                
                # Apply de-identification
                safe_data = self.phi_masker.deidentify_patient_data(filtered_data)
                
                # Log the safe data types for debugging
                logger.info(f"Safe data keys after PHI protection: {list(safe_data.keys())}")
                
                # Ensure data_types is always a list
                if "data_types" in value and not isinstance(value["data_types"], list):
                    if value["data_types"] is None:
                        value["data_types"] = []
                    else:
                        value["data_types"] = [str(value["data_types"])]
                
                # Ensure specific vital signs are preserved if they exist in the raw data
                # These are important for answering specific queries about vital signs
                for vital_type in ["blood_pressure", "heart_rate", "temperature", "oxygen_level"]:
                    if vital_type in raw_data:
                        # Copy the vital sign data to the safe data
                        safe_data[vital_type] = raw_data[vital_type]
                        logger.info(f"Preserved {vital_type} data in PHI protection: {raw_data[vital_type]}")
                
                # Reconstruct the patient_data structure
                protected_data[key] = {
                    "patient_id": "[MASKED]",  # Mask patient ID
                    "patient_name": "[MASKED]",  # Mask patient name
                    "data_types": value.get("data_types", []),
                    "data": safe_data
                }
            else:
                # For non-patient data (like analytics, hospital data), pass through
                # These typically don't contain individual PHI
                protected_data[key] = value
        
        return protected_data
    
    def _get_system_prompt(self, role: str, query_type: str, data_scope: DataScope) -> str:
        """
        Get the system prompt based on the user's role and query type.
        
        Args:
            role: The user's role.
            query_type: The type of query.
            data_scope: The user's data scope.
            
        Returns:
            The system prompt.
        """
         # Get current date and time
        current_datetime = datetime.now()
        current_date_str = current_datetime.strftime("%Y-%m-%d")
        current_time_str = current_datetime.strftime("%H:%M:%S")
        
        base_prompt = f"""
        You are CareIQ, a healthcare assistant for the Patient360 platform.
        If you get the data as empty then respond the answer correctly rather than "I don't have that information".
        You provide accurate, helpful information based on the data available to you.
        You NEVER make up information or hallucinate data that isn't provided to you.
        If you don't have specific information, say so clearly.
        If you have any queries relevant to upcoming appointment or something which needs time comparison of data to answer then use this date and time to analyze the data coming to you and then answer accordingly.
         CURRENT DATE AND TIME:
            Today's date: {current_date_str}
            Current time: {current_time_str} 
        while answering the queries be mindful of the past present and future of the data.
        CRITICAL ERROR HANDLING:
        - If you see an error message in the data (e.g., "error": "Error getting daily vitals"),
          clearly explain to the user that there was a technical issue retrieving their data.
        - Be transparent about system errors while maintaining a reassuring tone.
        - When data contains error messages, acknowledge them directly in your response.
        
        CRITICAL PHI PROTECTION RULES:
        - The data provided to you has been de-identified for privacy protection
        - DO NOT attempt to re-identify patients or infer protected information
        - DO NOT include specific dates, names, or identifiers in your responses
        - Focus on clinical insights and general patterns, not individual identifiers
        """
        
        role_specific_prompts = {
            "patient": """
            You are speaking directly to a patient about their own health data.
            Use a friendly, supportive tone and avoid medical jargon when possible.
            Explain medical terms in simple language.
            ONLY discuss the patient's own data, never mention other patients.
            
            When technical errors occur (indicated by error messages in the data),
            be transparent but reassuring. Explain that their data couldn't be retrieved
            due to a temporary technical issue, and suggest they try again later or
            contact support if the problem persists.
            """,
            
            "doctor": """
            You are speaking to a healthcare provider about patient data.
            Use professional medical terminology and be precise.
            You can reference specific lab values, medications, and clinical findings.
            Only discuss patients that this doctor has treated.
            
            IMPORTANT: When a doctor mentions a patient by name, the system will automatically
            identify the correct patient based on the name. If multiple patients have similar names,
            the system will use recent interactions to determine the most likely patient.
            """,
            
            "hospital": """
            You are speaking to a hospital administrator about hospital-level data.
            Focus on aggregated statistics and trends, not individual patient details.
            Use business and healthcare administration terminology.
            Highlight operational insights and efficiency metrics.
            """
        }
        
        query_specific_prompts = {
            "data": """
            You are providing specific data from the patient record.
            Be precise and factual, citing dates and values when available.
            Only share data that is explicitly provided in the context.
            Remember: dates and names have been de-identified for privacy.
            
            IMPORTANT: If you encounter an error message in the data (e.g., "error": "Error getting daily vitals"),
            clearly communicate to the user that there was a technical issue retrieving the requested information.
            Explain that their data could not be accessed at this time due to a system error.
            """,
            
            "explanation": """
            You are explaining medical concepts or terminology.
            Provide clear, accurate explanations at an appropriate level for the user.
            Use analogies or simplified explanations when helpful.
            """,
            
            "analytics": """
            You are providing analysis of aggregated healthcare data.
            Focus on trends, patterns, and insights from the data.
            Avoid discussing individual patients and focus on population-level insights.
            """,
            
            "recommendation": """
            You are providing health recommendations based on patient data.
            Be cautious and conservative in your recommendations.
            Always clarify that these are general suggestions, not medical advice.
            Encourage the user to consult with their healthcare provider for personalized advice.
            """,
            
            "action": """
            You are helping the user perform healthcare-related actions.
            Guide them through the process of scheduling appointments, requesting medication refills,
            or contacting their healthcare provider.
            Be clear about what actions are available and how to initiate them.
            """,
            
            # Hybrid prompts for common combinations
            "data+explanation": """
            You are providing specific patient data AND explaining what it means.
            First present the data clearly and factually, then explain its significance.
            Use simple language to help the patient understand their health information.
            Remember to check for error messages in the data and communicate them clearly.
            """,
            
            "data+recommendation": """
            You are providing specific patient data AND offering general health recommendations.
            Present the data first, then offer context-appropriate suggestions.
            Be very clear that your recommendations are general in nature, not medical advice.
            Always encourage consulting with a healthcare provider for personalized guidance.
            """,
            
            "explanation+recommendation": """
            You are explaining medical concepts AND offering general health recommendations.
            Provide clear explanations of medical terms or concepts first.
            Then offer general recommendations related to the topic.
            Be very clear that your recommendations are general in nature, not medical advice.
            """
        }
        
        # Combine prompts
        combined_prompt = base_prompt
        
        if role in role_specific_prompts:
            combined_prompt += "\n\n" + role_specific_prompts[role]
        
        # Handle hybrid query types
        if "+" in query_type:
            # Check if we have a specific prompt for this hybrid type
            if query_type in query_specific_prompts:
                combined_prompt += "\n\n" + query_specific_prompts[query_type]
            else:
                # If no specific hybrid prompt, combine individual prompts
                query_types = query_type.split("+")
                for qt in query_types:
                    if qt in query_specific_prompts:
                        combined_prompt += "\n\n" + query_specific_prompts[qt]
        elif query_type in query_specific_prompts:
            combined_prompt += "\n\n" + query_specific_prompts[query_type]
        
        # Add data scope information
        combined_prompt += f"\n\nYou can ONLY access the following data types: {', '.join(data_scope.allowed_data_types)}."
        
        if role == "patient":
            combined_prompt += "\n\nYou can ONLY discuss the patient's own health data, never other patients."
        elif role == "doctor":
            combined_prompt += f"\n\nYou can ONLY discuss patients with these IDs: {data_scope.patient_ids}."
        elif role == "hospital":
            combined_prompt += f"\n\nYou can ONLY discuss aggregated data for hospital ID: {data_scope.hospital_ids[0] if data_scope.hospital_ids else 'None'}."
        
        return combined_prompt
    
    def _format_data_for_context(self, data: Dict[str, Any], query_type: str) -> str:
        """
        Format data for the LLM context.
        
        Args:
            data: The data to format.
            query_type: The type of query.
            
        Returns:
            The formatted data.
        """
        if not data:
            return ""
        
        # Convert data to a formatted string
        return json.dumps(data, indent=2)
    
    async def _generate_response(self, context: List[Dict[str, str]]) -> str:
        """
        Generate a response from the LLM.
        
        Args:
            context: The context for the LLM.
            
        Returns:
            The generated response.
        """
        # Log the full context being sent to the LLM
        logger.info("Full LLM context:")
        for i, msg in enumerate(context):
            logger.info(f"Message {i} - Role: {msg['role']}")
            # Truncate content if it's too long for logs
            content = msg['content']
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            logger.info(f"Content: {content}")
        
        try:
            # Call OpenAI API
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=context,
                temperature=0.3,
                max_tokens=500
            )
            
            # Extract the response text
            return response.choices[0].message.content.strip()
        
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I'm sorry, I encountered an error processing your request. Please try again later."
    
    def _validate_response(self, response: str, data_scope: DataScope) -> str:
        """
        Validate the response to ensure it doesn't violate data access rules.
        
        Args:
            response: The generated response.
            data_scope: The user's data scope.
            
        Returns:
            The validated response.
        """
        # Additional validation can be added here
        # The sanitize_response function has already been applied in process_chat_request
        return response