from datetime import datetime
from sqlalchemy import (
    Column, DateTime, String, Date, Integer, Boolean,
    ForeignKey, Text, Numeric, Time, Table,JSON
)
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
from sqlalchemy import Column, String, Integer, Float, Date, Text, DateTime
from sqlalchemy.sql import func


# -------------------- Generate public_id --------------------
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

# Timestamp Mixin 
class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Hospitals 
class Hospital(Base, TimestampMixin):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # public_id = Column(String(150), unique=True, nullable=False, index=True, default=generate_hospital_public_id)
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

    logo_url = Column(String(300), nullable=True)
    registration_certificate = Column(String(300), nullable=False)

    # Relationships
    users = relationship("User", back_populates="hospital", cascade="all, delete-orphan")
    doctors = relationship("Doctor", back_populates="hospital", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="hospital", cascade="all, delete-orphan")
    encounters = relationship("Encounter", back_populates="hospital", cascade="all, delete-orphan")

# Users 
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(200))
    role = Column(String(50), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"))
    is_active = Column(Boolean, default=True)

    hospital = relationship("Hospital", back_populates="users")
    patients = relationship("Patient", back_populates="user", cascade="all, delete-orphan")
    doctors = relationship("Doctor", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")

# Doctors 
class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # public_id = Column(String(150), unique=True, nullable=False, index=True, default=generate_doctor_public_id)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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

    user = relationship("User", back_populates="doctors")
    hospital = relationship("Hospital", back_populates="doctors")
    encounters = relationship("Encounter", back_populates="doctor", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="doctor", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="doctor")
    assignments = relationship("Assignment", back_populates="doctor", cascade="all, delete-orphan")


# Patients 
class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(150), unique=True, nullable=False, index=True, default=generate_public_id)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    dob = Column(Date)
    weight = Column(Numeric(5,2), nullable=False)
    height = Column(Numeric(5,2), nullable=False)
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

    marital_status = Column(String(50))
    weight = Column(Numeric(5, 2), nullable=False)
    height = Column(Numeric(5, 2), nullable=False)

    preferred_contact = Column(String(20), default="phone")

    has_caregiver = Column(Boolean, default=False)
    caregiver_name = Column(String(100))
    caregiver_relationship = Column(String(50))
    caregiver_phone = Column(String(20))
    caregiver_email = Column(String(100))

    smoking_status = Column(String(100), nullable=True)       # e.g., "Current Smoker", "Former Smoker", "Never Smoked"
    alcohol_use = Column(String(100), nullable=True)          # e.g., "Occasional", "Regular", "None"
    diet = Column(String(200), nullable=True)                 # e.g., "Vegetarian", "Vegan", "Non-Vegetarian", "Low Carb"
    exercise_frequency = Column(String(100), nullable=True)   # e.g., "Daily", "Weekly", "Rarely", "Never"

    user = relationship("User", back_populates="patients")
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="patient", cascade="all, delete-orphan")
    vitals = relationship("Vitals", back_populates="patient", cascade="all, delete-orphan")
    encounters = relationship("Encounter", back_populates="patient", cascade="all, delete-orphan")
    patient_insurances = relationship("PatientInsurance", back_populates="patient", cascade="all, delete-orphan")
    pharmacy_insurances = relationship("PatientPharmacyInsurance", back_populates="patient", cascade="all, delete-orphan")
    allergies = relationship("Allergy", back_populates="patient", cascade="all, delete-orphan")
    consents = relationship("PatientConsent", back_populates="patient", cascade="all, delete-orphan", uselist=False)
    assignments = relationship("Assignment", back_populates="patient", cascade="all, delete-orphan")

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
    old_medications = Column(JSON, nullable=True)  # store list of medication dicts
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # relationships
    patient = relationship("Patient", back_populates="assignments")
    doctor = relationship("Doctor", back_populates="assignments")
    
# Allergy 
class Allergy(Base, TimestampMixin):
    __tablename__ = "allergies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)  # e.g. "Peanuts", "Dust", "Penicillin"
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)

    # Relationship
    patient = relationship("Patient", back_populates="allergies")

# PatientConsent 
class PatientConsent(Base, TimestampMixin):
    __tablename__ = "patient_consents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)

    # Consent fields
    hipaa = Column(Boolean, default=False)
    text_messaging = Column(Boolean, default=False)
    marketing = Column(Boolean, default=False)
    copay = Column(Boolean, default=False)
    treatment = Column(Boolean, default=False)
    financial = Column(Boolean, default=False)
    research = Column(Boolean, default=False)

    # Relationship
    patient = relationship("Patient", back_populates="consents")

# Appointments 
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

    patient = relationship("Patient", back_populates="appointments")
    hospital = relationship("Hospital", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    vitals = relationship("Vitals", back_populates="appointment", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="appointment", cascade="all, delete-orphan")

# Medications 
class Medication(Base, TimestampMixin):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="CASCADE"), nullable=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=True)

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

    assignment_id = Column(Integer, ForeignKey("assignments.id"))
    # assignment = relationship("PatientDoctorAssignment", back_populates="medications")

    patient = relationship("Patient", back_populates="medications")
    doctor = relationship("Doctor", back_populates="medications")
    appointment = relationship("Appointment", back_populates="medications")
    encounter = relationship("Encounter", back_populates="medications")

# Encounters
class Encounter(Base, TimestampMixin):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True)
    encounter_date = Column(Date, nullable=False)
    encounter_type = Column(String(50), nullable=False)
    reason_for_visit = Column(String(255))
    diagnosis = Column(Text)
    notes = Column(Text)
    follow_up_date = Column(Date)
    status = Column(String(20), default="open")
    is_lab_test_required = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="encounters")
    doctor = relationship("Doctor", back_populates="encounters")
    hospital = relationship("Hospital", back_populates="encounters")
    vitals = relationship("Vitals", back_populates="encounter", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="encounter", cascade="all, delete-orphan")

# Vitals
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

    user = relationship("User", back_populates="notifications")

# Password Reset Tokens
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

# Password Reset OTPs
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

## insurance master table
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
    
    provider_name = Column(String(100), nullable=False)
    plan_name = Column(String(100), nullable=False)
    plan_type = Column(String(50), nullable=True)
    coverage_percent = Column(Float, nullable=True)
    policy_number = Column(String(50), nullable=False)       
    copay_amount = Column(Float, nullable=True)
    deductible_amount = Column(Float, nullable=True)
    out_of_pocket_max = Column(Float, nullable=True)
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=False)
    status = Column(String(20), default="Active")
    priority = Column(String(20), default="primary")  # "primary" or "secondary"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    insurance_master = relationship("InsuranceMaster")
    patient = relationship("Patient", back_populates="patient_insurances")

# -----------------------
# Pharmacy Insurance Master Table
# -----------------------
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

# Patient Pharmacy Insurance Table
class PatientPharmacyInsurance(Base):
    __tablename__ = "patient_pharmacy_insurance"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    pharmacy_insurance_id = Column(Integer, ForeignKey("pharmacy_insurance_master.id"), nullable=False)
    
    provider_name = Column(String(100), nullable=False)       # autofilled from master
    plan_name = Column(String(100), nullable=False)           # autofilled from master
    policy_number = Column(String(50), nullable=False)        # patient-specific, manual input
    group_number = Column(String(50), nullable=True)          # from master
    formulary_type = Column(String(50), nullable=True)        # from master
    prior_auth_required = Column(Boolean, default=False)      # from master
    standard_copay = Column(Float, nullable=True)            # from master
    deductible_amount = Column(Float, nullable=True)         # from master
    effective_date = Column(Date, nullable=False)            # patient input
    expiry_date = Column(Date, nullable=False)               # patient input
    status = Column(String(20), default="Active")            # Active / Inactive
    priority = Column(String(20), default="primary")         # primary/secondary
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    patient = relationship("Patient", back_populates="pharmacy_insurances")
    pharmacy_master = relationship("PharmacyInsuranceMaster")

## -----------------------
## Lab Master Table

class LabMaster(Base):
    __tablename__ = "lab_master"

    id = Column(Integer, primary_key=True, index=True)
    test_code = Column(String(50), unique=True, nullable=False)  # e.g. "GLUCOSE_FASTING"
    test_name = Column(String(150), nullable=False)               # e.g. "Blood Glucose (Fasting)"
    description = Column(Text, nullable=True)                     # Optional details
    sample_type = Column(String(100), nullable=True)              # e.g. "Blood", "Urine"
    method = Column(String(100), nullable=True)                   # e.g. "Spectrophotometry"
    reference_range = Column(String(100), nullable=True)          # e.g. "70-120 mg/dL"
    unit = Column(String(50), nullable=True)                      # e.g. "mg/dL"
    normal_min = Column(Float, nullable=True)                     # Optional numerical reference
    normal_max = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    price = Column(Float, nullable=False, default=0.0)# Active/inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
# -----------------------
# Lab Orders and Results Tables

class LabOrder(Base):
    __tablename__ = "lab_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="CASCADE"))
    patient_id = Column(Integer, ForeignKey("patients.id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    test_code = Column(String(50))
    test_name = Column(String(100))
    sample_type = Column(String(50))
    status = Column(String(20), default="Pending")  # Pending, Completed
    created_at = Column(DateTime, default=datetime.utcnow)

class LabResult(Base):
    __tablename__ = "lab_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lab_order_id = Column(Integer, ForeignKey("lab_orders.id", ondelete="CASCADE"))
    result_value = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    pdf_url = Column(String(255), nullable=True)  # S3 file URL
    created_at = Column(DateTime, default=datetime.utcnow)


class TreatmentPlanMaster(Base):
    __tablename__ = "treatment_plan_master"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)        
    description = Column(Text, nullable=True)
    status = Column(String(20), default="Active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
