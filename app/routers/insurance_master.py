# app/routers/insurance_master.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import InsuranceMaster
from app.schemas import InsuranceMasterOut  
from app.auth import get_current_user 

router = APIRouter(prefix="/insurance", tags=["Insurance"])

@router.get("/", response_model=List[InsuranceMasterOut], summary="Get all insurance plans (only for doctors/hospitals)")
async def get_all_insurance_plans(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Role check
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only doctors or hospitals can access this."
        )

    result = await db.execute(select(InsuranceMaster))
    insurance_list = result.scalars().all()
    return insurance_list


@router.get("/providers", response_model=List[str], summary="Get distinct provider names")
async def get_providers(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Role check
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only doctors or hospitals can access this."
        )

    result = await db.execute(select(InsuranceMaster.provider_name).distinct())
    rows = result.all()
    # rows are tuples like ('Blue Cross',)
    providers = [row[0] for row in rows]
    return providers


@router.get("/plans/{provider_name}", response_model=List[InsuranceMasterOut], summary="Get plans for a provider")
async def get_plans_by_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Role check
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only doctors or hospitals can access this."
        )

    result = await db.execute(
        select(InsuranceMaster).where(InsuranceMaster.provider_name == provider_name)
    )
    plans = result.scalars().all()
    if not plans:
        raise HTTPException(status_code=404, detail="No plans found for this provider")
    return plans
