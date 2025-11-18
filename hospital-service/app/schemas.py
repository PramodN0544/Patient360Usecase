from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional,Dict
from datetime import date, time, datetime


# HOSPITAL SCHEMAS
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
    address: str
    zip_code: str
    license_number: str
    website: Optional[str] = None
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

# Allergy Schemas
class AllergyCreate(BaseModel):
    name: str

class AllergyOut(AllergyCreate):
    id: int

    class Config:
        orm_mode = True

# PatientConsent Schemas
class PatientConsentCreate(BaseModel):
    hipaa: bool
    text_messaging: bool
    marketing: Optional[bool] = False
    copay: Optional[bool] = False
    treatment: Optional[bool] = False
    financial: bool
    research: Optional[bool] = False

class PatientConsentOut(PatientConsentCreate):
    id: int

    class Config:
        orm_mode = True

# INSURANCE MASTER SCHEMAS
class InsuranceMasterOut(BaseModel):
    id: int
    provider_name: str
    plan_name: str
    plan_type: Optional[str] = None
    coverage_percent: Optional[float] = None
    copay_amount: Optional[float] = None
    deductible_amount: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    description: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class PharmacyInsuranceMasterOut(BaseModel):
    id: int
    provider_name: str
    plan_name: str
    group_number: Optional[str]
    formulary_type: Optional[str]
    prior_auth_required: bool
    standard_copay: Optional[float]
    deductible_amount: Optional[float]
    status: str
    created_at: datetime

    class Config:
        orm_mode = True
        
# Input schema for POST request
class PatientPharmacyInsuranceCreate(BaseModel):
    pharmacy_insurance_id: int  # Reference to master plan
    policy_number: str          # Patient-specific, manual input
    effective_date: date
    expiry_date: date
    priority: Optional[str] = "primary"  # primary / secondary

# Output schema for GET response
class PatientPharmacyInsuranceOut(BaseModel):
    id: int
    patient_id: int
    pharmacy_insurance_id: int
    provider_name: str
    plan_name: str
    policy_number: str
    group_number: Optional[str]
    formulary_type: Optional[str]
    prior_auth_required: bool
    standard_copay: Optional[float]
    deductible_amount: Optional[float]
    effective_date: date
    expiry_date: date
    status: str
    priority: str
    created_at: datetime

    class Config:
        orm_mode = True  # allows SQLAlchemy models to be returned directly

# Response schema 
class PatientInsuranceOut(BaseModel):
    id: int
    patient_id: int
    insurance_id: int
    provider_name: str
    plan_name: str
    plan_type: Optional[str]
    coverage_percent: Optional[float]
    copay_amount: Optional[float]
    deductible_amount: Optional[float]
    out_of_pocket_max: Optional[float]
    effective_date: date
    expiry_date: date
    status: str
    priority: str
    created_at: datetime

    class Config:
        orm_mode = True

# Create schema
class PatientInsuranceCreate(BaseModel):
    insurance_id: int                     
    effective_date: date
    expiry_date: date
    priority: Optional[str] = "primary" 
    policy_number: str

    class Config:
        orm_mode = True

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
    # New fields
    marital_status: Optional[str] = None
    preferred_contact: Optional[str] = "phone"
    has_caregiver: Optional[bool] = False
    caregiver_name: Optional[str] = None
    caregiver_relationship: Optional[str] = None
    caregiver_phone: Optional[str] = None
    caregiver_email: Optional[str] = None
    smoking_status: Optional[str] = None
    alcohol_use: Optional[str] = None
    diet: Optional[str] = None
    exercise_frequency: Optional[str] = None

    # Related records
    allergies: Optional[List[AllergyCreate]] = []
    consents: Optional[PatientConsentCreate] = None
    patient_insurances: Optional[List[PatientInsuranceCreate]] = []
    pharmacy_insurances: Optional[List[PatientPharmacyInsuranceCreate]] = []
    
    
    
class PatientOut(BaseModel):
    id: int
    public_id: str
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
    marital_status: Optional[str] = None
    preferred_contact: Optional[str] = "phone"
    has_caregiver: Optional[bool] = False
    caregiver_name: Optional[str] = None
    caregiver_relationship: Optional[str] = None
    caregiver_phone: Optional[str] = None
    caregiver_email: Optional[str] = None
    smoking_status: Optional[str] = None
    alcohol_use: Optional[str] = None
    diet: Optional[str] = None
    exercise_frequency: Optional[str] = None
    created_at: Optional[datetime] = None
   
    # ✅ FIXED NESTED OUTPUT RELATIONS
    allergies: List[AllergyOut] = []
    consents: Optional[PatientConsentOut] = None
    patient_insurances: List[PatientInsuranceOut] = []
    pharmacy_insurances: List[PatientPharmacyInsuranceOut] = []
    encounters: List["EncounterOut"] = []
    
    

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
    patient_public_id: Optional[str]  
    doctor_id: Optional[int] = None  
    hospital_id: Optional[int] = None  
    encounter_date: Optional[date]
    encounter_type: str
    reason_for_visit: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: Optional[str] = "open"
    is_lab_test_required: Optional[bool] = False  
    vitals: Optional[VitalsCreate] = None
    medications: Optional[List[MedicationCreate]] = []

    class Config:
        orm_mode = True

class EncounterOut(BaseModel):
    id: int
    patient_public_id: str
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
    is_lab_test_required: Optional[bool] = False  # <

    class Config:
        orm_mode = True
        
class EncounterBase(BaseModel):
    encounter_id: str
    encounter_type: str
    reason: str | None = None
    visit_date: datetime
    provider_name: str | None = None
    notes: str | None = None

    class Config:
        orm_mode = True


class EncounterResponse(BaseModel):
    id: int
    encounter_id: str
    encounter_type: str
    reason: str | None
    visit_date: datetime
    provider_name: str | None
    notes: str | None

    class Config:
        orm_mode = True


class PatientEncounterResponse(EncounterBase):
    id: int
    patient_id: int

class VitalsUpdate(BaseModel):
    height: Optional[float]
    weight: Optional[float]
    blood_pressure: Optional[str]
    heart_rate: Optional[int]
    temperature: Optional[float]
    respiration_rate: Optional[int]
    oxygen_saturation: Optional[int]

class MedicationUpdate(BaseModel):
    medication_name: Optional[str]
    dosage: Optional[str]
    frequency: Optional[str]
    route: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    status: Optional[str]
    notes: Optional[str]
    icd_code: Optional[str]
    ndc_code: Optional[str]

class EncounterUpdate(BaseModel):
    encounter_type: Optional[str]
    reason_for_visit: Optional[str]
    diagnosis: Optional[str]
    notes: Optional[str]
    follow_up_date: Optional[date]
    is_lab_test_required: Optional[bool]
    vitals: Optional[VitalsUpdate]
    medications: Optional[List[MedicationUpdate]]

# INSURANCE MASTER SCHEMAS
class InsuranceMasterOut(BaseModel):
    id: int
    provider_name: str
    plan_name: str
    plan_type: Optional[str] = None
    coverage_percent: Optional[float] = None
    copay_amount: Optional[float] = None
    deductible_amount: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    description: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class PharmacyInsuranceMasterOut(BaseModel):
    id: int
    provider_name: str
    plan_name: str
    group_number: Optional[str]
    formulary_type: Optional[str]
    prior_auth_required: bool
    standard_copay: Optional[float]
    deductible_amount: Optional[float]
    status: str
    created_at: datetime

    class Config:
        orm_mode = True
        
# Input schema for POST request
# ------------------------------
class PatientPharmacyInsuranceCreate(BaseModel):
    patient_id: int
    pharmacy_insurance_id: int  # Reference to master plan
    policy_number: str          # Patient-specific, manual input
    effective_date: date
    expiry_date: date
    priority: Optional[str] = "primary"  # primary / secondary

# ------------------------------
# Output schema for GET response
# ------------------------------
class PatientPharmacyInsuranceOut(BaseModel):
    id: int
    patient_id: int
    pharmacy_insurance_id: int
    provider_name: str
    plan_name: str
    policy_number: str
    group_number: Optional[str]
    formulary_type: Optional[str]
    prior_auth_required: bool
    standard_copay: Optional[float]
    deductible_amount: Optional[float]
    effective_date: date
    expiry_date: date
    status: str
    priority: str
    created_at: datetime

    class Config:
        orm_mode = True  # allows SQLAlchemy models to be returned directly
# -----------------------------
# Response schema (Out)
# -----------------------------
class PatientInsuranceOut(BaseModel):
    id: int
    patient_id: int
    insurance_id: int
    provider_name: str
    plan_name: str
    policy_number: str
    plan_type: Optional[str]
    coverage_percent: Optional[float]
    copay_amount: Optional[float]
    deductible_amount: Optional[float]
    out_of_pocket_max: Optional[float]
    effective_date: date
    expiry_date: date
    status: str
    priority: str
    created_at: datetime

    class Config:
        orm_mode = True


# -----------------------------
# Create schema (input)
# -----------------------------
class PatientInsuranceCreate(BaseModel):
    insurance_id: int                     
    effective_date: date
    expiry_date: date
    priority: Optional[str] = "primary" 
    policy_number: str

    class Config:
        orm_mode = True

class PatientsWithCount(BaseModel):
    total_patients: int
    patients: List[PatientOut]  

    class Config:
        orm_mode = True




# ============================================================
# Schema for test list (dropdown)
# ============================================================
class LabTestCode(BaseModel):
    test_code: str

    class Config:
        orm_mode = True


# ============================================================
# Schema for full test details
# ============================================================
class LabTestDetail(BaseModel):
    test_code: str
    test_name: str
    sample_type: Optional[str] = None
    price: Optional[float] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None

    class Config:
        orm_mode = True
        

class LabOrderCreate(BaseModel):
    test_code: str

class LabOrderResponse(BaseModel):
    id: int
    encounter_id: int
    patient_id: int
    doctor_id: int
    test_code: str
    test_name: Optional[str]
    sample_type: Optional[str]
    status: str

    class Config:
        orm_mode = True

class LabResultCreate(BaseModel):
    lab_order_id: int
    result_value: Optional[str]
    notes: Optional[str]

class LabResultResponse(BaseModel):
    lab_order_id: int
    result_value: Optional[str]
    notes: Optional[str]
    view_url: Optional[str]
    download_url: Optional[str]
    file_key: Optional[str]
    created_at: Optional[datetime]

    class Config:
        orm_mode = True


class LabTestCode(BaseModel):
    test_code: str

class LabTestDetail(BaseModel):
    test_code: str
    test_name: str
    sample_type: Optional[str]
    price: Optional[float]
    unit: Optional[str]
    reference_range: Optional[str]

    class Config:
        orm_mode = True


# -----------------------------
# Base Lab Result Schema
# -----------------------------
class LabResultBase(BaseModel):
    id: int
    test_name: str
    result_value: Optional[str] = None
    result_date: datetime
    file_url: Optional[str] = None
    notes: Optional[str] = None


# -----------------------------
# Patient Dashboard Schema
# -----------------------------
class LabResultPatientResponse(LabResultBase):
    class Config:
        orm_mode = True


# -----------------------------
# Doctor Dashboard Schema
# -----------------------------
class LabResultDoctorResponse(LabResultBase):
    patient_id: int
    encounter_id: int

    class Config:
        orm_mode = True


# -----------------------------
# Hospital Dashboard Schema
# -----------------------------
class LabResultHospitalResponse(LabResultBase):
    patient_id: int
    doctor_id: int
    encounter_id: int
    hospital_id: int

    class Config:
        orm_mode = True

        


class SpecialtyResponse(BaseModel):
    specialty: List[str]

class AssignmentResponse(BaseModel):
    id: int
    message: str

class AssignmentBase(BaseModel):
    public_patient_id: str
    doctor_id: int
    treatment_plan_id: Optional[int] = None
    medical_history: Optional[str] = None
    specialty: Optional[str] = None
    reason: Optional[str] = None
    old_medications: Optional[List[Dict[str, str]]] = []


class DoctorBase(BaseModel):
    first_name: str
    last_name: str
    specialty: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None

class DoctorResponse(DoctorBase):
    id: int
    

class TreatmentPlanBase(BaseModel):
    name: str
    description: Optional[str] = None

class TreatmentPlanResponse(TreatmentPlanBase):
    id: int

    class Config:
        orm_mode = True


# Resolve forward references for Pydantic models defined out-of-order
PatientOut.update_forward_refs()
PatientsWithCount.update_forward_refs() 
        
