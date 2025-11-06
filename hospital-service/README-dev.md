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
 - To allow your frontend to call this API, configure CORS by setting one of the environment variables before starting the server:
	 - `FRONTEND_ORIGINS` — comma-separated list of allowed origins (e.g. `http://localhost:3000,http://localhost:5173`)
	 - `FRONTEND_URL` — single allowed origin (e.g. `http://localhost:3000`)
	 If none are set we default to `http://localhost:3000` and `http://localhost:5173` for local development.
