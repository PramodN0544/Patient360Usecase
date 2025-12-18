from datetime import datetime
from sqlalchemy import (
    Column, DateTime, String, Date, Integer, Boolean,
    ForeignKey, Text, Numeric, Time, Table, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship, backref
from app.database import Base
import uuid
from sqlalchemy import Column, String, Integer, Float, Date, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ARRAY

def generate_public_id(context):
    instance = context.current_parameters
    first = instance.get("first_name", "unknown").lower()
    last = instance.get("last_name", "unknown").lower()
    return f"{first}_{last}_{uuid.uuid4().hex[:8]}"

def generate_doctor_public_id(context):
    instance = context.current_parameters
    first = instance.get("first_name", "unknown").lower()
    last = instance.get("last_name", "unknown").lower()
    return f"doc_{first}_{last}_{uuid.uuid4().hex[:8]}"

def generate_hospital_public_id(context):
    instance = context.current_parameters
    name = instance.get("name", "hospital").lower().replace(" ", "_")
    return f"hosp_{name}_{uuid.uuid4().hex[:8]}"

class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Hospital(Base, TimestampMixin):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    registration_no = Column(String(100))
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(50), default="USA")
    specialty = Column(String(100))
    license_number = Column(String(100), unique=True, nullable=False)
    experience_years = Column(Integer)
    availability_days = Column(String(200))
    start_time = Column(Time)
    end_time = Column(Time)
    consultation_fee = Column(Numeric(10,2))
    website = Column(String(200))
    status = Column(String(20), default="active")
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    logo_url = Column(String(300), nullable=True)
    registration_certificate = Column(String(300), nullable=False)

    users = relationship("User", back_populates="hospital")
    doctors = relationship("Doctor", back_populates="hospital")
    appointments = relationship("Appointment", back_populates="hospital")   
    encounters = relationship("Encounter", back_populates="hospital")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(200))
    role = Column(String(50), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"))
    is_active = Column(Boolean, default=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    hospital = relationship("Hospital", back_populates="users")
    patients = relationship("Patient", back_populates="user")
    doctors = relationship("Doctor", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user")

class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(150), unique=True, nullable=False, index=True, default=generate_doctor_public_id)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"))
    npi_number = Column(String(100), unique=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    specialty = Column(String(100))
    license_number = Column(String(100), unique=True, nullable=False)
    qualification = Column(String(200))
    experience_years = Column(Integer)
    gender = Column(String(20))
    availability_days = Column(String(200))
    start_time = Column(Time)
    end_time = Column(Time)
    mode_of_consultation = Column(String(50))
    status = Column(String(20), default="Active")

    license_url  = Column(String(300), nullable=True)
    license_document = Column(String(300), nullable=False)

    is_active = Column(Boolean, default=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="doctors")
    hospital = relationship("Hospital", back_populates="doctors")
    encounters = relationship("Encounter", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    assignments = relationship("Assignment", back_populates="doctor")
    medications = relationship("Medication", back_populates="doctor")
   
class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(150), unique=True, nullable=False, index=True, default=generate_public_id)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    dob = Column(Date)
    age = Column(Integer, nullable=True)  # Added age field to store calculated age
    gender = Column(String(20), index=True)
    ssn = Column(String(100), unique=True, index=True)
    phone = Column(String(20), unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(50), nullable=False)
    citizenship_status = Column(String(50))
    visa_type = Column(String(50))

    photo_url  = Column(String(300), nullable=True)  
    id_proof_document = Column(String(300), nullable=False)  

    is_active = Column(Boolean, default=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    marital_status = Column(String(50))
    weight = Column(Numeric(5, 2), nullable=False)
    height = Column(Numeric(5, 2), nullable=False)

    preferred_contact = Column(String(20), default="phone")
    is_insured = Column(Boolean, default=False)
    insurance_status = Column(String(20), default="Self-Pay")

    has_caregiver = Column(Boolean, default=False)
    caregiver_name = Column(String(100))
    caregiver_relationship = Column(String(50))
    caregiver_phone = Column(String(20))
    caregiver_email = Column(String(100))

    smoking_status = Column(String(100), nullable=True)       
    alcohol_use = Column(String(100), nullable=True)          
    diet = Column(String(200), nullable=True)                 
    exercise_frequency = Column(String(100), nullable=True)   

    middle_name = Column(String(100), nullable=True)
    suffix = Column(String(20), nullable=True)  
    mrn = Column(String(50), unique=True, index=True)  
    preferred_language = Column(String(50), nullable=True)
    race = Column(String(50), nullable=True)
    ethnicity = Column(String(50), nullable=True)
    interpreter_required = Column(Boolean, default=False)
    alternate_phone = Column(String(20), nullable=True)
    pcp_name = Column(String(100), nullable=True)
    pcp_npi = Column(String(20), nullable=True)
    pcp_phone = Column(String(20), nullable=True)

    preferred_communication = Column(String(20), nullable=True)

    emergency_contact_name = Column(String(100), nullable=True)
    emergency_contact_relationship = Column(String(50), nullable=True)
    emergency_phone = Column(String(20), nullable=True)
    emergency_alternate_phone = Column(String(20), nullable=True)

    pcp_facility = Column(String(150), nullable=True)

    preferred_pharmacy_name = Column(String(150), nullable=True)
    preferred_pharmacy_address = Column(Text, nullable=True)
    preferred_pharmacy_phone = Column(String(20), nullable=True)

    phone_verified = Column(Boolean, default=False)
    phone_verified_at = Column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="patients", lazy="selectin")
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    medications = relationship("Medication", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    vitals = relationship("Vitals", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    encounters = relationship("Encounter", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    patient_insurances = relationship("PatientInsurance", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    pharmacy_insurances = relationship("PatientPharmacyInsurance", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    allergies = relationship("Allergy", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    consents = relationship("PatientConsent", back_populates="patient", cascade="all, delete-orphan", lazy="selectin", uselist=False)
    assignments = relationship("Assignment", back_populates="patient", cascade="all, delete-orphan", lazy="selectin")
    
class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    treatment_plan_id = Column(Integer, ForeignKey("treatment_plan_master.id"), nullable=True)
    specialty = Column(String, nullable=True)
    doctor_category = Column(String, nullable=True)
    medical_history = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    old_medications = Column(JSON, nullable=True)  
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    patient = relationship("Patient", back_populates="assignments")
    doctor = relationship("Doctor", back_populates="assignments")
    
class Allergy(Base, TimestampMixin):
    
    __tablename__ = "allergies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)  
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    patient = relationship("Patient", back_populates="allergies")

class PatientConsent(Base, TimestampMixin):
    __tablename__ = "patient_consents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    hipaa = Column(Boolean, default=False)
    text_messaging = Column(Boolean, default=False)
    marketing = Column(Boolean, default=False)
    copay = Column(Boolean, default=False)
    treatment = Column(Boolean, default=False)
    financial = Column(Boolean, default=False)
    research = Column(Boolean, default=False)
    patient = relationship("Patient", back_populates="consents")

class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(String(100), unique=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    reason = Column(String(300))
    mode = Column(String(50), default="In-person")
    status = Column(String(50), default="Scheduled")
    reminders_sent = Column(ARRAY(String), default=[])  
    patient = relationship("Patient", back_populates="appointments")
    hospital = relationship("Hospital", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    vitals = relationship("Vitals", back_populates="appointment", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="appointment", cascade="all, delete-orphan")


class Medication(Base, TimestampMixin):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="CASCADE"), nullable=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True)
    icd_code = Column(String(50), nullable=True)  # Changed from foreign key to direct string
    medication_name = Column(String(200), nullable=False)
    dosage = Column(String(100), nullable=False)
    frequency = Column(String(100), nullable=False)
    route = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(String(50), default="active")
    notes = Column(Text, nullable=True)
    icd_code = Column(String(20), nullable=True)
    ndc_code = Column(String(50), nullable=True)
    reminder_times = Column(ARRAY(Time), nullable=True)
    patient = relationship("Patient", back_populates="medications")
    doctor = relationship("Doctor", back_populates="medications")
    appointment = relationship("Appointment", back_populates="medications")
    encounter = relationship("Encounter", back_populates="medications")


class Vitals(Base, TimestampMixin):
    __tablename__ = "vitals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True)
    height = Column(Numeric(5,2), nullable=True)
    weight = Column(Numeric(5,2), nullable=True)
    bmi = Column(Numeric(5,2), nullable=True)
    blood_pressure = Column(String(20), nullable=True)
    heart_rate = Column(Integer, nullable=True)
    temperature = Column(Numeric(5,2), nullable=True)
    respiration_rate = Column(Integer, nullable=True)
    oxygen_saturation = Column(Integer, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="vitals")
    appointment = relationship("Appointment", back_populates="vitals")
    encounter = relationship("Encounter", back_populates="vitals")

class Encounter(Base, TimestampMixin):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    patient_public_id = Column(String(150), nullable=False)
    previous_encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True)
    encounter_date = Column(Date, nullable=False)
    encounter_type = Column(String(50), nullable=False)
    primary_icd_code = Column(String(50), nullable=True)  # This is the only field needed for ICD codes, stores the code directly
    reason_for_visit = Column(String(255))
    diagnosis = Column(Text)
    notes = Column(Text)
    follow_up_date = Column(Date)
    status = Column(String(20), default="pending")
    is_lab_test_required = Column(Boolean, default=False)
    documents = Column(ARRAY(String), nullable=True)
    # primary_icd_code_value column removed as it's redundant with primary_icd_code

    patient = relationship("Patient", back_populates="encounters")
    doctor = relationship("Doctor", back_populates="encounters")
    hospital = relationship("Hospital", back_populates="encounters")
    vitals = relationship("Vitals", back_populates="encounter", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="encounter", cascade="all, delete-orphan")
    previous_encounter = relationship(
        "Encounter", 
        remote_side=[id],
        backref=backref("continuations", lazy="selectin"), 
        foreign_keys=[previous_encounter_id]
    )
    lab_orders = relationship(
        "LabOrder",
        backref="encounter",
        cascade="all, delete-orphan",
        lazy="joined"
    )
    # icd_codes relationship removed as EncounterIcdCode table no longer exists
    # primary_icd_code relationship removed as it's now a direct string column

class EncounterHistory(Base):
    __tablename__ = "encounter_history"
    
    id = Column(Integer, primary_key=True, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False)
    status = Column(String(50), nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"))
    notes = Column(Text)  # Optional: track what changed
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    encounter = relationship("Encounter", backref="history")
    updater = relationship("User")
    
# Notifications
class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    desc = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)
    status = Column(String(50), default="unread")
    data_id = Column(String(200), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    reminder_type = Column(String(50), nullable=True)  
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=True)

    user = relationship("User", back_populates="notifications")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    otp = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="password_reset_tokens")

    def is_expired(self):
        return datetime.utcnow() > self.expires_at


password_reset_otps_table = Table(
    "password_reset_otps",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("otp", String(6), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("used", Boolean, default=False),
    Column("created_at", DateTime, default=datetime.utcnow)
)

class InsuranceMaster(Base):
    __tablename__ = "insurance_master"

    id = Column(Integer, primary_key=True, index=True)
    provider_name = Column(String(100), nullable=False)         # e.g. "Blue Cross Blue Shield"
    plan_name = Column(String(100), nullable=False)              # e.g. "Silver PPO Plan"
    plan_type = Column(String(50), nullable=True)                # e.g. "PPO", "HMO", "EPO"
    coverage_percent = Column(Float, nullable=True)              # e.g. 80.0
    copay_amount = Column(Float, nullable=True)                  # e.g. 20.0
    deductible_amount = Column(Float, nullable=True)             # e.g. 1000.0
    out_of_pocket_max = Column(Float, nullable=True)             # e.g. 6000.0
    effective_date = Column(Date, nullable=True)                 # e.g. 2025-01-01
    expiry_date = Column(Date, nullable=True)                    # e.g. 2025-12-31
    description = Column(Text, nullable=True)                    # Notes about coverage
    status = Column(String(20), default="Active")                # Active / Inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now())

##  Patient Insurance Table
class PatientInsurance(Base):
    __tablename__ = "patient_insurance"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign key to patient
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    
    # Foreign key to insurance master
    insurance_id = Column(Integer, ForeignKey("insurance_master.id", ondelete="CASCADE"), nullable=False)
    benefits_verified = Column(Boolean, default=False)
    insurance_type = Column(String(20), default="primary")

    provider_name = Column(String(100), nullable=False)
    plan_name = Column(String(100), nullable=False)
    plan_type = Column(String(50), nullable=True)
    coverage_percent = Column(Float, nullable=True)
    policy_number = Column(String(50), nullable=False)  
    copay_amount = Column(Float, nullable=True)
    deductible_amount = Column(Float, nullable=True)
    out_of_pocket_max = Column(Float, nullable=True)
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)
    status = Column(String(20), default="Active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    group_number = Column(String(50), nullable=True)
    subscriber_name = Column(String(100), nullable=False)
    subscriber_relationship = Column(String(50), nullable=False)  
    subscriber_dob = Column(Date, nullable=True)

    payer_phone = Column(String(20), nullable=True)

    insurance_master = relationship("InsuranceMaster")
    patient = relationship("Patient", back_populates="patient_insurances")

class PharmacyInsuranceMaster(Base):
    __tablename__ = "pharmacy_insurance_master"

    id = Column(Integer, primary_key=True, index=True)
    provider_name = Column(String(100), nullable=False)        # e.g., "CVS Caremark"
    plan_name = Column(String(100), nullable=False)            # e.g., "Standard Rx Plan"
    group_number = Column(String(50), nullable=True)           # plan-level group number
    formulary_type = Column(String(50), nullable=True)         # e.g., "Formulary", "Non-Formulary"
    prior_auth_required = Column(Boolean, default=False)       # True/False
    standard_copay = Column(Float, nullable=True)             # optional, default copay amount
    deductible_amount = Column(Float, nullable=True)
    status = Column(String(20), default="Active")             # Active / Inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PatientPharmacyInsurance(Base):
    __tablename__ = "patient_pharmacy_insurance"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    pharmacy_insurance_id = Column(Integer, ForeignKey("pharmacy_insurance_master.id"), nullable=False)
    
    provider_name = Column(String(100), nullable=False)       
    plan_name = Column(String(100), nullable=False)          
    policy_number = Column(String(50), nullable=False)       
    bin_number = Column(String(50), nullable=True)
    pcn_number = Column(String(50), nullable=True)
    group_number = Column(String(50), nullable=True)          # from master
    formulary_type = Column(String(50), nullable=True)        # from master
    prior_auth_required = Column(Boolean, default=False)      # from master
    standard_copay = Column(Float, nullable=True)            # from master
    deductible_amount = Column(Float, nullable=True)         # from master
    effective_date = Column(Date, nullable=False)  
    expiry_date = Column(Date, nullable=True)             
    status = Column(String(20), default="Active")            # Active / Inactive

    insurance_type = Column(String(20), default="primary")

    benefits_verified = Column(Boolean, default=False)

    pharmacy_name = Column(String(150), nullable=True)
    pharmacy_phone = Column(String(20), nullable=True)
    pharmacy_address = Column(String(200), nullable=True)
    is_preferred = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    patient = relationship("Patient", back_populates="pharmacy_insurances")
    pharmacy_master = relationship("PharmacyInsuranceMaster")

class LabMaster(Base):
    __tablename__ = "lab_master"

    id = Column(Integer, primary_key=True, index=True)
    test_code = Column(String(50), unique=True, nullable=False)  
    test_name = Column(String(150), nullable=False)               
    description = Column(Text, nullable=True)                     
    sample_type = Column(String(100), nullable=True)             
    method = Column(String(100), nullable=True)                  
    reference_range = Column(String(100), nullable=True)         
    unit = Column(String(50), nullable=True)                      
    normal_min = Column(Float, nullable=True)                  
    normal_max = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    price = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class LabOrder(Base):
    __tablename__ = "lab_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="CASCADE"))
    patient_id = Column(Integer, ForeignKey("patients.id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    test_code = Column(String(50))
    test_name = Column(String(100))
    sample_type = Column(String(50))
    status = Column(String(20), default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LabResult(Base):
    __tablename__ = "lab_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lab_order_id = Column(Integer, ForeignKey("lab_orders.id", ondelete="CASCADE"))
    result_value = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    file_key = Column(String(512), nullable=True)  
    created_at = Column(DateTime, default=datetime.utcnow)
    lab_order = relationship("LabOrder", backref="lab_results", lazy="joined")

class TreatmentPlanMaster(Base):
    __tablename__ = "treatment_plan_master"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)        
    description = Column(Text, nullable=True)
    status = Column(String(20), default="Active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Chat(Base, TimestampMixin):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True)
    
    patient = relationship("Patient", backref="chats_as_patient")
    doctor = relationship("Doctor", backref="chats_as_doctor")
    encounter = relationship("Encounter", backref="chats")

    messages = relationship(
        "ChatMessage",
        back_populates="chat",
        cascade="all, delete-orphan"
    )

    user_statuses = relationship(
        "ChatUserStatus",
        back_populates="chat",
        cascade="all, delete-orphan"
    )
    
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)

    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)

    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    _is_read = Column("is_read", Boolean, default=False)  
    _sender_type = Column("sender_type", String(20), nullable=True)  

    chat = relationship("Chat", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    doctor = relationship("Doctor", foreign_keys=[doctor_id])
    patient = relationship("Patient", foreign_keys=[patient_id])

    @property
    def sent_at(self):
        return self.timestamp

    @property
    def sender_type(self):
        if self._sender_type:
            return self._sender_type
        return "patient" if self.sender_id == self.patient_id else "doctor"
    
    @sender_type.setter
    def sender_type(self, value):
        self._sender_type = value

    @property
    def is_read(self):
        return self._is_read
    
    @is_read.setter
    def is_read(self, value):
        self._is_read = value

class ChatUserStatus(Base):
    __tablename__ = "chat_user_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    is_typing = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow)
    online = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chat = relationship("Chat", back_populates="user_statuses")
    user = relationship("User")

class PatientTask(Base, TimestampMixin):
    __tablename__ = "patient_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)

    priority = Column(String(20), default="normal")   
    status = Column(String(20), default="pending")    

    patient = relationship("Patient", backref="tasks")

# Care Plan Feature - New Models

class ConditionGroup(Base, TimestampMixin):
   __tablename__ = "condition_groups"

   condition_group_id = Column(Integer, primary_key=True, autoincrement=True)
   name = Column(String(200), nullable=False)
   description = Column(Text)
   
   # Relationships
   icd_codes = relationship("ICDConditionMap", back_populates="condition_group")
   guidelines = relationship("ConditionGuidelineMap", back_populates="condition_group")
   care_plans = relationship("CarePlan", back_populates="condition_group")

class ICDConditionMap(Base):
   __tablename__ = "icd_condition_map"

   id = Column(Integer, primary_key=True, autoincrement=True)
   icd_code = Column(String(50), nullable=False)
   condition_group_id = Column(Integer, ForeignKey("condition_groups.condition_group_id"), nullable=False)
   is_pattern = Column(Boolean, default=False)
   description = Column(Text, nullable=True)  # Added description column
   
   # Relationships
   condition_group = relationship("ConditionGroup", back_populates="icd_codes")

class GuidelineMaster(Base, TimestampMixin):
   __tablename__ = "guideline_master"

   guideline_id = Column(Integer, primary_key=True, autoincrement=True)
   name = Column(String(200))
   guideline_number = Column(String(50))  # e.g., NG17
   url = Column(Text)
   version = Column(String(50))
   description = Column(Text)
   
   # Relationships
   conditions = relationship("ConditionGuidelineMap", back_populates="guideline")
   rules = relationship("GuidelineRules", back_populates="guideline")

class ConditionGuidelineMap(Base):
   __tablename__ = "condition_guideline_map"

   id = Column(Integer, primary_key=True, autoincrement=True)
   condition_group_id = Column(Integer, ForeignKey("condition_groups.condition_group_id"), nullable=False)
   guideline_id = Column(Integer, ForeignKey("guideline_master.guideline_id"), nullable=False)
   
   # Relationships
   condition_group = relationship("ConditionGroup", back_populates="guidelines")
   guideline = relationship("GuidelineMaster", back_populates="conditions")

class GuidelineRules(Base, TimestampMixin):
   __tablename__ = "guideline_rules"

   id = Column(Integer, primary_key=True, autoincrement=True)
   guideline_id = Column(Integer, ForeignKey("guideline_master.guideline_id"), nullable=False)
   rules_json = Column(JSON, nullable=False)
   version = Column(String(50))
   
   # Relationships
   guideline = relationship("GuidelineMaster", back_populates="rules")

class CarePlan(Base, TimestampMixin):
   __tablename__ = "care_plans"

   careplan_id = Column(Integer, primary_key=True, autoincrement=True)
   patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
   encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False)
   condition_group_id = Column(Integer, ForeignKey("condition_groups.condition_group_id"), nullable=False)
   status = Column(String(20), default="proposed")  # proposed, active, completed
   patient_friendly_summary = Column(Text)
   clinician_summary = Column(Text)
   plan_metadata = Column(JSON)
   
   # Relationships
   patient = relationship("Patient", backref="care_plans")
   encounter = relationship("Encounter", backref="care_plans")
   condition_group = relationship("ConditionGroup", back_populates="care_plans")
   tasks = relationship("CarePlanTask", back_populates="care_plan", cascade="all, delete-orphan")
   audit_logs = relationship("CarePlanAudit", back_populates="care_plan", cascade="all, delete-orphan")

class CarePlanTask(Base, TimestampMixin):
   __tablename__ = "care_plan_tasks"

   task_id = Column(Integer, primary_key=True, autoincrement=True)
   careplan_id = Column(Integer, ForeignKey("care_plans.careplan_id"), nullable=False)
   type = Column(String(50))  # lab_test, monitoring, education, visit, screening, referral
   title = Column(String(200), nullable=False)
   description = Column(Text)
   frequency = Column(String(50))
   due_date = Column(Date)
   assigned_to = Column(String(50))  # patient or provider
   requires_clinician_review = Column(Boolean, default=False)
   status = Column(String(20), default="pending")  # pending, in_progress, completed, cancelled
   
   # Relationships
   care_plan = relationship("CarePlan", back_populates="tasks")

class CarePlanAudit(Base):
   __tablename__ = "care_plan_audit"

   audit_id = Column(Integer, primary_key=True, autoincrement=True)
   careplan_id = Column(Integer, ForeignKey("care_plans.careplan_id"), nullable=False)
   action = Column(String(50))
   actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
   notes = Column(Text)
   timestamp = Column(DateTime, default=datetime.utcnow)
   
   # Relationships
   care_plan = relationship("CarePlan", back_populates="audit_logs")
   actor = relationship("User")
# IcdCodeMaster and EncounterIcdCode tables have been removed
# Their functionality is now handled by the ICDConditionMap table with the added description column
