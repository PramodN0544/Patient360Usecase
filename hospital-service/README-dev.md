# Development notes

This file lists small helpers and the recommended way to run the development server and the test scripts.

Run server (recommended)

1. From the repository root run the PowerShell helper (recommended):

```powershell
cd hospital-service
.\run_server.ps1 -Reload
```

2. Alternative: run uvicorn directly from the `hospital-service` folder:

```powershell
cd hospital-service
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Developer scripts

All small helper/test scripts are in the `hospital-service/scripts/` folder. Example:

```powershell
python hospital-service/scripts/create_doctor_test.py
python hospital-service/scripts/login_test.py
```

Notes

- Keep the `app/` package in `hospital-service/app` so Python imports work when running from that folder.
- If port 8000 is in use, stop the process or start the server on a different port.
