from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from typing import List, Optional, Dict, Any
from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user

router = APIRouter(
    prefix="/icd-codes",
    tags=["ICD Codes"]
)

# Define a response model for ICD codes since we removed IcdCodeResponse
class ICDCodeResponse(Dict[str, Any]):
    pass

# For dropdown/search
@router.get("/dropdown", response_model=List[Dict[str, Any]])
async def get_icd_dropdown(
    search: Optional[str] = Query(None, description="Search by code or description"),
    condition_group: Optional[str] = Query(None, description="Filter by condition group"),
    limit: int = Query(100, ge=1, le=1000, description="Limit results"),
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get ICD codes for dropdown/search in UI
    Returns: List of ICD codes matching search criteria
    """
    # Build the query
    query = select(models.ICDConditionMap).options(
        # Join with condition group to get the name
        joinedload(models.ICDConditionMap.condition_group)
    )
    
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                models.ICDConditionMap.icd_code.ilike(search_term),
                models.ICDConditionMap.description.ilike(search_term)
            )
        )
    
    if condition_group:
        query = query.join(models.ConditionGroup).where(
            models.ConditionGroup.name == condition_group
        )
    
    query = query.order_by(models.ICDConditionMap.icd_code).limit(limit)
    
    # Execute the query
    result = await db.execute(query)
    icd_codes = result.scalars().all()
    
    # Format the response
    return [
        {
            "id": icd.id,
            "code": icd.icd_code,
            "name": icd.description or icd.icd_code,
            "description": icd.description,
            "condition_group": icd.condition_group.name if icd.condition_group else "Unknown",
            "is_pattern": icd.is_pattern
        }
        for icd in icd_codes
    ]


@router.get("/", response_model=List[Dict[str, Any]])
async def get_icd_codes(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    search: Optional[str] = None,
    condition_group: Optional[str] = None,
    is_active: Optional[bool] = None,  # Added is_active parameter but we'll ignore it
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get all ICD codes with pagination and filtering
    """
    # Start with base query
    query = select(models.ICDConditionMap).options(
        joinedload(models.ICDConditionMap.condition_group)
    )
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                models.ICDConditionMap.icd_code.ilike(search_term),
                models.ICDConditionMap.description.ilike(search_term)
            )
        )
    
    if condition_group:
        query = query.join(models.ConditionGroup).where(
            models.ConditionGroup.name == condition_group
        )
    
    # Apply ordering and pagination
    query = query.order_by(models.ICDConditionMap.icd_code).offset(skip).limit(limit)
    
    # Execute query
    result = await db.execute(query)
    icd_codes = result.scalars().all()
    
    # Format the response
    return [
        {
            "id": icd.id,
            "code": icd.icd_code,
            "name": icd.description or icd.icd_code,
            "description": icd.description,
            "condition_group": icd.condition_group.name if icd.condition_group else "Unknown",
            "is_pattern": icd.is_pattern
        }
        for icd in icd_codes
    ]


@router.get("/{icd_code_id}", response_model=Dict[str, Any])
async def get_icd_code_by_id(
    icd_code_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get specific ICD code by ID
    """
    query = select(models.ICDConditionMap).where(
        models.ICDConditionMap.id == icd_code_id
    ).options(
        joinedload(models.ICDConditionMap.condition_group)
    )
    
    result = await db.execute(query)
    icd_code = result.scalar_one_or_none()
    
    if not icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    return {
        "id": icd_code.id,
        "code": icd_code.icd_code,
        "name": icd_code.description or icd_code.icd_code,
        "description": icd_code.description,
        "condition_group": icd_code.condition_group.name if icd_code.condition_group else "Unknown",
        "condition_group_id": icd_code.condition_group_id,
        "is_pattern": icd_code.is_pattern
    }


@router.get("/code/{code}", response_model=Dict[str, Any])
async def get_icd_code_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Get ICD code by its code (e.g., "J06.9")
    """
    query = select(models.ICDConditionMap).where(
        models.ICDConditionMap.icd_code == code
    ).options(
        joinedload(models.ICDConditionMap.condition_group)
    )
    
    result = await db.execute(query)
    icd_code = result.scalar_one_or_none()
    
    if not icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ICD code '{code}' not found"
        )
    
    return {
        "id": icd_code.id,
        "code": icd_code.icd_code,
        "name": icd_code.description or icd_code.icd_code,
        "description": icd_code.description,
        "condition_group": icd_code.condition_group.name if icd_code.condition_group else "Unknown",
        "condition_group_id": icd_code.condition_group_id,
        "is_pattern": icd_code.is_pattern
    }


@router.post("/", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_icd_code(
    icd_code_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Create a new ICD code (Admin/Hospital only)
    """
    # Check permissions
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create ICD codes"
        )
    
    # Check required fields
    if "icd_code" not in icd_code_data or "condition_group_id" not in icd_code_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="icd_code and condition_group_id are required"
        )
    
    # Check if code already exists
    query = select(models.ICDConditionMap).where(
        models.ICDConditionMap.icd_code == icd_code_data["icd_code"]
    )
    result = await db.execute(query)
    existing_code = result.scalar_one_or_none()
    
    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ICD code '{icd_code_data['icd_code']}' already exists"
        )
    
    # Check if condition group exists
    condition_group_query = select(models.ConditionGroup).where(
        models.ConditionGroup.condition_group_id == icd_code_data["condition_group_id"]
    )
    condition_group_result = await db.execute(condition_group_query)
    condition_group = condition_group_result.scalar_one_or_none()
    
    if not condition_group:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Condition group with ID {icd_code_data['condition_group_id']} not found"
        )
    
    # Create new ICD code
    db_icd_code = models.ICDConditionMap(
        icd_code=icd_code_data["icd_code"],
        condition_group_id=icd_code_data["condition_group_id"],
        description=icd_code_data.get("description"),
        is_pattern=icd_code_data.get("is_pattern", False)
    )
    
    db.add(db_icd_code)
    await db.commit()
    await db.refresh(db_icd_code)
    
    return {
        "id": db_icd_code.id,
        "code": db_icd_code.icd_code,
        "name": db_icd_code.description or db_icd_code.icd_code,
        "description": db_icd_code.description,
        "condition_group_id": db_icd_code.condition_group_id,
        "condition_group": condition_group.name,
        "is_pattern": db_icd_code.is_pattern
    }


@router.put("/{icd_code_id}", response_model=Dict[str, Any])
async def update_icd_code(
    icd_code_id: int,
    icd_code_update: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
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
    
    query = select(models.ICDConditionMap).where(
        models.ICDConditionMap.id == icd_code_id
    )
    result = await db.execute(query)
    db_icd_code = result.scalar_one_or_none()
    
    if not db_icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    # Check if condition group exists if it's being updated
    if "condition_group_id" in icd_code_update:
        condition_group_query = select(models.ConditionGroup).where(
            models.ConditionGroup.condition_group_id == icd_code_update["condition_group_id"]
        )
        condition_group_result = await db.execute(condition_group_query)
        condition_group = condition_group_result.scalar_one_or_none()
        
        if not condition_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Condition group with ID {icd_code_update['condition_group_id']} not found"
            )
    
    # Update fields
    if "icd_code" in icd_code_update:
        db_icd_code.icd_code = icd_code_update["icd_code"]
    
    if "condition_group_id" in icd_code_update:
        db_icd_code.condition_group_id = icd_code_update["condition_group_id"]
    
    if "description" in icd_code_update:
        db_icd_code.description = icd_code_update["description"]
    
    if "is_pattern" in icd_code_update:
        db_icd_code.is_pattern = icd_code_update["is_pattern"]
    
    await db.commit()
    await db.refresh(db_icd_code)
    
    # Get condition group name
    condition_group_query = select(models.ConditionGroup).where(
        models.ConditionGroup.condition_group_id == db_icd_code.condition_group_id
    )
    condition_group_result = await db.execute(condition_group_query)
    condition_group = condition_group_result.scalar_one_or_none()
    
    return {
        "id": db_icd_code.id,
        "code": db_icd_code.icd_code,
        "name": db_icd_code.description or db_icd_code.icd_code,
        "description": db_icd_code.description,
        "condition_group_id": db_icd_code.condition_group_id,
        "condition_group": condition_group.name if condition_group else "Unknown",
        "is_pattern": db_icd_code.is_pattern
    }


@router.delete("/{icd_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icd_code(
    icd_code_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: schemas.UserOut = Depends(get_current_user)
):
    """
    Delete an ICD code
    """
    if current_user.role not in ["admin", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete ICD codes"
        )
    
    query = select(models.ICDConditionMap).where(
        models.ICDConditionMap.id == icd_code_id
    )
    result = await db.execute(query)
    db_icd_code = result.scalar_one_or_none()
    
    if not db_icd_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ICD code not found"
        )
    
    await db.delete(db_icd_code)
    await db.commit()
    
    return None