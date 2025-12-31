"""
Wearable Service Client

This module provides a client for interacting with the wearable backend service via API.
Instead of directly accessing the wearable database, this client makes HTTP requests
to the wearable backend API endpoints.

The client supports querying wearable data by specific dates, date ranges, and other parameters.
"""

import os
import httpx
import logging
import dateparser
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, date, time
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

class WearableServiceClient:
    """Client for interacting with the Wearable Backend Service."""
    
    def __init__(self):
        """Initialize the wearable service client."""
        self.base_url = os.getenv("WEARABLE_SERVICE_URL", "http://localhost:5000/api")
        self.timeout = 10.0  # seconds
        logger.info(f"Initialized wearable service client with base URL: {self.base_url}")
        
    def _parse_date(self, date_str: str) -> Optional[date]:
        """
        Parse a date string into a date object.
        
        Args:
            date_str: The date string to parse
            
        Returns:
            A date object, or None if parsing failed
        """
        try:
            # Try to parse the date using dateparser
            parsed_date = dateparser.parse(
                date_str,
                settings={
                    'DATE_ORDER': 'DMY',
                    'PREFER_DAY_OF_MONTH': 'first',
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': datetime.now()
                }
            )
            
            if parsed_date:
                return parsed_date.date()
            return None
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}")
            return None
    
    def _format_date_for_api(self, date_obj: Union[date, datetime, str]) -> Optional[str]:
        """
        Format a date object for API requests.
        
        Args:
            date_obj: A date object, datetime object, or date string
            
        Returns:
            A formatted date string in ISO format, or None if formatting failed
        """
        try:
            if isinstance(date_obj, str):
                # Try to parse the string to a date
                parsed_date = self._parse_date(date_obj)
                if parsed_date:
                    return parsed_date.isoformat()
                return None
            elif isinstance(date_obj, datetime):
                # Ensure datetime has timezone info
                if date_obj.tzinfo is None:
                    date_obj = date_obj.replace(tzinfo=pytz.UTC)
                return date_obj.isoformat()
            elif isinstance(date_obj, date):
                return date_obj.isoformat()
            return None
        except Exception as e:
            logger.error(f"Error formatting date '{date_obj}': {e}")
            return None
    
    async def get_patient_profile(self, patient_id: int) -> Dict[str, Any]:
        """
        Get a patient profile from the wearable service.
        
        Args:
            patient_id: The ID of the patient
            
        Returns:
            The patient profile data
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/patients/{patient_id}",
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Patient {patient_id} not found in wearable service")
                return {"error": "Patient not found"}
            logger.error(f"HTTP error getting patient profile: {e}")
            raise
        except Exception as e:
            logger.error(f"Error getting patient profile: {e}")
            raise
    
    async def connect_patient_device(self, patient_id: int, device_type: str = "Apple Watch") -> Dict[str, Any]:
        """
        Connect a patient's wearable device.
        This simulates connecting a wearable device for a patient and initializes data generation.
        
        Args:
            patient_id: The ID of the patient
            device_type: The type of wearable device
            
        Returns:
            Connection status and latest vitals
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/patients/{patient_id}/connect",
                    json={"device_type": device_type},
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error connecting patient device: {e}")
            raise
    
    async def get_current_vitals(self, patient_id: int) -> Dict[str, Any]:
        """
        Get the most recent vital signs for a patient.
        
        Args:
            patient_id: The ID of the patient
            
        Returns:
            The latest vital signs data
        """
        try:
            logger.info(f"Requesting current vitals for patient {patient_id}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/patients/{patient_id}/vitals/current",
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                logger.info(f"Successfully retrieved current vitals for patient {patient_id}")
                return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                error_message = f"No vital data found for patient {patient_id}"
                logger.warning(error_message)
                return {"error": error_message}
            error_message = f"HTTP error getting current vitals: {e}"
            logger.error(error_message)
            return {"error": error_message, "status_code": e.response.status_code}
        except httpx.ConnectError as e:
            error_message = f"Connection error to wearable service: {e}"
            logger.error(error_message)
            return {"error": error_message, "type": "connection_error"}
        except Exception as e:
            error_message = f"Error getting current vitals: {str(e) if str(e) else 'Unknown error'}"
            logger.error(error_message)
            return {"error": error_message}
    
    async def get_vitals_history(
        self,
        patient_id: int,
        start_time: Optional[Union[datetime, date, str]] = None,
        end_time: Optional[Union[datetime, date, str]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get historical vital signs for a patient.
        
        Args:
            patient_id: The ID of the patient
            start_time: Optional start time for the history query (default: 24 hours ago)
                Can be a datetime object, date object, or string in various formats
            end_time: Optional end time for the history query (default: now)
                Can be a datetime object, date object, or string in various formats
            limit: Maximum number of records to return
            
        Returns:
            List of historical vital signs data
            
        Example:
            To get data for a specific date:
            ```
            # Using datetime objects
            data = await wearable_service.get_vitals_history(
                patient_id=123,
                start_time=datetime.combine(date(2025, 12, 25), time.min),
                end_time=datetime.combine(date(2025, 12, 25), time.max)
            )
            
            # Using date objects
            data = await wearable_service.get_vitals_history(
                patient_id=123,
                start_time=date(2025, 12, 25),  # Will be converted to start of day
                end_time=date(2025, 12, 25)     # Will be converted to end of day
            )
            
            # Using strings
            data = await wearable_service.get_vitals_history(
                patient_id=123,
                start_time="25 December 2025",
                end_time="25 December 2025"
            )
            
            # Using strings without spaces
            data = await wearable_service.get_vitals_history(
                patient_id=123,
                start_time="25december2025",
                end_time="25december2025"
            )
            ```
        """
        try:
            params = {"limit": limit}
            
            # Convert start_time to ISO format if provided
            if start_time:
                if isinstance(start_time, str):
                    # Try to parse the string to a date
                    parsed_date = self._parse_date(start_time)
                    if parsed_date:
                        # Convert to datetime at start of day
                        start_datetime = datetime.combine(parsed_date, time.min)
                        params["start_time"] = start_datetime.isoformat()
                        logger.info(f"Parsed start_time '{start_time}' to '{start_datetime.isoformat()}'")
                    else:
                        logger.warning(f"Failed to parse start_time '{start_time}'")
                elif isinstance(start_time, date) and not isinstance(start_time, datetime):
                    # Convert date to datetime at start of day
                    start_datetime = datetime.combine(start_time, time.min)
                    params["start_time"] = start_datetime.isoformat()
                else:
                    # Use _format_date_for_api for datetime objects
                    formatted_start_time = self._format_date_for_api(start_time)
                    if formatted_start_time:
                        params["start_time"] = formatted_start_time
            
            # Convert end_time to ISO format if provided
            if end_time:
                if isinstance(end_time, str):
                    # Try to parse the string to a date
                    parsed_date = self._parse_date(end_time)
                    if parsed_date:
                        # Convert to datetime at end of day
                        end_datetime = datetime.combine(parsed_date, time.max)
                        params["end_time"] = end_datetime.isoformat()
                        logger.info(f"Parsed end_time '{end_time}' to '{end_datetime.isoformat()}'")
                    else:
                        logger.warning(f"Failed to parse end_time '{end_time}'")
                elif isinstance(end_time, date) and not isinstance(end_time, datetime):
                    # Convert date to datetime at end of day
                    end_datetime = datetime.combine(end_time, time.max)
                    params["end_time"] = end_datetime.isoformat()
                else:
                    # Use _format_date_for_api for datetime objects
                    formatted_end_time = self._format_date_for_api(end_time)
                    if formatted_end_time:
                        params["end_time"] = formatted_end_time
                
            # Log the request for debugging
            logger.info(f"Requesting vitals history for patient {patient_id} with params: {params}")
                
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/patients/{patient_id}/vitals/history",
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                
                # Log the response for debugging
                logger.info(f"Received {len(data) if isinstance(data, list) else 'non-list'} vitals history records")
                
                return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"No vitals history found for patient {patient_id} in time range")
                return []
            error_message = f"HTTP error getting vitals history: {e}"
            logger.error(error_message)
            return [{"error": error_message}]
        except Exception as e:
            error_message = f"Error getting vitals history: {e}"
            logger.error(error_message)
            return [{"error": error_message}]  # Return error in list format for consistent handling
    
    async def get_daily_vitals(
        self,
        patient_id: int,
        start_date: Optional[Union[date, datetime, str]] = None,
        end_date: Optional[Union[date, datetime, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get daily aggregated vital signs for a patient.
        
        Args:
            patient_id: The ID of the patient
            start_date: Optional start date for the query (default: 7 days ago)
                Can be a date object, datetime object, or string in various formats
            end_date: Optional end date for the query (default: today)
                Can be a date object, datetime object, or string in various formats
            
        Returns:
            List of daily aggregated vital signs data
            
        Example:
            To get data for a specific date:
            ```
            # Using date objects
            data = await wearable_service.get_daily_vitals(
                patient_id=123,
                start_date=date(2025, 12, 25),
                end_date=date(2025, 12, 25)
            )
            
            # Using strings
            data = await wearable_service.get_daily_vitals(
                patient_id=123,
                start_date="25 December 2025",
                end_date="25 December 2025"
            )
            
            # Using strings without spaces
            data = await wearable_service.get_daily_vitals(
                patient_id=123,
                start_date="25december2025",
                end_date="25december2025"
            )
            ```
        """
        try:
            params = {}
            
            # Convert start_date to ISO format if provided
            if start_date:
                if isinstance(start_date, str):
                    # Try to parse the string to a date
                    parsed_start_date = self._parse_date(start_date)
                    if parsed_start_date:
                        params["start_date"] = parsed_start_date.isoformat()
                        logger.info(f"Parsed start_date '{start_date}' to '{parsed_start_date.isoformat()}'")
                    else:
                        logger.warning(f"Failed to parse start_date '{start_date}'")
                else:
                    # Use _format_date_for_api for date/datetime objects
                    formatted_start_date = self._format_date_for_api(start_date)
                    if formatted_start_date:
                        params["start_date"] = formatted_start_date
            
            # Convert end_date to ISO format if provided
            if end_date:
                if isinstance(end_date, str):
                    # Try to parse the string to a date
                    parsed_end_date = self._parse_date(end_date)
                    if parsed_end_date:
                        params["end_date"] = parsed_end_date.isoformat()
                        logger.info(f"Parsed end_date '{end_date}' to '{parsed_end_date.isoformat()}'")
                    else:
                        logger.warning(f"Failed to parse end_date '{end_date}'")
                else:
                    # Use _format_date_for_api for date/datetime objects
                    formatted_end_date = self._format_date_for_api(end_date)
                    if formatted_end_date:
                        params["end_date"] = formatted_end_date
                
            # Log the request for debugging
            logger.info(f"Requesting daily vitals for patient {patient_id} with params: {params}")
                
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/patients/{patient_id}/vitals/daily",
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                
                # Log the response for debugging
                logger.info(f"Received {len(data) if isinstance(data, list) else 'non-list'} daily vitals records")
                
                return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"No daily vitals found for patient {patient_id} in date range")
                return []
            error_message = f"HTTP error getting daily vitals: {e}"
            logger.error(error_message)
            return [{"error": error_message}]
        except Exception as e:
            error_message = f"Error getting daily vitals: {e}"
            logger.error(error_message)
            return [{"error": error_message}]  # Return error in list format for consistent handling
    
    async def generate_data(self, patient_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Manually trigger data generation for a specific patient or all active patients.
        
        Args:
            patient_id: Optional ID of the specific patient to generate data for
            
        Returns:
            Status of the data generation request
        """
        try:
            data = {}
            if patient_id:
                data["patient_id"] = patient_id
                
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/generate-data",
                    json=data,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error generating data: {e}")
            raise
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the wearable service is running.
        
        Returns:
            Health status of the wearable service
        """
        try:
            logger.info(f"Checking health of wearable service at {self.base_url}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                logger.info(f"Wearable service health check successful: {data}")
                return data
        except httpx.ConnectError as e:
            error_message = f"Connection error to wearable service: {e}"
            logger.error(error_message)
            return {
                "status": "error",
                "message": error_message,
                "type": "connection_error",
                "timestamp": datetime.now(IST).isoformat()
            }
        except httpx.TimeoutException as e:
            error_message = f"Timeout connecting to wearable service: {e}"
            logger.error(error_message)
            return {
                "status": "error",
                "message": error_message,
                "type": "timeout",
                "timestamp": datetime.now(IST).isoformat()
            }
        except Exception as e:
            error_message = f"Error checking wearable service health: {str(e) if str(e) else 'Unknown error'}"
            logger.error(error_message)
            return {
                "status": "error",
                "message": error_message,
                "type": "unknown_error",
                "timestamp": datetime.now(IST).isoformat()
            }

# Create a singleton instance
wearable_service = WearableServiceClient()