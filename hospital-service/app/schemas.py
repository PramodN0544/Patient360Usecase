from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID
from datetime import date, time, datetime


# -----------------------------
# ✅ Hospital Schemas
# -----------------------------
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
    mode_of_consultation: str
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

# Doctor Schemas
class DoctorCreate(BaseModel):
    npi_number: str
    first_name: str
    last_name: str
    email: EmailStr | None = None
    phone: str | None = None
    specialty: str | None = None
    license_number: str | None = None
    qualification: str | None = None
    experience_years: int | None = None
    gender: str | None = None
    availability_days: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    mode_of_consultation: str | None = None


class DoctorOut(DoctorCreate):
    id: UUID
    status: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        orm_mode = True   # ✅ REQUIRED



# Patient (FHIR Patient)

class PatientCreate(BaseModel):
    first_name: str
    last_name: str

    dob: date = None
    gender: str = None

    ssn: str= None 

    phone: str = None
    email: EmailStr = None

    address: str = None
    city: str = None
    state: str = None
    zip_code: str = None
    country: str = None

    # ✅ Extra optional U.S. immigration fields (not in FHIR but allowed)
    citizenship_status: Optional[str] = None
    visa_type: Optional[str] = None

class PatientOut(PatientCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# ✅ Auth Schemas

class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'


class TokenData(BaseModel):
    email: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)
    full_name: Optional[str]
    role: Optional[str] = 'hospital'


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
