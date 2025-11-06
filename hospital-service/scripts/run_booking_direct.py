import asyncio
from datetime import date, time
from app.schemas import AppointmentCreate
from app.routers.appointment import book_appointment
from app.database import AsyncSessionLocal


async def run():
    appt = AppointmentCreate(
        hospital_id="8dbef098-b9f9-41c6-9f09-a6b1e3eee838",
        doctor_id="f87ca70e-553f-41c1-a3df-8d42694ebc84",
        patient_id="caed1062-0cad-4c2d-900e-7b57f7385cc3",
        appointment_date=date(2025,11,10),
        appointment_time=time(9,30),
        reason="Checkup",
        mode="In-person",
    )

    async with AsyncSessionLocal() as session:
        try:
            res = await book_appointment(appt, session)
            print("Booking result:", res)
        except Exception as e:
            print("Booking raised:", type(e), e)


if __name__ == "__main__":
    asyncio.run(run())
