from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import PatientDoctorAssignment, Patient, Doctor
from app.auth import get_current_user

router = APIRouter(prefix="/assignments", tags=["Assignments"])

@router.post("/")
async def assign_doctor_to_patient(patient_id: int, doctor_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    # Only hospital can assign
    if current_user.role != "hospital":
        raise HTTPException(403, "Only hospital can assign doctors to patients")

    # Check doctor exists in this hospital
    doctor = await db.execute(select(Doctor).where(Doctor.id == doctor_id, Doctor.hospital_id == current_user.hospital_id))
    doctor = doctor.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Doctor not found in your hospital")

    # Check patient exists in this hospital
    patient = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = patient.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Assign doctor to patient
    assignment = PatientDoctorAssignment(patient_id=patient.id, doctor_id=doctor.id, hospital_id=current_user.hospital_id)
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    return {"message": "Doctor assigned to patient successfully", "assignment_id": assignment.id}
