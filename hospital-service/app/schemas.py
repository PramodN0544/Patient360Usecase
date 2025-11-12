from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import date, time, datetime

# ================================
# HOSPITAL SCHEMAS
# ================================
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
    # qualification: str
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
    id: int
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

# ================================
# DOCTOR SCHEMAS
# ================================
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
    id: int
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# ================================
# PATIENT SCHEMAS
# ================================
class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    dob: Optional[date] = None
    gender: Optional[str] = None
    ssn: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    citizenship_status: Optional[str] = None
    visa_type: Optional[str] = None
    photo_url: Optional[str]        
    id_proof_document: Optional[str] 
    


class PatientOut(PatientCreate):
    id: int
    public_id: str  # for safe external reference
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# ================================
# AUTH SCHEMAS
# ================================
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)
    full_name: Optional[str]
    role: Optional[str] = "hospital"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    hospital_id: Optional[int]

    class Config:
        orm_mode = True


class SignupResponse(BaseModel):
    user: UserOut
    hospital: HospitalOut

# ================================
# APPOINTMENT SCHEMAS
# ================================
class AppointmentCreate(BaseModel):
    hospital_id: int
    doctor_id: int
    # patient_id: int (will be derived from auth)
    appointment_date: date
    appointment_time: time
    reason: Optional[str] = None
    mode: Optional[str] = "In-person"

    class Config:
        orm_mode = True


class AppointmentResponse(BaseModel):
    id: int
    appointment_id: str
    hospital_id: int
    doctor_id: int
    patient_id: int
    appointment_date: date
    appointment_time: time
    mode: str
    status: str

    class Config:
        orm_mode = True

# ================================
# VITALS SCHEMAS
# ================================
class VitalsCreate(BaseModel):
    height: Optional[float] = None
    weight: Optional[float] = None
    blood_pressure: Optional[str] = None
    heart_rate: Optional[int] = None
    temperature: Optional[float] = None
    respiration_rate: Optional[int] = None
    oxygen_saturation: Optional[int] = None

    class Config:
        orm_mode = True


class VitalsOut(VitalsCreate):
    id: int
    encounter_id: Optional[int] = None
    patient_id: Optional[int] = None
    recorded_at: datetime

    class Config:
        orm_mode = True

# ================================
# MEDICATION SCHEMAS
# ================================
class MedicationCreate(BaseModel):
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    encounter_id: Optional[int] = None

    medication_name: str
    dosage: str
    frequency: str
    route: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    status: Optional[str] = "active"
    notes: Optional[str] = None
    icd_code: Optional[str] = None   
    ndc_code: Optional[str] = None 

    class Config:
        orm_mode = True


class MedicationOut(BaseModel):
    id: int
    patient_id: int
    doctor_id: Optional[int] = None
    encounter_id: Optional[int] = None

    medication_name: str
    dosage: str
    frequency: str
    route: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    status: str
    notes: Optional[str] = None

    class Config:
        orm_mode = True

class EncounterCreate(BaseModel):
    patient_public_id: str  
    doctor_id: Optional[int] = None  
    hospital_id: Optional[int] = None  
    encounter_date: date
    encounter_type: str
    reason_for_visit: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: Optional[str] = "open"

    vitals: Optional[VitalsCreate] = None
    medications: Optional[List[MedicationCreate]] = []

    class Config:
        orm_mode = True



class EncounterOut(BaseModel):
    id: int
    patient_id: int
    doctor_id: int
    hospital_id: int
    encounter_date: date
    encounter_type: str
    reason_for_visit: Optional[str]
    diagnosis: Optional[str]
    notes: Optional[str]
    follow_up_date: Optional[date]
    status: str
    doctor_name: Optional[str]  
    hospital_name: Optional[str] 
    vitals: List[VitalsOut] = []
    medications: List[MedicationOut] = []

    class Config:
        orm_mode = True
