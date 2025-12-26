"""
Role-Based Access Control (RBAC) for the Patient360 Chatbot.

This module implements RBAC for the chatbot, ensuring that users can only
access data they are authorized to see.
"""

import logging
from typing import List, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Patient, Doctor, Encounter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataScope:
    """
    Data scope for a user.
    
    This class represents the data a user is allowed to access.
    """
    
    def __init__(
        self,
        user_role: str,
        allowed_data_types: Set[str],
        patient_ids: Optional[List[int]] = None,
        hospital_ids: Optional[List[int]] = None,
        can_access_analytics: bool = False
    ):
        """
        Initialize the data scope.
        
        Args:
            user_role: The user's role.
            allowed_data_types: The types of data the user is allowed to access.
            patient_ids: The IDs of patients the user is allowed to access.
            hospital_ids: The IDs of hospitals the user is allowed to access.
            can_access_analytics: Whether the user can access analytics data.
        """
        self.user_role = user_role
        self.allowed_data_types = allowed_data_types
        self.patient_ids = patient_ids or []
        self.hospital_ids = hospital_ids or []
        self.can_access_analytics = can_access_analytics
    
    def __str__(self) -> str:
        """Return a string representation of the data scope."""
        return (
            f"DataScope(user_role={self.user_role}, "
            f"allowed_data_types={self.allowed_data_types}, "
            f"patient_ids={self.patient_ids}, "
            f"hospital_ids={self.hospital_ids}, "
            f"can_access_analytics={self.can_access_analytics})"
        )


async def get_data_scope(user: User, db: AsyncSession) -> DataScope:
    """
    Get the data scope for a user.
    
    Args:
        user: The user.
        db: The database session.
        
    Returns:
        The user's data scope.
    """
    # Define allowed data types based on role
    if user.role == "patient":
        allowed_data_types = {
            "labs", "medications", "vitals", "appointments", "care_plans"
        }
        
        # Get patient ID
        result = await db.execute(
            select(Patient.id).where(Patient.user_id == user.id)
        )
        patient = result.scalar_one_or_none()
        
        if patient:
            return DataScope(
                user_role=user.role,
                allowed_data_types=allowed_data_types,
                patient_ids=[patient],
                can_access_analytics=False
            )
        else:
            logger.warning(f"No patient record found for user {user.id}")
            return DataScope(
                user_role=user.role,
                allowed_data_types=allowed_data_types,
                can_access_analytics=False
            )
    
    elif user.role == "doctor":
        allowed_data_types = {
            "labs", "medications", "vitals", "appointments", "care_plans",
            "encounters", "diagnoses"
        }
        
        # Get doctor ID
        result = await db.execute(
            select(Doctor.id).where(Doctor.user_id == user.id)
        )
        doctor = result.scalar_one_or_none()
        
        if doctor:
            # Get patient IDs for patients the doctor has treated
            result = await db.execute(
                select(Encounter.patient_id)
                .where(Encounter.doctor_id == doctor)
                .distinct()
            )
            patient_ids = [row[0] for row in result.all()]
            
            return DataScope(
                user_role=user.role,
                allowed_data_types=allowed_data_types,
                patient_ids=patient_ids,
                hospital_ids=[user.hospital_id] if user.hospital_id else [],
                can_access_analytics=True
            )
        else:
            logger.warning(f"No doctor record found for user {user.id}")
            return DataScope(
                user_role=user.role,
                allowed_data_types=allowed_data_types,
                hospital_ids=[user.hospital_id] if user.hospital_id else [],
                can_access_analytics=True
            )
    
    elif user.role == "hospital":
        allowed_data_types = {
            "aggregated_data", "analytics", "hospital_stats"
        }
        
        return DataScope(
            user_role=user.role,
            allowed_data_types=allowed_data_types,
            hospital_ids=[user.hospital_id] if user.hospital_id else [],
            can_access_analytics=True
        )
    
    else:
        # Default scope for unknown roles
        logger.warning(f"Unknown role: {user.role}")
        return DataScope(
            user_role=user.role,
            allowed_data_types=set(),
            can_access_analytics=False
        )


def validate_data_access(data_scope: DataScope, data_type: str, entity_id: Optional[int] = None) -> bool:
    """
    Validate data access.
    
    Args:
        data_scope: The user's data scope.
        data_type: The type of data being accessed.
        entity_id: The ID of the entity being accessed.
        
    Returns:
        Whether the access is allowed.
    """
    # Check if the data type is allowed
    if data_type not in data_scope.allowed_data_types:
        logger.warning(f"Access denied: data type {data_type} not allowed for role {data_scope.user_role}")
        return False
    
    # For patient data, check if the patient ID is allowed
    if data_type in {"labs", "medications", "vitals", "appointments", "care_plans", "encounters", "diagnoses"}:
        if entity_id is not None and entity_id not in data_scope.patient_ids:
            logger.warning(f"Access denied: patient ID {entity_id} not allowed for user")
            return False
    
    # For hospital data, check if the hospital ID is allowed
    if data_type in {"aggregated_data", "analytics", "hospital_stats"}:
        if entity_id is not None and entity_id not in data_scope.hospital_ids:
            logger.warning(f"Access denied: hospital ID {entity_id} not allowed for user")
            return False
    
    # For analytics, check if the user can access analytics
    if data_type == "analytics" and not data_scope.can_access_analytics:
        logger.warning(f"Access denied: analytics not allowed for role {data_scope.user_role}")
        return False
    
    return True