import os
import shutil
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import Patient, Doctor, Hospital

router = APIRouter(prefix="/upload", tags=["File Upload"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ✅ File type configuration
FILE_TYPE_CONFIG = {
    "patient_photo": {
        "model": Patient,
        "field": "photo_url",
        "allowed_ext": ["jpg", "jpeg", "png"],
    },
    "patient_document": {
        "model": Patient,
        "field": "id_proof_document",
        "allowed_ext": ["pdf", "jpeg"],
    },
    "doctor_license": {
        "model": Doctor,
        "field": "license_url",
        "allowed_ext": ["jpg", "jpeg", "png"],
    },
    "doctor_document": {
        "model": Doctor,
        "field": "license_document",
        "allowed_ext": ["pdf", "jpeg"],
    },
    "hospital_logo": {
        "model": Hospital,
        "field": "logo_url",
        "allowed_ext": ["jpg", "jpeg", "png"],
    },
    "hospital_document": {
        "model": Hospital,
        "field": "registration_certificate",
        "allowed_ext": ["pdf", "jpeg"],
    },
}


@router.post("/{file_type}/{public_id}")
async def upload_file(
    file_type: str,
    public_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a file (photo, license, or document) for patient/doctor/hospital.
    - Allowed Photo formats: jpg, jpeg, png
    - Allowed Document formats: pdf, jpeg

    Example:
    - POST /upload/patient_photo/{public_id}
    - POST /upload/doctor_license/{public_id}
    """
    if file_type not in FILE_TYPE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid file_type")

    config = FILE_TYPE_CONFIG[file_type]
    model = config["model"]
    field = config["field"]
    allowed_ext = config["allowed_ext"]

    try:
        # 🧩 Validate file extension
        ext = os.path.splitext(file.filename)[1].lower().replace(".", "")
        if ext not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file format. Allowed formats: {', '.join(allowed_ext)}",
            )

        # 📁 Create subfolder if not exists
        folder_path = os.path.join(UPLOAD_DIR, file_type)
        os.makedirs(folder_path, exist_ok=True)

        # 🕓 Unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{file_type}_{timestamp}.{ext}"
        file_path = os.path.join(folder_path, filename)

        # 💾 Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # ✅ Convert to URL-safe path (replace backslashes)
        file_url = f"/{file_path}".replace("\\", "/")

        # 🔍 Fetch record dynamically
        result = await db.execute(select(model).filter(model.public_id == public_id))
        record = result.scalars().first()
        if not record:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")

        # ⚡ Update DB field with file URL
        setattr(record, field, file_url)
        await db.commit()
        await db.refresh(record)

        return {
            "message": f"{file_type} uploaded successfully",
            "file_url": file_url,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
