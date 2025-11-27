
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import PharmacyInsuranceMaster
from app.schemas import PharmacyInsuranceMasterOut
from app.auth import get_current_user

router = APIRouter(prefix="/pharmacyinsurance", tags=["Pharmacy Insurance"])


@router.get("/", response_model=List[PharmacyInsuranceMasterOut], summary="Get all pharmacy insurance plans")
async def get_all_pharmacy_insurance(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(PharmacyInsuranceMaster))
    return result.scalars().all()


@router.get("/providers", response_model=List[str], summary="Get distinct pharmacy provider names")
async def get_pharmacy_providers(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(PharmacyInsuranceMaster.provider_name).distinct())
    return [r[0] for r in result.all()]


@router.get("/plans/{provider_name}", response_model=List[PharmacyInsuranceMasterOut], summary="Get pharmacy plans for a provider")
async def get_pharmacy_plans_by_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if getattr(current_user, "role", None) not in ["doctor", "hospital"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        select(PharmacyInsuranceMaster).where(PharmacyInsuranceMaster.provider_name == provider_name)
    )
    plans = result.scalars().all()
    if not plans:
        raise HTTPException(status_code=404, detail="No pharmacy plans found for this provider")
    return plans
