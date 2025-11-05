-- ✅ Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ✅ Hospitals table
CREATE TABLE IF NOT EXISTS hospitals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    phone VARCHAR(20),
    email VARCHAR(100),
    specialty VARCHAR(100),
    license_number VARCHAR(100),
    qualification VARCHAR(200),
    experience_years INT,
    availability_days VARCHAR(200),

    start_time TIME,
    end_time TIME,

    consultation_fee NUMERIC(10,2),
    mode_of_consultation VARCHAR(50),
    status VARCHAR(20) DEFAULT 'Active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- ✅ Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(200) UNIQUE NOT NULL,
    hashed_password VARCHAR(200) NOT NULL,
    full_name VARCHAR(200),
    role VARCHAR(50) DEFAULT 'hospital',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- ✅ Patients table
CREATE TABLE IF NOT EXISTS patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id UUID REFERENCES hospitals(id) ON DELETE SET NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    dob DATE,
    gender VARCHAR(20),
    mrn VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    country VARCHAR(50) DEFAULT 'USA',

    citizenship_status VARCHAR(50),
    visa_type VARCHAR(50),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
