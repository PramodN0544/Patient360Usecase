from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID
from datetime import date, time, datetime


# ==============================================================
# ✅ HOSPITAL SCHEMAS
# ==============================================================
class HospitalBase(BaseModel):
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    email: EmailStr
    specialty: str
    license_number: str
    qualification: str
    experience_years: int
    availability_days: str
    start_time: time
    end_time: time
    consultation_fee: float
    # mode_of_consultation: str
    website: Optional[str] = None
    country: Optional[str] = "USA"


class HospitalSignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "hospital"
    hospital: HospitalBase


class HospitalOut(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str
    specialty: str
    city: str
    state: str
    license_number: str
    consultation_fee: float

    class Config:
        orm_mode = True


# ==============================================================
# ✅ DOCTOR SCHEMAS
# ==============================================================
class DoctorCreate(BaseModel):
    npi_number: str
    first_name: str
    last_name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    gender: Optional[str] = None
    availability_days: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    mode_of_consultation: Optional[str] = None


class DoctorOut(DoctorCreate):
    id: UUID
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# ==============================================================
# ✅ PATIENT SCHEMAS
# ==============================================================
class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    dob: Optional[date] = None
    gender: Optional[str] = None
    ssn: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    citizenship_status: Optional[str] = None
    visa_type: Optional[str] = None


class PatientOut(PatientCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# ==============================================================
# ✅ AUTH SCHEMAS
# ==============================================================
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: Optional[str] = None


# Simple JSON login request (optional, for clients that prefer JSON over form data)
class LoginRequest(BaseModel):
    username: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)
    full_name: Optional[str]
    role: Optional[str] = "hospital"


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: str
    hospital_id: Optional[UUID]

    class Config:
        orm_mode = True


class SignupResponse(BaseModel):
    user: UserOut
    hospital: HospitalOut

# Appointment Schemas
# ===============================
class AppointmentCreate(BaseModel):
    hospital_id: UUID
    doctor_id: UUID
    patient_id: UUID
    appointment_date: date
    appointment_time: time
    reason: Optional[str] = None
    mode: Optional[str] = "In-person"

    class Config:
        orm_mode = True


class AppointmentResponse(BaseModel):
    id: UUID
    appointment_id: str
    hospital_id: UUID
    doctor_id: UUID
    patient_id: UUID
    appointment_date: date
    appointment_time: time
    mode: str
    status: str

    class Config:
        orm_mode = True
        
        
class MedicationCreate(BaseModel):
    patient_id: UUID
    doctor_id: Optional[UUID] = None
    appointment_id: Optional[UUID] = None
    medication_name: str
    dosage: str
    frequency: str
    route: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    status: Optional[str] = "active"
    notes: Optional[str] = None

    class Config:
        orm_mode = True


class MedicationOut(MedicationCreate):
    id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True