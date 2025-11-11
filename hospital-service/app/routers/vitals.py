from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
from app.database import get_db
from app.models import Vitals, Patient
from app.auth import get_current_user

router = APIRouter(prefix="/vitals", tags=["Vitals"])

# Utility to get patient_id from logged-in user
async def get_patient_id(current_user, db: AsyncSession):
    result = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return patient.id


# CREATE VITAL RECORD
@router.post("/")
async def create_vitals(payload: dict, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient_id = await get_patient_id(current_user, db)
    height = payload.get("height")
    weight = payload.get("weight")

    bmi = round(float(weight) / ((float(height) / 100) ** 2), 2) if height and weight else None

    vitals = Vitals(
        patient_id=patient_id,
        appointment_id=payload.get("appointment_id"),
        encounter_id=payload.get("encounter_id"),
        height=height,
        weight=weight,
        bmi=bmi,
        blood_pressure=payload.get("blood_pressure"),
        heart_rate=payload.get("heart_rate"),
        temperature=payload.get("temperature"),
        respiration_rate=payload.get("respiration_rate"),
        oxygen_saturation=payload.get("oxygen_saturation"),
        recorded_at=datetime.utcnow(),
    )
    db.add(vitals)
    await db.commit()
    await db.refresh(vitals)

    return {"message": "Vitals recorded successfully", "vitals_id": vitals.id, "bmi": bmi}


# UPDATE VITAL RECORD
@router.put("/{vitals_id}")
async def update_vitals(vitals_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    stmt = await db.execute(select(Vitals).where(Vitals.id == vitals_id))
    vitals = stmt.scalar_one_or_none()
    if not vitals:
        raise HTTPException(status_code=404, detail="Vitals not found")

    height = payload.get("height", vitals.height)
    weight = payload.get("weight", vitals.weight)
    bmi = round(float(weight) / ((float(height) / 100) ** 2), 2) if height and weight else vitals.bmi

    for field in ["height", "weight", "blood_pressure", "heart_rate", "temperature", "respiration_rate", "oxygen_saturation"]:
        if payload.get(field) is not None:
            setattr(vitals, field, payload[field])
    vitals.bmi = bmi
    vitals.recorded_at = datetime.utcnow()

    db.add(vitals)
    await db.commit()
    await db.refresh(vitals)
    return {"message": "Vitals updated successfully", "vitals_id": vitals.id, "bmi": bmi}


@router.get("/bmi/category")
async def get_bmi_category(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Return latest BMI value + BMI category of logged-in patient."""
    
    # Get patient using current logged-in user
    result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = result.scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Fetch latest vitals entry with BMI
    vitals_result = await db.execute(
        select(Vitals)
        .where(Vitals.patient_id == patient.id)
        .where(Vitals.bmi.isnot(None))
        .order_by(Vitals.recorded_at.desc())
        .limit(1)
    )

    latest = vitals_result.scalar_one_or_none()
    if not latest:
        return {
            "patient_id": str(patient.id),
            "bmi": None,
            "category": "No BMI data"
        }

    bmi = float(latest.bmi)

    # Determine Category
    if bmi < 18.5:
        category = "Underweight"
    elif 18.5 <= bmi < 25:
        category = "Normal"
    elif 25 <= bmi < 30:
        category = "Overweight"
    else:
        category = "Obese"

    return {
        "patient_id": str(patient.id),
        "bmi": bmi,
        "category": category,
        "recorded_at": latest.recorded_at.strftime("%Y-%m-%d %H:%M:%S")
    }
