from datetime import datetime
import uuid
from sqlalchemy import (
    Column, DateTime, String, Date, Integer, Boolean,
    ForeignKey, Text, Numeric, Time
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Table, Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.database import metadata
from app.database import Base

class TimestampMixin:
    # Use naive UTC datetimes (datetime.utcnow) so they match the
    # TIMESTAMP WITHOUT TIME ZONE columns created earlier.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Hospital(Base, TimestampMixin):
    __tablename__ = "hospitals"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))

    # Basic info
    name = Column(String(200), nullable=False)
    registration_no = Column(String(100))
    email = Column(String(100))
    phone = Column(String(20))

    # Address
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(50), default="USA")

    # Additional details
    specialty = Column(String(100))
    license_number = Column(String(100))
    qualification = Column(String(200))
    experience_years = Column(Integer)
    availability_days = Column(String(200))

    # Working hours
    start_time = Column(Time)
    end_time = Column(Time)

    # Consultation details
    consultation_fee = Column(Numeric(10, 2))
    # mode_of_consultation = Column(String(50))

    website = Column(String(200))
    status = Column(String(20), default="active")

    # ✅ Relationships
    users = relationship("User", back_populates="hospital", cascade="all, delete")
    doctors = relationship("Doctor", back_populates="hospital", cascade="all, delete")
    appointments = relationship("Appointment", back_populates="hospital", cascade="all, delete")

class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    npi_number = Column(String(100), unique=True)

    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(100))
    phone = Column(String(20))
    specialty = Column(String(100))
    license_number = Column(String(100))
    qualification = Column(String(200))
    experience_years = Column(Integer)
    gender = Column(String(20))
    availability_days = Column(String(200))
    start_time = Column(Time)
    end_time = Column(Time)
    mode_of_consultation = Column(String(50))

    status = Column(String(20), default="Active")

    # ✅ Relationships
    hospital = relationship("Hospital", back_populates="doctors")
    appointments = relationship("Appointment", back_populates="doctor", cascade="all, delete")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    email = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(200))
    role = Column(String(50), nullable=False)  
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    is_active = Column(Boolean, default=True)

    hospital = relationship("Hospital", back_populates="users")


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Demographics
    first_name = Column(String(100))
    last_name = Column(String(100))
    dob = Column(Date)
    gender = Column(String(20),unique=True, index=True)
    ssn = Column(String(100),unique=True, index=True)  # MRN / Identifier
    phone = Column(String(20),unique=True, index=True)
    email = Column(String(100),unique=True, index=True)

    # Address
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(50), default="USA")

    citizenship_status = Column(String(50))
    visa_type = Column(String(50))

    # ✅ Relationships
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete")
    medications = relationship("Medication", back_populates="patient", cascade="all, delete")


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    
    # Business-friendly ID (human readable)
    appointment_id = Column(String(100), unique=True, nullable=False)

    # Foreign Keys
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)

    # Appointment Details
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(Time, nullable=False)
    reason = Column(String(300))
    mode = Column(String(50), default="In-person")  # Online / In-person
    status = Column(String(50), default="Scheduled")  # Scheduled / Completed / Cancelled

    # Audit trail is provided by TimestampMixin

    # ✅ Relationships
    patient = relationship("Patient", back_populates="appointments")
    hospital = relationship("Hospital", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")


# =====================================================
# ✅ Medication Table
# =====================================================
class Medication(Base, TimestampMixin):
    __tablename__ = "medications"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))

    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="SET NULL"), nullable=True)
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)

    medication_name = Column(String(200), nullable=False)
    dosage = Column(String(100), nullable=False)
    frequency = Column(String(100), nullable=False)
    route = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(String(50), default="active")  # active / completed / stopped
    notes = Column(Text, nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="medications")
    doctor = relationship("Doctor")
    appointment = relationship("Appointment")
Patient.medications = relationship("Medication", back_populates="patient", cascade="all, delete")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    otp = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Optional if you want to link it to user
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User")

    def is_expired(self):
        return datetime.utcnow() > self.expires_at

password_reset_otps_table = Table(
    "password_reset_otps",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("otp", String(6), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("used", Boolean, default=False),
    Column("created_at", DateTime, default=datetime.utcnow)
)



