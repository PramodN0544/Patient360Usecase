from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pytz
import logging

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Patient
from app.wearable_service import wearable_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/wearable",
    tags=["wearable"],
    responses={404: {"description": "Not found"}},
)

# Get the latest wearable data for a patient
@router.get("/latest/{patient_id}")
async def get_latest_wearable_data(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the latest wearable data for a patient.
    
    This endpoint returns the most recent vital signs recorded by the patient's wearable device.
    """
    # Check permissions
    if current_user.role == "patient":
        # Patients can only access their own data
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == current_user.id)
        )
        patient = patient_result.scalar_one_or_none()
        
        if not patient or patient.id != patient_id:
            raise HTTPException(
                status_code=403,
                detail="You can only access your own wearable data"
            )
    elif current_user.role == "doctor":
        # Doctors can access data for patients they have treated
        # This would typically check against encounters or assignments
        pass
    elif current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access wearable data"
        )
    
    # Get the latest wearable data using the wearable service client
    try:
        # Call the wearable service to get current vitals
        latest_data = await wearable_service.get_current_vitals(patient_id)
        
        # Check if there was an error
        if "error" in latest_data:
            logger.warning(f"No vital data found for patient {patient_id}")
            raise HTTPException(
                status_code=404,
                detail="No vital data found for this patient"
            )
        
        return latest_data
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error retrieving wearable data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving wearable data: {str(e)}"
        )

# Get daily aggregates for a patient
@router.get("/daily/{patient_id}")
async def get_daily_aggregates(
    patient_id: int,
    days: int = Query(7, description="Number of days to retrieve"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get daily aggregated wearable data for a patient.
    
    This endpoint returns the daily low, high, and average values for vital signs
    over the specified number of days.
    """
    # Check permissions (same as above)
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == current_user.id)
        )
        patient = patient_result.scalar_one_or_none()
        
        if not patient or patient.id != patient_id:
            raise HTTPException(
                status_code=403,
                detail="You can only access your own wearable data"
            )
    elif current_user.role not in ["doctor", "admin", "hospital"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access wearable data"
        )
    
    # Get daily aggregates using the wearable service client
    try:
        # Calculate the start and end dates
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Call the wearable service to get daily aggregates
        daily_data = await wearable_service.get_daily_vitals(
            patient_id=patient_id,
            start_date=start_date,
            end_date=end_date
        )
        
        # Check if there was an error
        if isinstance(daily_data, dict) and "error" in daily_data:
            logger.warning(f"No daily aggregates found for patient {patient_id}")
            raise HTTPException(
                status_code=404,
                detail="No daily aggregates found for this patient"
            )
        
        return daily_data
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error retrieving daily aggregates: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving daily aggregates: {str(e)}"
        )

# Get trends for a specific vital sign
@router.get("/trends/{patient_id}/{vital_type}")
async def get_vital_trends(
    patient_id: int,
    vital_type: str,
    days: int = Query(30, description="Number of days for trend analysis"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get trends for a specific vital sign.
    
    This endpoint analyzes the trends for a specific vital sign over time
    and provides insights about the patient's health.
    
    Valid vital_type values: heart_rate, temperature, blood_pressure, oxygen_level
    """
    # Check permissions (same as above)
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == current_user.id)
        )
        patient = patient_result.scalar_one_or_none()
        
        if not patient or patient.id != patient_id:
            raise HTTPException(
                status_code=403,
                detail="You can only access your own wearable data"
            )
    elif current_user.role not in ["doctor", "admin", "hospital"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access wearable data"
        )
    
    # Validate vital type
    valid_vital_types = ["heart_rate", "temperature", "blood_pressure", "oxygen_level"]
    if vital_type not in valid_vital_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid vital type. Must be one of: {', '.join(valid_vital_types)}"
        )
    
    # Get trend data using the wearable service client
    try:
        # Calculate the start and end times
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        # Get historical data for the specified period
        history_data = await wearable_service.get_vitals_history(
            patient_id=patient_id,
            start_time=start_time,
            end_time=end_time,
            limit=1000  # Get enough data points for trend analysis
        )
        
        # Check if there was an error or no data
        if isinstance(history_data, dict) and "error" in history_data:
            logger.warning(f"No vital history found for patient {patient_id}")
            raise HTTPException(
                status_code=404,
                detail="No vital history found for this patient"
            )
        
        if not history_data:
            logger.warning(f"No data points available for trend analysis for patient {patient_id}")
            raise HTTPException(
                status_code=404,
                detail="No data points available for trend analysis"
            )
        
        # Process the data to extract the specific vital sign and analyze trends
        # This is a simplified version - in a real implementation, you would do more sophisticated analysis
        data_points = []
        values = []
        
        for point in history_data:
            if vital_type == "blood_pressure":
                value = {
                    "systolic": point.get("systolic_bp"),
                    "diastolic": point.get("diastolic_bp")
                }
                if value["systolic"] is not None and value["diastolic"] is not None:
                    values.append(value["systolic"])  # For average calculation, use systolic
            else:
                value = point.get(vital_type)
                if value is not None:
                    values.append(value)
            
            if value is not None:
                data_points.append({
                    "date": point.get("timestamp"),
                    "value": value
                })
        
        # Calculate average and determine trend
        if not values:
            trend = "unknown"
            average = None
        else:
            # Simple trend analysis based on first and last values
            if vital_type == "blood_pressure":
                first_value = history_data[0].get("systolic_bp", 0)
                last_value = history_data[-1].get("systolic_bp", 0)
            else:
                first_value = history_data[0].get(vital_type, 0)
                last_value = history_data[-1].get(vital_type, 0)
            
            if abs(last_value - first_value) < 5:
                trend = "stable"
            elif last_value > first_value:
                trend = "increasing"
            else:
                trend = "decreasing"
            
            average = sum(values) / len(values) if values else 0
        
        # Get normal range for the vital type
        normal_range = get_normal_range(vital_type)
        
        # Count out of range values
        out_of_range_count = 0
        for value in values:
            if vital_type == "blood_pressure":
                # Skip blood pressure for simplicity
                pass
            elif value < normal_range["min"] or value > normal_range["max"]:
                out_of_range_count += 1
        
        # Build the response
        trend_data = {
            "patient_id": patient_id,
            "vital_type": vital_type,
            "period": f"Last {days} days",
            "trend": trend,
            "average": average,
            "normal_range": normal_range,
            "out_of_range_count": out_of_range_count,
            "data_points": data_points
        }
        
        return trend_data
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error retrieving vital trends: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving vital trends: {str(e)}"
        )

# Helper function for normal ranges
def get_normal_range(vital_type):
    if vital_type == "heart_rate":
        return {"min": 60, "max": 100}
    elif vital_type == "temperature":
        return {"min": 97.8, "max": 99.1}
    elif vital_type == "blood_pressure":
        return {"systolic": {"min": 90, "max": 120}, "diastolic": {"min": 60, "max": 80}}
    elif vital_type == "oxygen_level":
        return {"min": 95, "max": 100}
    return {"min": 0, "max": 0}

# Add a health check endpoint for the wearable service
@router.get("/health")
async def check_wearable_service_health():
    """Check if the wearable service is running."""
    try:
        health_status = await wearable_service.health_check()
        return health_status
    except Exception as e:
        logger.error(f"Error checking wearable service health: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error connecting to wearable service: {str(e)}"
        )

# Add an endpoint to connect a patient's wearable device
@router.post("/{patient_id}/connect")
async def connect_patient_device(
    patient_id: int,
    device_type: str = "Apple Watch",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Connect a patient's wearable device.
    This simulates connecting a wearable device for a patient and initializes data generation.
    """
    # Check permissions (same as above)
    if current_user.role == "patient":
        patient_result = await db.execute(
            select(Patient).where(Patient.user_id == current_user.id)
        )
        patient = patient_result.scalar_one_or_none()
        
        if not patient or patient.id != patient_id:
            raise HTTPException(
                status_code=403,
                detail="You can only connect your own wearable device"
            )
    elif current_user.role not in ["doctor", "admin", "hospital"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to connect wearable devices"
        )
    
    # Connect the device using the wearable service client
    try:
        connection_result = await wearable_service.connect_patient_device(
            patient_id=patient_id,
            device_type=device_type
        )
        
        return connection_result
    except Exception as e:
        logger.error(f"Error connecting patient device: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error connecting patient device: {str(e)}"
        )