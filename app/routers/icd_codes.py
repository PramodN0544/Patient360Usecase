from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from typing import List, Optional
from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user

router = APIRouter(
    prefix="/icd-codes",
    tags=["ICD Codes"]
)

# For dropdown/search
@router.get("/dropdown", response_model=List[schemas.IcdCodeResponse])
async def get_icd_dropdown(
    search: Optional[str] = Query(None, description="Search by code or name"),
    category: Optional[str] = Query(None, description="Filter by category"),
    version: Optional[str] = Query("ICD-10", description="ICD version"),
    is_active: bool = Query(True, description="Only active codes"),
    limit: int = Query(100, ge=1, le=1000, description="Limit results"),
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get ICD codes for dropdown/search in UI
    Returns: List of ICD codes matching search criteria
    """
    # Build the query
    query = select(models.IcdCodeMaster).where(
        models.IcdCodeMaster.is_active == is_active,
        models.IcdCodeMaster.version == version
    )
    
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                models.IcdCodeMaster.code.ilike(search_term),
                models.IcdCodeMaster.name.ilike(search_term)
            )
        )
    
    if category:
        query = query.where(models.IcdCodeMaster.category == category)
    
    query = query.order_by(models.IcdCodeMaster.code).limit(limit)
    
    # Execute the query
    result = await db.execute(query)
    icd_codes = result.scalars().all()
    return icd_codes


@router.get("/", response_model=List[schemas.IcdCodeResponse])
async def get_icd_codes(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    search: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    version: Optional[str] = None,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get all ICD codes with pagination and filtering
    """
    # Start with base query
    query = select(models.IcdCodeMaster)
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                models.IcdCodeMaster.code.ilike(search_term),
                models.IcdCodeMaster.name.ilike(search_term),
                models.IcdCodeMaster.description.ilike(search_term)
            )
        )
    
    if category:
        query = query.where(models.IcdCodeMaster.category == category)
    
    if is_active is not None:
        query = query.where(models.IcdCodeMaster.is_active == is_active)
    
    if version:
        query = query.where(models.IcdCodeMaster.version == version)
    
    # Apply ordering and pagination
    query = query.order_by(models.IcdCodeMaster.code).offset(skip).limit(limit)
    
    # Execute query
    result = await db.execute(query)
    icd_codes = result.scalars().all()
    return icd_codes


@router.get("/{icd_code_id}", response_model=schemas.IcdCodeResponse)
async def get_icd_code_by_id(
    icd_code_id: int,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get specific ICD code by ID
    """
    query = select(models.IcdCodeMaster).where(models.IcdCodeMaster.id == icd_code_id)
    result = await db.execute(query)
    icd_code = result.scalar_one_or_none()
    
    if not icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    return icd_code


@router.get("/code/{code}", response_model=schemas.IcdCodeResponse)
async def get_icd_code_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get ICD code by its code (e.g., "J06.9")
    """
    query = select(models.IcdCodeMaster).where(models.IcdCodeMaster.code == code)
    result = await db.execute(query)
    icd_code = result.scalar_one_or_none()
    
    if not icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ICD code '{code}' not found"
        )
    
    return icd_code


@router.post("/", response_model=schemas.IcdCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_icd_code(
    icd_code: schemas.IcdCodeCreate,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Create a new ICD code (Admin/Hospital only)
    """
    # Check permissions (example)
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create ICD codes"
        )
    
    # Check if code already exists
    query = select(models.IcdCodeMaster).where(models.IcdCodeMaster.code == icd_code.code)
    result = await db.execute(query)
    existing_code = result.scalar_one_or_none()
    
    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ICD code '{icd_code.code}' already exists"
        )
    
    db_icd_code = models.IcdCodeMaster(**icd_code.dict())
    db.add(db_icd_code)
    await db.commit()
    await db.refresh(db_icd_code)
    
    return db_icd_code


@router.put("/{icd_code_id}", response_model=schemas.IcdCodeResponse)
async def update_icd_code(
    icd_code_id: int,
    icd_code_update: schemas.IcdCodeUpdate,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Update an ICD code (Admin/Hospital only)
    """
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update ICD codes"
        )
    
    query = select(models.IcdCodeMaster).where(models.IcdCodeMaster.id == icd_code_id)
    result = await db.execute(query)
    db_icd_code = result.scalar_one_or_none()
    
    if not db_icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    update_data = icd_code_update.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(db_icd_code, field, value)
    
    await db.commit()
    await db.refresh(db_icd_code)
    
    return db_icd_code


@router.delete("/{icd_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icd_code(
    icd_code_id: int,
    db: AsyncSession = Depends(get_db),  # Change to AsyncSession
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Soft delete an ICD code by setting is_active=False
    """
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete ICD codes"
        )
    
    query = select(models.IcdCodeMaster).where(models.IcdCodeMaster.id == icd_code_id)
    result = await db.execute(query)
    db_icd_code = result.scalar_one_or_none()
    
    if not db_icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    db_icd_code.is_active = False
    await db.commit()
    
    return None