from sqlalchemy import (
    Column, String, Date, Integer, Boolean, TIMESTAMP, 
    ForeignKey, Text, Numeric, Time
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# -----------------------------------------------------
# ✅ Hospital Table
# -----------------------------------------------------
class Hospital(Base):
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

    # Additional hospital details
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
    mode_of_consultation = Column(String(50))

    website = Column(String(200))
    status = Column(String(20), default="active")
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.func.now())

    # ✅ Relationships
    users = relationship("User", back_populates="hospital", cascade="all,delete")
    doctors = relationship("Doctor", back_populates="hospital", cascade="all,delete")
    # patients = relationship("Patient", back_populates="hospital", cascade="all,delete")

# -----------------------------------------------------
# ✅ Doctor Table
# -----------------------------------------------------
class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()")
    )

    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    npi_number = Column(String(100), unique=True)

    # FHIR Practitioner fields
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(100))
    phone = Column(String(20))
    specialty = Column(String(100))
    license_number = Column(String(100))
    qualification = Column(String(200))
    experience_years = Column(Integer)
    gender = Column(String, nullable=True)
    availability_days = Column(String(200))
    start_time = Column(Time)
    end_time = Column(Time)
    mode_of_consultation = Column(String(50))

    status = Column(String(20), default="Active")
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.func.now())

    hospital = relationship("Hospital", back_populates="doctors")


# -----------------------------------------------------
# ✅ User Table
# -----------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()'))
    
    email = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(200))
    role = Column(String(50), default="hospital")  # hospital / doctor / admin / patient
    
    # ✅ User belongs to a hospital (optional for admin)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"))
    
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.func.now())

    # ✅ Relationship
    hospital = relationship("Hospital", back_populates="users")


# -----------------------------------------------------
# ✅ Patient Table
# -----------------------------------------------------
class Patient(Base):
    __tablename__ = "patients"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()")
    )

    # FHIR Patient fields
    first_name = Column(String(100))
    last_name = Column(String(100))
    dob = Column(Date)            # FHIR: birthDate
    gender = Column(String(20))   # male/female/other/unknown
    ssn = Column(String(100))     # FHIR: identifier (MRN)
    phone = Column(String(20))
    email = Column(String(100))

    # Address
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip_code = Column(String(20))
    country = Column(String(50), default="USA")

    citizenship_status = Column(String(50))
    visa_type = Column(String(50))

    created_at = Column(TIMESTAMP(timezone=True), server_default=sa.func.now())

    # hospital = relationship("Hospital", back_populates="patients")