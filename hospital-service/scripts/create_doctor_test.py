import json
import urllib.request
import urllib.error
import urllib.parse
import uuid
from datetime import time

BASE = 'http://127.0.0.1:8000'

# Unique email to avoid conflicts
email = f"test.hospital.{uuid.uuid4().hex[:6]}@example.com"
password = "StrongPass123!"

signup_payload = {
    "email": email,
    "password": password,
    "full_name": "Test Hospital",
    "role": "hospital",
    "hospital": {
        "name": "Test Hospital",
        "address": "123 Test St",
        "city": "Testville",
        "state": "TS",
        "zip_code": "12345",
        "phone": "1234567890",
        "email": email,
        "specialty": "General",
        "license_number": "LIC123",
        "qualification": "N/A",
        "experience_years": 1,
        "availability_days": "Mon-Fri",
        "start_time": "09:00:00",
        "end_time": "17:00:00",
        "consultation_fee": 50.0,
        "mode_of_consultation": "In-person"
    }
}

# Doctor payload
doctor_payload = {
    "npi_number": "NPI123456",
    "first_name": "Alice",
    "last_name": "Doctor",
    "email": f"alice.{uuid.uuid4().hex[:6]}@example.com",
    "phone": "9876543210",
    "specialty": "Cardiology",
    "license_number": "DOCLIC123",
    "qualification": "MD",
    "experience_years": 5,
    "gender": "F",
    "availability_days": "Mon-Fri",
    "start_time": "09:00:00",
    "end_time": "15:00:00",
    "mode_of_consultation": "In-person"
}


def post_json(path, data, token=None):
    url = BASE + path
    b = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=b, method='POST')
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            print('POST', path, '->', resp.status)
            print(body)
            return json.loads(body)
    except urllib.error.HTTPError as e:
        print('HTTPError', e.code, e.reason)
        try:
            err = e.read().decode()
            print(err)
        except Exception:
            pass
        return None
    except Exception as e:
        print('ERROR', e)
        return None


if __name__ == '__main__':
    print('Signing up hospital:', email)
    r = post_json('/hospitals/signup', signup_payload)
    if r is None:
        print('Signup failed; aborting')
        exit(1)

    print('Logging in...')
    login = post_json('/auth/login', {'username': email, 'password': password})
    if not login:
        print('Login failed; aborting')
        exit(1)

    token = login.get('access_token')
    print('Token:', token)

    print('Creating doctor...')
    dr = post_json('/doctors', doctor_payload, token=token)
    print('Doctor create result:', dr)
