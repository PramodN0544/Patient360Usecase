from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

payload = {
  "email": "test.hospital2@example.com",
  "password": "short",
  "full_name": "CityCare Admin2",
  "role": "hospital",
  "hospital": {
    "name": "New CityCare 2",
    "address": "1 Test St",
    "city": "Testville",
    "state": "TS",
    "zip_code": "00000",
    "phone": "1234567890",
    "email": "newcitycare2@example.com",
    "specialty": "General",
    "license_number": "LIC-12345",
    "qualification": "MD",
    "experience_years": 10,
    "availability_days": "Mon-Fri",
    "start_time": "09:00:00",
    "end_time": "17:00:00",
    "consultation_fee": 100.00,
    "mode_of_consultation": "Both",
    "website": "https://newcitycare2.test"
  }
}

resp = client.post("/hospitals/signup", json=payload)
print("status", resp.status_code)
print(resp.json())