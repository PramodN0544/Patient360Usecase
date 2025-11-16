from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from typing import List
from datetime import date
from app.database import get_db
from app.models import Encounter, Doctor, Patient, Vitals, Medication, Assignment
from app.schemas import EncounterCreate, EncounterOut, EncounterUpdate
from app.auth import get_current_user

router = APIRouter(prefix="/encounters", tags=["Encounters"])


# ===============================
# CREATE ENCOUNTER
# ===============================
@router.post("/", response_model=EncounterOut)
async def create_encounter(
    encounter_in: EncounterCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):

    # -------------------------------
    # Determine doctor
    # -------------------------------
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if current_user.role == "hospital":
        # Hospital creating encounter → doctor must be passed
        doctor_id = encounter_in.doctor_id
        doctor_result = await db.execute(
            select(Doctor).where(
                Doctor.id == doctor_id,
                Doctor.hospital_id == current_user.hospital_id
            )
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor not found in your hospital")

    elif not doctor:
        raise HTTPException(403, "Only doctors or hospitals can create encounters")

    # -------------------------------
    # Fetch patient by public_id
    # -------------------------------
    patient_result = await db.execute(
        select(Patient).where(Patient.public_id == encounter_in.patient_public_id)
    )
    patient = patient_result.scalar_one_or_none()

    if not patient:
        raise HTTPException(404, "Patient not found")

    # -------------------------------
    # Check doctor is assigned to patient (Assignment table)
    # -------------------------------
    assignment_result = await db.execute(
        select(Assignment).where(
            Assignment.patient_id == patient.id,
            Assignment.doctor_id == doctor.id
        )
    )
    assignment = assignment_result.scalar_one_or_none()

    if not assignment:
        raise HTTPException(403, "Doctor is not assigned to this patient")

    encounter_date_today = encounter_in.encounter_date or date.today()
    # -------------------------------
    # Create encounter
    # -------------------------------
    new_encounter = Encounter(
        patient_id=patient.id,
        doctor_id=doctor.id,
        hospital_id=doctor.hospital_id,
        encounter_date=encounter_date_today,
        encounter_type=encounter_in.encounter_type,
        reason_for_visit=encounter_in.reason_for_visit,
        diagnosis=encounter_in.diagnosis,
        notes=encounter_in.notes,
        follow_up_date=encounter_in.follow_up_date,
        is_lab_test_required=encounter_in.is_lab_test_required,
        status="open"
    )
    db.add(new_encounter)
    await db.flush()  # get encounter ID

    # -------------------------------
    # Save vitals
    # -------------------------------
    if encounter_in.vitals:
        v = encounter_in.vitals
        bmi = None
        if v.height and v.weight:
            height_m = v.height / 100
            bmi = round(v.weight / (height_m ** 2), 2)

        vitals_obj = Vitals(
            patient_id=patient.id,
            encounter_id=new_encounter.id,
            height=v.height,
            weight=v.weight,
            bmi=bmi,
            blood_pressure=v.blood_pressure,
            heart_rate=v.heart_rate,
            temperature=v.temperature,
            respiration_rate=v.respiration_rate,
            oxygen_saturation=v.oxygen_saturation,
        )
        db.add(vitals_obj)

    # -------------------------------
    # Save medications
    # -------------------------------
    if encounter_in.medications:
        for m in encounter_in.medications:
            med_obj = Medication(
                patient_id=patient.id,
                doctor_id=doctor.id,
                encounter_id=new_encounter.id,
                medication_name=m.medication_name,
                icd_code=m.icd_code,
                ndc_code=m.ndc_code,
                dosage=m.dosage,
                frequency=m.frequency,
                route=m.route,
                start_date=m.start_date,
                end_date=m.end_date,
                status=m.status or "active",
                notes=m.notes,
            )
            db.add(med_obj)

    await db.commit()
    await db.refresh(new_encounter)

    # -------------------------------
    # Return encounter with relations
    # -------------------------------
    final_result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            joinedload(Encounter.doctor),
            joinedload(Encounter.hospital)
        )
        .where(Encounter.id == new_encounter.id)
    )

    encounter = final_result.scalar_one()
    encounter_out = EncounterOut.from_orm(encounter)

    encounter_out.doctor_name = (
        f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
        if encounter.doctor else None
    )
    encounter_out.hospital_name = encounter.hospital.name if encounter.hospital else None

    return encounter_out





# ===============================
# GET PATIENT'S ENCOUNTERS
# ===============================


@router.get("/patient/{patient_id}", response_model=List[EncounterOut])
async def get_patient_encounters(
    patient_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Only doctors or hospitals can fetch encounters
    if current_user.role not in ["doctor", "hospital"]:
        raise HTTPException(403, "Not permitted")

    # Check doctor assignment
    if current_user.role == "doctor":
        doctor_result = await db.execute(select(models.Doctor).where(models.Doctor.user_id == current_user.id))
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            raise HTTPException(404, "Doctor record not found")

        assignment_result = await db.execute(
            select(models.Assignment).where(
                models.Assignment.patient_id == patient_id,
                models.Assignment.doctor_id == doctor.id
            )
        )
        assignment = assignment_result.scalar_one_or_none()
        if not assignment:
            raise HTTPException(403, "Doctor is not assigned to this patient")

    # Fetch encounters
    result = await db.execute(
        select(Encounter)
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.encounter_date.desc())
    )
    encounters = result.scalars().all()
    return [EncounterOut.from_orm(e) for e in encounters]

@router.get("/patient", response_model=List[EncounterOut])
async def get_my_encounters(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.scalar_one_or_none()

    if not patient:
        raise HTTPException(403, "Only patients can view encounters")

    result = await db.execute(
        select(Encounter)
        .options(
            joinedload(Encounter.vitals),
            joinedload(Encounter.medications),
            joinedload(Encounter.doctor),
            joinedload(Encounter.hospital)
        )
        .where(Encounter.patient_id == patient.id)
        .order_by(Encounter.encounter_date.desc())
    )
    encounters = result.unique().scalars().all()

    response = []
    for e in encounters:
        encounter_data = EncounterOut.from_orm(e)
        encounter_data.doctor_name = (
    f"{e.doctor.first_name} {e.doctor.last_name}" if e.doctor else None
)
        encounter_data.hospital_name = e.hospital.name if e.hospital else None
        response.append(encounter_data)

    return response

# ===============================
# GET SINGLE ENCOUNTER
# ===============================
@router.get("/{encounter_id}", response_model=EncounterOut)
async def get_encounter(
    encounter_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Encounter)
        .options(
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications),
            joinedload(Encounter.doctor),
            joinedload(Encounter.hospital)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(404, "Encounter not found")

    # If patient → ensure they own the encounter
    patient_result = await db.execute(
        select(Patient).where(Patient.user_id == current_user.id)
    )
    patient = patient_result.scalar_one_or_none()
    if patient and encounter.patient_id != patient.id:
        raise HTTPException(403, "You can only see your own encounters")

    encounter_out = EncounterOut.from_orm(encounter)
    # doctor full name
    if encounter.doctor:
        encounter_out.doctor_name = f"{encounter.doctor.first_name} {encounter.doctor.last_name}"
    else:
        encounter_out.doctor_name = None

    # hospital name
    encounter_out.hospital_name = encounter.hospital.name if encounter.hospital else None
    return encounter_out


@router.put("/{encounter_id}", response_model=EncounterOut)
async def update_encounter(
    encounter_id: int,
    encounter_in: EncounterUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Fetch encounter
    result = await db.execute(
        select(Encounter)
        .options(
            joinedload(Encounter.doctor),
            joinedload(Encounter.hospital),
            selectinload(Encounter.vitals),
            selectinload(Encounter.medications)
        )
        .where(Encounter.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    # Only doctor/hospital who created assignment can update
    doctor_result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = doctor_result.scalar_one_or_none()

    if not doctor and current_user.role != "hospital":
        raise HTTPException(status_code=403, detail="Not allowed")

    # UPDATE MAIN FIELDS
    update_data = encounter_in.dict(exclude_unset=True)

    for field, value in update_data.items():
        if field not in ["vitals", "medications"]:
            setattr(encounter, field, value)

    # UPDATE VITALS
    if encounter_in.vitals:
        v = encounter_in.vitals
        vitals_result = await db.execute(
            select(Vitals).where(Vitals.encounter_id == encounter.id)
        )
        vitals = vitals_result.scalar_one_or_none()

        if vitals:
            for f, val in v.dict(exclude_unset=True).items():
                setattr(vitals, f, val)

    # UPDATE MEDICATIONS
    if encounter_in.medications:
        # Delete old meds
        await db.execute(
            Medication.__table__.delete().where(Medication.encounter_id == encounter.id)
        )

        # Insert new meds
        for m in encounter_in.medications:
            new_med = Medication(
                patient_id=encounter.patient_id,
                doctor_id=encounter.doctor_id,
                encounter_id=encounter.id,
                medication_name=m.medication_name,
                dosage=m.dosage,
                frequency=m.frequency,
                route=m.route,
                start_date=m.start_date,
                end_date=m.end_date,
                status=m.status,
                notes=m.notes,
                icd_code=m.icd_code,
                ndc_code=m.ndc_code,
            )
            db.add(new_med)

    await db.commit()
    await db.refresh(encounter)

    return EncounterOut.from_orm(encounter)
