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
from typing import List, Dict, Any, Optional, Tuple
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
        context = self._build_context(
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
        
        # CRITICAL: Audit log the interaction for HIPAA compliance
        await log_chat_interaction(
            user_id=user.id,
            message=message,
            response=validated_response,
            query_type=query_type,
            data_accessed=data_accessed,
            context=context,
            db=db
        )
        
        return ChatResponse(
            response=validated_response,
            query_type=query_type,
            data_accessed=data_accessed
        )
    
    async def _classify_query(self, message: str) -> str:
        """
        Classify the user's query.
        
        Args:
            message: The user's message.
            
        Returns:
            The query type: 'data', 'explanation', or 'analytics'.
        """
        # Use OpenAI to classify the query
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """
                    You are a query classifier for a healthcare chatbot. Classify the query into one of these categories:
                    - data: Requests for specific patient data (labs, medications, vitals, etc.)
                    - explanation: Requests for explanations of medical terms or concepts
                    - analytics: Requests for aggregated statistics or trends
                    
                    Respond with ONLY the category name, nothing else.
                    """
                },
                {"role": "user", "content": message}
            ],
            temperature=0.1,
            max_tokens=10
        )
        
        # Extract the query type from the response
        query_type = response.choices[0].message.content.strip().lower()
        
        # Validate query type
        valid_types = ["data", "explanation", "analytics"]
        if query_type not in valid_types:
            query_type = "explanation"  # Default to explanation
        
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
        
        Args:
            user: The user making the request.
            message: The user's message.
            query_type: The type of query.
            data_scope: The user's data scope.
            db: The database session.
            
        Returns:
            A tuple of (data, data_accessed).
        """
        data = {}
        data_accessed = []
        
        if db is None:
            logger.warning("No database session provided, cannot retrieve real data")
            return data, data_accessed
        
        if query_type == "data":
            # For data queries, retrieve specific patient data
            if user.role == "patient":
                # Patient can only access their own data
                data["patient_data"] = await self._get_patient_data(
                    patient_id=data_scope.patient_ids[0] if data_scope.patient_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                data_accessed.append("patient_data")
            
            elif user.role == "doctor":
                # Doctor can access data for patients they have treated
                # First, extract patient name or ID from the message
                patient_id = await self._extract_patient_id(message, data_scope.patient_ids, db)
                
                if patient_id and patient_id in data_scope.patient_ids:
                    data["patient_data"] = await self._get_patient_data(
                        patient_id=patient_id,
                        message=message,
                        data_scope=data_scope,
                        db=db
                    )
                    data_accessed.append(f"patient_data:{patient_id}")
            
            elif user.role == "hospital":
                # Hospital admin can access aggregated data
                data["hospital_data"] = await self._get_hospital_data(
                    hospital_id=data_scope.hospital_ids[0] if data_scope.hospital_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                data_accessed.append("hospital_data")
        
        elif query_type == "explanation":
            # For explanation queries, use RAG to retrieve relevant information
            rag_results = await self.rag_pipeline.query(message)
            data["rag_results"] = rag_results
            data_accessed.append("medical_knowledge")
        
        elif query_type == "analytics":
            # For analytics queries, retrieve aggregated data
            if user.role == "hospital" and data_scope.can_access_analytics:
                data["analytics"] = await self._get_analytics(
                    hospital_id=data_scope.hospital_ids[0] if data_scope.hospital_ids else None,
                    message=message,
                    data_scope=data_scope,
                    db=db
                )
                data_accessed.append("analytics")
        
        return data, data_accessed
    
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
        from sqlalchemy import select
        from app.models import Patient
        
        # First, check if any patient ID is mentioned directly
        for patient_id in allowed_patient_ids:
            if str(patient_id) in message:
                return patient_id
        
        # Next, check if a patient name is mentioned
        # Get all patients the user can access
        result = await db.execute(
            select(Patient).where(Patient.id.in_(allowed_patient_ids))
        )
        patients = result.scalars().all()
        
        # Check if any patient name is mentioned in the message
        for patient in patients:
            full_name = f"{patient.first_name} {patient.last_name}".lower()
            if patient.first_name.lower() in message.lower() or patient.last_name.lower() in message.lower() or full_name in message.lower():
                return patient.id
        
        # If no specific patient is found, return the first allowed ID
        return allowed_patient_ids[0] if allowed_patient_ids else None
    
    def _build_context(
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
            protected_data = self._apply_phi_protection(data, message, query_type)
            
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
    
    def _apply_phi_protection(
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
                
                # Apply minimum necessary filtering
                filtered_data = MinimumNecessaryFilter.extract(message, raw_data)
                
                # Apply de-identification
                safe_data = self.phi_masker.deidentify_patient_data(filtered_data)
                
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
        base_prompt = """
        You are CareIQ, a healthcare assistant for the Patient360 platform. 
        You provide accurate, helpful information based on the data available to you.
        You NEVER make up information or hallucinate data that isn't provided to you.
        If you don't have specific information, say so clearly.
        
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
            """,
            
            "doctor": """
            You are speaking to a healthcare provider about patient data.
            Use professional medical terminology and be precise.
            You can reference specific lab values, medications, and clinical findings.
            Only discuss patients that this doctor has treated.
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
            """
        }
        
        # Combine prompts
        combined_prompt = base_prompt
        
        if role in role_specific_prompts:
            combined_prompt += "\n\n" + role_specific_prompts[role]
        
        if query_type in query_specific_prompts:
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