from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional,Dict
from datetime import date, time, datetime
from typing import Literal
from decimal import Decimal

class LabOrderResponse(BaseModel):
    id: int
    encounter_id: int
    patient_id: int
    doctor_id: int
    test_code: str
    test_name: Optional[str]
    sample_type: Optional[str]
    status: str
    created_at: datetime  
    updated_at: datetime 

    class Config:
        orm_mode = True

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
    experience_years: int
    availability_days: str
    start_time: time
    end_time: time
    consultation_fee: float
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

class AllergyCreate(BaseModel):
    name: str

class AllergyOut(AllergyCreate):
    id: int

    class Config:
        orm_mode = True

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
        
class PatientPharmacyInsuranceCreate(BaseModel):
    id: int = Field(..., alias="pharmacy_insurance_id")

    provider_name: str
    plan_name: str

    policy_number: str
    bin_number: Optional[str] = None
    pcn_number: Optional[str] = None

    effective_date: date 
    expiry_date: Optional[date] = None

    insurance_type: Optional[str] = "primary"

    pharmacy_name: Optional[str] = None
    pharmacy_phone: Optional[str] = None
    pharmacy_address: Optional[str] = None
    is_preferred: Optional[bool] = True

    benefits_verified: Optional[bool] = False

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
        extra = "ignore"


class PatientPharmacyInsuranceOut(BaseModel):
    id: int
    patient_id: int
    pharmacy_insurance_id: int

    provider_name: str
    plan_name: str
    policy_number: str

    group_number: Optional[str] = None
    formulary_type: Optional[str] = None
    prior_auth_required: bool

    standard_copay: Optional[float] = None
    deductible_amount: Optional[float] = None

    effective_date: date
    expiry_date: date

    status: str
    priority: str
    pharmacy_name: Optional[str] = None
    pharmacy_phone: Optional[str] = None
    pharmacy_address: Optional[str] = None
    is_preferred: Optional[bool] = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

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

class PatientInsuranceCreate(BaseModel):
    # frontend sends plan.id
    id: int = Field(..., alias="insurance_id")

    provider_name: str
    plan_name: str
    plan_type: Optional[str] = None
    coverage_percent: Optional[float] = None
    policy_number: str
    group_number: Optional[str] = None
    subscriber_name: str
    subscriber_relationship: str
    subscriber_dob: Optional[date] = None
    payer_phone: Optional[str] = None
    effective_date: date
    expiry_date: Optional[date] = None
    insurance_type: Optional[str] = "primary"  
    benefits_verified: Optional[bool] = False   

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
        extra = "ignore"


class PatientCreate(BaseModel):
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    suffix: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    ssn: Optional[str] = None
    alternate_phone: Optional[str] = None
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

    mrn: Optional[str] = None
    preferred_language: Optional[str] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    interpreter_required: bool = False
    marital_status: Optional[str] = None
    preferred_contact: Optional[str] = "phone"
    has_caregiver: Optional[bool] = False
    caregiver_name: Optional[str] = None
    caregiver_relationship: Optional[str] = None
    caregiver_phone: Optional[str] = None
    caregiver_email: Optional[str] = None
    smoking_status: Optional[str] = None
    pcp_name: Optional[str] = None
    pcp_npi: Optional[str] = None
    pcp_phone: Optional[str] = None
    alcohol_use: Optional[str] = None
    diet: Optional[str] = None
    exercise_frequency: Optional[str] = None

    preferred_communication: Optional[str] = None

    emergency_contact_name: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None    
    emergency_phone: Optional[str] = None
    emergency_alternate_phone: Optional[str] = None

    pcp_facility: Optional[str] = None

    preferred_pharmacy_name: Optional[str] = None
    preferred_pharmacy_address: Optional[str] = None
    preferred_pharmacy_phone: Optional[str] = None
    is_insured: bool = False
    allergies: Optional[List[AllergyCreate]] = []
    consents: Optional[PatientConsentCreate] = None
    patient_insurances: Optional[List[PatientInsuranceCreate]] = []
    pharmacy_insurances: Optional[List[PatientPharmacyInsuranceCreate]] = []
    
class PatientOut(BaseModel):
    id: int
    public_id: str
    user_id: Optional[int] = None
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    suffix: Optional[str] = None
    mrn: Optional[str] = None
    ssn: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    preferred_language: Optional[str] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    interpreter_required: Optional[bool] = False
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    email: Optional[EmailStr] = None
    preferred_contact: Optional[str] = "phone"
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    citizenship_status: Optional[str] = None
    visa_type: Optional[str] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    smoking_status: Optional[str] = None
    alcohol_use: Optional[str] = None
    diet: Optional[str] = None
    exercise_frequency: Optional[str] = None
    has_caregiver: Optional[bool] = False
    caregiver_name: Optional[str] = None
    caregiver_relationship: Optional[str] = None
    caregiver_phone: Optional[str] = None
    caregiver_email: Optional[str] = None
    pcp_name: Optional[str] = None
    pcp_npi: Optional[str] = None
    pcp_phone: Optional[str] = None
    is_insured: Optional[bool] = False
    insurance_status: Optional[str] = "Self-Pay"
    photo_url: Optional[str] = None
    id_proof_document: Optional[str] = None
    is_active: Optional[bool] = True
    deactivated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    allergies: List[AllergyOut] = []
    consents: Optional[PatientConsentOut] = None
    patient_insurances: List[PatientInsuranceOut] = []
    pharmacy_insurances: List[PatientPharmacyInsuranceOut] = []
    encounters: List["EncounterOut"] = []

    class Config:
        orm_mode = True

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

class AppointmentCreate(BaseModel):
    hospital_id: int
    doctor_id: int
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
    created_at: datetime  
    updated_at: datetime 

    class Config:
        orm_mode = True

class LabOrderCreate(BaseModel):
    test_name: str
    priority: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        orm_mode = True

class IcdCodeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    chapter: Optional[str] = None
    subcategory: Optional[str] = None
    is_active: bool = True
    version: str = "ICD-10"

class IcdCodeCreate(IcdCodeBase):
    pass

class IcdCodeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    chapter: Optional[str] = None
    subcategory: Optional[str] = None
    is_active: Optional[bool] = None
    version: Optional[str] = None

class IcdCodeResponse(IcdCodeBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class EncounterIcdCodeBase(BaseModel):
    icd_code_id: int
    is_primary: bool = False
    notes: Optional[str] = None

class EncounterIcdCodeCreate(EncounterIcdCodeBase):
    pass

class EncounterIcdCodeUpdate(BaseModel):
    is_primary: Optional[bool] = None
    notes: Optional[str] = None

class EncounterIcdCodeInDB(EncounterIcdCodeBase):
    id: int
    encounter_id: int
    created_at: datetime
    icd_code: Optional[IcdCodeResponse] = None

    class Config:
        orm_mode = True

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
    
class LabOrderUpdate(BaseModel):
    id: Optional[int] = None
    test_code: str
    test_name:str
    sample_type: Optional[str] = None
    status: Optional[str] = "Ordered"

    class Config:
        orm_mode = True

class EncounterCreate(BaseModel):
    patient_public_id: str
    doctor_id: Optional[int] = None  
    encounter_type: str
    reason_for_visit: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    encounter_date: Optional[date] = None
    follow_up_date: Optional[date] = None
    is_lab_test_required: Optional[bool] = False
    primary_icd_code_id: Optional[int] = None
    icd_codes: Optional[List[EncounterIcdCodeCreate]] = None
    vitals: Optional[VitalsUpdate] = None
    medications: Optional[List[MedicationUpdate]] = None
    previous_encounter_id: Optional[int] = None
    is_continuation: Optional[bool] = False
    documents: Optional[List[str]] = None

    class Config:
        orm_mode = True

class EncounterUpdate(BaseModel):
    encounter_type: Optional[str] = None
    reason_for_visit: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    is_lab_test_required: Optional[bool] = None
    status: Optional[str] = None  
    primary_icd_code_id: Optional[int] = None
    icd_codes: Optional[List[EncounterIcdCodeCreate]] = None
    previous_encounter_id: Optional[int] = None
    is_continuation: Optional[bool] = None
    vitals: Optional[VitalsUpdate] = None
    medications: Optional[List[MedicationUpdate]] = None
    lab_orders: Optional[List[LabOrderUpdate]] = None
    documents: Optional[List[str]] = None

    class Config:
        orm_mode = True

class EncounterOut(BaseModel):
    id: int
    patient_public_id: str
    doctor_id: Optional[int]
    hospital_id: Optional[int]
    encounter_date: date
    encounter_type: str
    reason_for_visit: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: str
    is_lab_test_required: Optional[bool] = False
    documents: Optional[List[str]] = None
    previous_encounter_id: Optional[int] = None
    is_continuation: bool = False
    primary_icd_code_id: Optional[int] = None
    lab_orders: List[LabOrderResponse] = [] 
    doctor_name: Optional[str] = None
    hospital_name: Optional[str] = None
    primary_icd_code: Optional[IcdCodeResponse] = None
    icd_codes: List[EncounterIcdCodeInDB] = []

    class Config:
        orm_mode = True

    class Config:
        orm_mode = True


class EncounterSummary(BaseModel):
    id: int
    patient_public_id: str
    encounter_date: date
    encounter_type: str
    status: str
    doctor_name: Optional[str] = None
    hospital_name: Optional[str] = None
    primary_diagnosis: Optional[str] = None 
    
    class Config:
        orm_mode = True
        
class EncounterBase(BaseModel):
    encounter_id: str
    encounter_type: str
    reason: str | None = None
    visit_date: datetime
    provider_name: str | None = None
    notes: str | None = None
    primary_icd_code_id: Optional[int] = None

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
        orm_mode = True

class PatientInsuranceOut(BaseModel):
    id: int
    patient_id: int
    insurance_id: int

    provider_name: str
    plan_name: str
    plan_type: Optional[str] = None

    policy_number: str
    group_number: Optional[str] = None

    coverage_percent: Optional[float] = None
    copay_amount: Optional[float] = None
    deductible_amount: Optional[float] = None
    out_of_pocket_max: Optional[float] = None

    subscriber_name: Optional[str] = None
    subscriber_relationship: Optional[str] = None
    subscriber_dob: Optional[date] = None

    payer_phone: Optional[str] = None

    effective_date: date
    expiry_date: date

    status: str
    priority: str

    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class PatientsWithCount(BaseModel):
    total_patients: int
    patients: List[PatientOut]  

    class Config:
        orm_mode = True

class LabTestCode(BaseModel):
    test_code: str

    class Config:
        orm_mode = True

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

class LabResultCreate(BaseModel):
    lab_order_id: int
    result_value: Optional[str]
    notes: Optional[str]

class LabResultResponse(BaseModel):
    lab_order_id: int
    patient_public_id: str
    patient_name: str
    test_name: Optional[str]
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

class LabResultBase(BaseModel):
    id: int
    test_name: str
    result_value: Optional[str] = None
    result_date: datetime
    file_url: Optional[str] = None
    notes: Optional[str] = None

class LabResultPatientResponse(LabResultBase):
    class Config:
        orm_mode = True

class LabResultDoctorResponse(LabResultBase):
    patient_id: int
    encounter_id: int

    class Config:
        orm_mode = True
    
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

class ChatMessageBase(BaseModel):
    message: str

class ChatMessageCreate(ChatMessageBase):
    pass

class ChatMessageOut(ChatMessageBase):
    id: int
    chat_id: int
    sender_id: int
    sender_type: str
    is_read: bool
    sent_at: datetime

    class Config:
        orm_mode = True

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = "normal"

class TaskUpdate(BaseModel):
    title: Optional[str]
    description: Optional[str]
    due_date: Optional[date]
    priority: Optional[str]
    status: Optional[str]

class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    due_date: Optional[date]
    priority: str
    status: str
    created_at: Optional[date]

    class Config:
        orm_mode = True

class SendToRecipientRequest(BaseModel):
    recipient_id: int
    message: str
    
class ChatUserStatusBase(BaseModel):
    is_typing: Optional[bool] = False
    online: Optional[bool] = False

class ChatUserStatusUpdate(ChatUserStatusBase):
    pass

class ChatUserStatusOut(ChatUserStatusBase):
    id: int
    chat_id: int
    user_id: int
    last_seen: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class ChatBase(BaseModel):
    patient_id: Optional[int] = None
    doctor_id: Optional[int] = None
    encounter_id: Optional[int] = None

class ChatCreate(ChatBase):
    pass

class ChatOut(ChatBase):
    id: int
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageOut] = []
    
    class Config:
        orm_mode = True

class ChatParticipantInfo(BaseModel):
    id: int
    public_id: str
    name: str
    role: str
    photo_url: Optional[str] = None
    dob: Optional[date] = None  
    gender: Optional[str] = None 
    specialty: Optional[str] = None  
    hospital: Optional[str] = None 
    
class ChatSummary(BaseModel):
    id: int
    patient: ChatParticipantInfo
    doctor: ChatParticipantInfo
    last_message: Optional[ChatMessageOut] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class DoctorBasicInfo(BaseModel):
    id: int
    public_id: Optional[str] = ""
    name: str
    email: Optional[str] = None
    specialty: Optional[str] = None
    role: str = "doctor"
    encounter_id: Optional[int] = None
    photo_url: Optional[str] = None
    
    class Config:
        orm_mode = True

class PatientBasicInfo(BaseModel):
    id: int
    public_id: str
    name: str
    email: Optional[str] = None
    role: str = "patient"
    encounter_id: Optional[int] = None
    photo_url: Optional[str] = None
    
    class Config:
        orm_mode = True
           
PatientOut.update_forward_refs()
PatientsWithCount.update_forward_refs() 
        
class HospitalPatientOut(BaseModel):
    patient_id: int
    patient_name: str | None
    age: int | None = None
    dob: date | None = None
    gender: str | None = None
    phone: str | None = None
    email: str | None
    admission_status: str | None = None
    assigned_doctor: str | None = None
    last_visit_date: datetime | None = None

    mrn: str | None = None
    insurance_status: str | None = None
    diagnosis: str | None = None
    room_bed: str | None = None

    policy_number: str | None = None
    pharma_policy_number: str | None = None

    class Config:
        orm_mode = True

AllowedRoles = Literal["admin", "doctor", "hospital", "patient"]

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)
    phone: str = Field(..., min_length=10)
    full_name: Optional[str] = None
    role: AllowedRoles
    hospital_id: Optional[int] = None


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[AllowedRoles] = None
    hospital_id: Optional[int] = None
    is_active: Optional[bool] = None


class AdminUserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: AllowedRoles
    hospital_id: Optional[int]
    is_active: bool
    created_at: Optional[datetime]

    class Config:
        orm_mode = True

class AppointmentReminder(BaseModel):
    id: int
    user_id: Optional[int] = None
    patient_id: int
    appointment_id: int
    reminder_type: str  
    scheduled_for: Optional[datetime] = None
    status: str  
    title: Optional[str] = None
    desc: Optional[str] = None

    class Config:
        orm_mode = True

class MedicationReminder(BaseModel):
    id: int
    user_id: Optional[int] = None
    patient_id: int
    medication_id: int
    reminder_type: str 
    scheduled_for: Optional[datetime] = None
    status: str 
    title: Optional[str] = None
    desc: Optional[str] = None

    class Config:
        orm_mode = True

class NotificationOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    patient_id: int
    type: Literal["appointment", "medication"]  
    related_id: int  
    reminder_type: str  
    scheduled_for: Optional[datetime] = None
    status: str 
    title: Optional[str] = None
    desc: Optional[str] = None

    class Config:
        orm_mode = True
class HospitalUpdate(BaseModel):
    website: Optional[str] = None
    consultation_fee: Optional[float] = None

class PatientUpdate(BaseModel):
    first_name: Optional[str]
    middle_name: Optional[str]
    last_name: Optional[str]
    suffix: Optional[str]
    phone: Optional[str]
    alternate_phone: Optional[str]
    email: Optional[EmailStr]

    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    photo_url: Optional[str]

    preferred_language: Optional[str]
    race: Optional[str]
    ethnicity: Optional[str]
    interpreter_required: Optional[bool]

    pcp_name: Optional[str]
    pcp_npi: Optional[str]
    pcp_phone: Optional[str]

    marital_status: Optional[str]
    preferred_contact: Optional[str]

    weight: Optional[Decimal]
    height: Optional[Decimal]

    smoking_status: Optional[str]
    alcohol_use: Optional[str]
    diet: Optional[str]
    exercise_frequency: Optional[str]

    has_caregiver: Optional[bool]
    caregiver_name: Optional[str]
    caregiver_relationship: Optional[str]
    caregiver_phone: Optional[str]
    caregiver_email: Optional[str]
class PatientSearchRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    ssn: Optional[str] = None


class PatientSearchOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    dob: Optional[date]
    gender: Optional[str]
    public_id: str
    ssn: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    country: Optional[str]
    citizenship_status: Optional[str]
    visa_type: Optional[str]

    class Config:
        orm_mode = True


class AppointmentListResponse(BaseModel):
    appointments: List[AppointmentResponse]
    total_count: int
    status_counts: Optional[Dict[str, int]] = None
    today_count: Optional[int] = None
    upcoming_count: Optional[int] = None


class RescheduleAppointment(BaseModel):
    new_date: date
    new_time: time
    reason: Optional[str] = None


class AppointmentStats(BaseModel):
    status_counts: Dict[str, int]
    today_count: int
    upcoming_count: int
    total_appointments: int


class AppointmentFilter(BaseModel):
    status: Optional[str] = None
    date_filter: Optional[str] = None
    search: Optional[str] = None
    doctor_id: Optional[int] = None
    patient_id: Optional[int] = None

class AppointmentStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None

class UpcomingAppointmentResponse(BaseModel):
    appointment_id: int
    patient_public_id: str
    patient_name: str
    date: date
    time: time
    reason: str
    status: str

    class Config:
        orm_mode = True

class UpcomingAppointmentsResponse(BaseModel):
    upcoming_appointments: List[UpcomingAppointmentResponse]

class TodayAppointmentsResponse(BaseModel):
    today_appointments: int

class MonthlyVisitResponse(BaseModel):
    month: str
    patient_visits: int

    class Config:
        orm_mode = True

class AppointmentPatientResponse(BaseModel):
    appointment_id: int
    hospital_id: int
    hospital_name: str
    doctor_id: int
    doctor_name: str
    doctor_specialty: str
    appointment_date: str
    appointment_time: Optional[str]
    reason: Optional[str]
    mode: str
    status: str

    class Config:
        orm_mode = True

