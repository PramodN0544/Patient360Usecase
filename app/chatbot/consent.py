# app/chatbot/consent.py

from app.models import PatientConsent

async def has_patient_consent(patient_id: int, db) -> bool:
    result = await db.execute(
        PatientConsent.__table__.select().where(
            PatientConsent.patient_id == patient_id,
            PatientConsent.hipaa == True
        )
    )
    return result.first() is not None
