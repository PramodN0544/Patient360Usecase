import os
import shutil
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import Patient, Doctor, Hospital
from app.auth import get_current_user  

router = APIRouter(prefix="/upload", tags=["File Upload"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# File type configuration
FILE_TYPE_CONFIG = {
    "photo": {  # Changed from "patient_photo"
        "model": Hospital,
        "field": "photo_url",
        "allowed_ext": ["jpg", "jpeg", "png"],
        "max_size": 5 * 1024 * 1024,  # 5MB,
       
       
    },
    "id_proof": {  # Changed from "patient_document"
        "model": Hospital,
        "field": "id_proof_document",
        "allowed_ext": ["pdf", "jpg", "jpeg"],
        "max_size": 10 * 1024 * 1024,  # 10MB,
       
       
    },
    "doctor_license": {
        "model": Doctor,
        "field": "license_url",
        "allowed_ext": ["jpg", "jpeg", "png", "pdf"],
        "max_size": 5 * 1024 * 1024,
        
    },
    "hospital_logo": {
        "model": Hospital,
        "field": "logo_url",
        "allowed_ext": ["jpg", "jpeg", "png"],
        "max_size": 5 * 1024 * 1024,
        
    },
}

@router.post("/{file_type}/{public_id}")
async def upload_file(
    file_type: str,
    public_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),  # Add authentication
):
    """
    Upload a file (photo, license, or document) for patient/doctor/hospital.
    - Allowed Photo formats: jpg, jpeg, png
    - Allowed Document formats: pdf, jpeg

    Example:
    - POST /upload/photo/{public_id}
    - POST /upload/id_proof/{public_id}
    """
    print(f"Upload request - file_type: {file_type}, public_id: {public_id}")

    if file_type not in FILE_TYPE_CONFIG:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file_type: {file_type}. Allowed: {list(FILE_TYPE_CONFIG.keys())}"
        )

    config = FILE_TYPE_CONFIG[file_type]
    model = config["model"]
    field = config["field"]
    allowed_ext = config["allowed_ext"]
    max_size = config.get("max_size", 10 * 1024 * 1024)

    try:
        # Validate file extension - FIXED
        file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''
        if not file_extension or file_extension not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file format: {file_extension}. Allowed formats: {', '.join(allowed_ext)}",
            )

        # Validate file size
        file.file.seek(0, 2)  # Seek to end to get file size
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        if file_size > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {file_size} bytes. Maximum size: {max_size} bytes"
            )

        # Create subfolder if not exists
        folder_path = os.path.join(UPLOAD_DIR, file_type)
        os.makedirs(folder_path, exist_ok=True)

        # Unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{public_id}_{timestamp}.{file_extension}"
        file_path = os.path.join(folder_path, filename)

        print(f"💾 Saving file to: {file_path}")

        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Convert to URL-safe path (replace backslashes)
        file_url = f"/{file_path}".replace("\\", "/")

        # Handle temporary patient IDs (like 'new-patient-temp')
        if public_id == 'new-patient-temp':
            print("Temporary patient ID - skipping database update")
            return {
                "message": f"{file_type} uploaded successfully",
                "file_url": file_url,
                "filename": filename,
                "temporary": True
            }

        # Fetch record dynamically for existing patients
        result = await db.execute(select(model).filter(model.public_id == public_id))
        record = result.scalars().first()
        
        if not record:
            raise HTTPException(
                status_code=404, 
                detail=f"{model.__name__} with public_id '{public_id}' not found"
            )

        # Update DB field with file URL
        setattr(record, field, file_url)
        await db.commit()
        await db.refresh(record)

        return {
            "message": f"{file_type} uploaded successfully",
            "file_url": file_url,
            "filename": filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")