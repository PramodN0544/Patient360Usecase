from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
import json
import httpx
import os
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from app.utils import send_email
from dotenv import load_dotenv
load_dotenv()


router = APIRouter(prefix="/api/care-plans", tags=["care-plans"])

# LLM API configuration
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4")

from datetime import datetime, date

def parse_iso_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except:
        return None

import re

def extract_json_from_llm(text: str) -> dict:
    """
    Extract JSON safely from LLM response, removing markdown fences like ```json.
    """
    cleaned = text.strip()

    # Remove leading/trailing code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
        cleaned = cleaned.replace("```", "").strip()

    # Extract JSON block
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("No JSON object found in LLM response")

    return json.loads(match.group(0))

async def generate_care_plan_with_llm(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a care plan using the LLM API
    """
    print(f"🔄 Starting LLM care plan generation")
    
    # Check if API key is available
    if not LLM_API_KEY:
        print(f"⚠️ LLM_API_KEY is not set or empty")
        # Create a fallback care plan if no API key is available
        return {
            "careplan_id": "fallback_001",
            "status": "proposed",
            "generated_at": datetime.utcnow().isoformat(),
            "condition_group": input_data.get("guideline_rules", {}).get("condition_group", "General"),
            "icd_codes": [],
            "tasks": [
                {
                    "task_id": "task_001",
                    "type": "follow_up",
                    "title": "Schedule Follow-up Appointment",
                    "description": "Please schedule a follow-up appointment with your doctor in 2 weeks.",
                    "frequency": "once",
                    "due_date": (datetime.now().date() + timedelta(days=14)).isoformat(),
                    "assigned_to": "patient",
                    "requires_clinician_review": False
                }
            ],
            "patient_friendly_summary": "This is a basic care plan. Please follow the tasks and contact your doctor if you have any questions.",
            "clinician_summary": "Basic care plan generated due to LLM API unavailability.",
            "metadata": {
                "guideline_used": "Basic Care",
                "rules_version": "2025-01",
                "llm_model": "fallback",
                "created_by": "system"
            }
        }
    
    print(f"🔑 Using LLM API key: {LLM_API_KEY[:5]}... (truncated)")
    print(f"🧠 Using LLM model: {LLM_MODEL}")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }
    
    # Prepare the prompt for the LLM
    print(f"📝 Preparing LLM prompt")
    
    # Create a sanitized version of input_data for logging (remove sensitive info)
    log_data = {k: "..." if k in ["patient_profile"] else v for k, v in input_data.items()}
    print(f"📊 Input data summary: {json.dumps(log_data, default=str)[:200]}... (truncated)")
    
    prompt = f"""
    You are a clinical decision support system that generates care plans based on patient data.
    Please analyze the following patient information and generate a comprehensive care plan.
    Do not hallucinate any information; only use the data provided.
    
    Patient Information:
    {json.dumps(input_data, indent=2, default=str)}
    
    Generate a care plan that includes:
    1. A list of tasks for the patient and healthcare providers
    2. A patient-friendly summary
    3. A clinical summary for healthcare providers
    
    Format your response as a JSON object with the following structure:
    {{
      "careplan_id": "cp_001",
      "status": "proposed",
      "generated_at": "2025-12-09T12:30:00Z",
      "condition_group": "Type 1 Diabetes",
      "icd_codes": ["E10.65"],
      "tasks": [
        {{
          "task_id": "task_001",
          "type": "lab_test",
          "title": "Repeat HbA1c",
          "description": "Repeat HbA1c test in 3 months to assess glycemic improvement.",
          "frequency": "once",
          "due_date": "2026-03-09",
          "assigned_to": "provider",
          "requires_clinician_review": false
        }},
        ...
      ],
      "patient_friendly_summary": "Your care plan focuses on improving blood sugar control...",
      "clinician_summary": "Careplan aligns with NICE NG17...",
      "metadata": {{
        "guideline_used": "NICE NG17",
        "rules_version": "2025-01",
        "llm_model": "gpt-5.1",
        "created_by": "system"
      }}
    }}
    """
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a clinical decision support system that generates care plans based on patient data."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }
    
    print(f"📡 Sending request to LLM API: {LLM_API_URL}")
    
    try:
        async with httpx.AsyncClient(timeout=120) as client:  # Increased timeout to 2 minutes for LLM API call
            print(f"🔄 Making API request...")
            response = await client.post(LLM_API_URL, json=payload, headers=headers)
            print(f"📊 API Response Status: {response.status_code}")
            
            # Log a truncated version of the response to avoid flooding logs
            response_preview = response.text[:500] + "..." if len(response.text) > 500 else response.text
            print(f"📄 Raw Response Preview: {response_preview}")
            
            response.raise_for_status()
            
            print(f"✅ API request successful, parsing response")
            result = response.json()
            llm_response = result["choices"][0]["message"]["content"]
            
            # Log a truncated version of the LLM response
            llm_preview = llm_response[:500] + "..." if len(llm_response) > 500 else llm_response
            print(f"📄 LLM Response Preview: {llm_preview}")
            
            # Parse the JSON response from the LLM
            print(f"🔄 Extracting JSON from LLM response")
            care_plan_data = extract_json_from_llm(llm_response)
            
            # Validate the care plan data has required fields
            required_fields = ["tasks", "patient_friendly_summary", "clinician_summary"]
            for field in required_fields:
                if field not in care_plan_data:
                    print(f"⚠️ Missing required field in care plan data: {field}")
                    care_plan_data[field] = "Not provided by LLM" if field.endswith("summary") else []
            
            print(f"✅ Successfully extracted care plan data with {len(care_plan_data.get('tasks', []))} tasks")
            return care_plan_data
            
    except httpx.HTTPStatusError as e:
        error_detail = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        print(f"❌ HTTP Status Error: {error_detail}")
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to API error")
        return create_fallback_care_plan(input_data, f"API Error: {e.response.status_code}")
        
    except httpx.TimeoutException as e:
        print(f"⏱️ Timeout Error: {str(e)}")
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to timeout")
        return create_fallback_care_plan(input_data, "API Timeout")
        
    except httpx.RequestError as e:
        print(f"🌐 Request Error: {str(e)}")
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to request error")
        return create_fallback_care_plan(input_data, f"Request Error: {str(e)}")
        
    except json.JSONDecodeError as e:
        print(f"📋 JSON Decode Error: {str(e)}")
        print(f"📄 Response that caused error: {response.text[:500]}...")
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to JSON decode error")
        return create_fallback_care_plan(input_data, "JSON Parse Error")
        
    except KeyError as e:
        print(f"🔑 KeyError: {str(e)}")
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to missing key: {str(e)}")
        return create_fallback_care_plan(input_data, f"Missing Key: {str(e)}")
        
    except Exception as e:
        # ✅ Generic exception LAST
        print(f"💥 Unexpected Error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Create a fallback care plan
        print(f"⚠️ Creating fallback care plan due to unexpected error")
        return create_fallback_care_plan(input_data, f"Error: {type(e).__name__}")

def create_fallback_care_plan(input_data: Dict[str, Any], error_reason: str) -> Dict[str, Any]:
    """Create a fallback care plan when the LLM API fails"""
    print(f"🔄 Creating fallback care plan due to: {error_reason}")
    
    # Extract some basic info from input data
    encounter_data = input_data.get("current_encounter", {})
    encounter_id = encounter_data.get("encounter_id", "unknown")
    diagnosis = encounter_data.get("diagnosis_text", "General checkup")
    condition_group = input_data.get("guideline_rules", {}).get("condition_group", "General")
    
    # Extract ICD codes if available
    icd_codes = []
    if "current_encounter" in input_data and "icd_codes" in input_data["current_encounter"]:
        icd_codes = input_data["current_encounter"]["icd_codes"]
    
    # Create a basic care plan
    return {
        "careplan_id": f"fallback_{encounter_id}",
        "status": "proposed",
        "generated_at": datetime.utcnow().isoformat(),
        "condition_group": condition_group,
        "icd_codes": icd_codes,
        "tasks": [
            {
                "task_id": "task_001",
                "type": "follow_up",
                "title": "Schedule Follow-up Appointment",
                "description": "Please schedule a follow-up appointment with your doctor in 2 weeks.",
                "frequency": "once",
                "due_date": (datetime.now().date() + timedelta(days=14)).isoformat(),
                "assigned_to": "patient",
                "requires_clinician_review": False
            },
            {
                "task_id": "task_002",
                "type": "medication",
                "title": "Continue Current Medications",
                "description": "Continue taking your current medications as prescribed.",
                "frequency": "daily",
                "due_date": None,
                "assigned_to": "patient",
                "requires_clinician_review": False
            }
        ],
        "patient_friendly_summary": f"This is a basic care plan for your {diagnosis}. Please follow the tasks and contact your doctor if you have any questions or if your symptoms worsen.",
        "clinician_summary": f"Basic care plan generated due to LLM API error: {error_reason}. Please review and update as needed.",
        "metadata": {
            "guideline_used": "Basic Care",
            "rules_version": "2025-01",
            "llm_model": "fallback",
            "created_by": "system",
            "error_reason": error_reason
        }
    }
        
async def send_care_plan_notification(user_id: int, care_plan_id: int, db: AsyncSession):
    """
    Send a notification to the user about the new care plan
    """
    # Get the user
    user_result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = user_result.scalars().first()
    
    if not user:
        print(f"User {user_id} not found for notification")
        return
    
    # Get the care plan
    care_plan_result = await db.execute(select(models.CarePlan).where(models.CarePlan.careplan_id == care_plan_id))
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        print(f"Care plan {care_plan_id} not found for notification")
        return
    
    # Create notification
    notification = models.Notification(
        user_id=user_id,
        title="New Care Plan Available",
        desc="A new care plan has been created for you. Please review it.",
        type="care_plan",
        status="unread",
        data_id=str(care_plan_id),
        patient_id=care_plan.patient_id
    )
    
    db.add(notification)
    await db.commit()
    
    # Send email notification if user has email
    if user.email:
        send_email(
            user.email,
            "New Care Plan Available",
            f"""
            Dear {user.full_name},
            
            A new care plan has been created for you. Please log in to your account to review it.
            
            Regards,
            CareIQ Team
            """
        )

@router.post("/generate", response_model=schemas.CarePlanOut)
async def generate_care_plan(
    input_data: schemas.CarePlanGenerationInput,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a care plan for a patient based on encounter data
    """
    print(f"🔄 Received request to generate care plan for encounter {input_data.current_encounter.encounter_id}")
    
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        print(f"❌ User role {current_user.role} not authorized to generate care plans")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can generate care plans"
        )
    
    print(f"✅ User {current_user.id} with role {current_user.role} is authorized")
    
    # Get the encounter
    encounter_id = input_data.current_encounter.encounter_id
    print(f"🔍 Looking up encounter with ID {encounter_id}")
    
    encounter_result = await db.execute(
        select(models.Encounter).where(models.Encounter.id == encounter_id)
    )
    encounter = encounter_result.scalars().first()
    
    if not encounter:
        print(f"❌ Encounter with ID {encounter_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter with ID {encounter_id} not found"
        )
    
    print(f"✅ Found encounter {encounter_id} for patient {encounter.patient_id}")
    
    # Get ICD code from the encounter
    print(f"🔍 Looking up ICD code for encounter {encounter_id}")
    
    # Default condition group name
    condition_name = "General"
    
    # Check if encounter has a primary ICD code
    if not encounter.primary_icd_code:
        print(f"⚠️ No ICD code found for encounter {encounter_id}, using default condition group")
        icd_code = None
    else:
        print(f"✅ Found primary ICD code: {encounter.primary_icd_code}")
        icd_code = encounter.primary_icd_code
        
        if icd_code:
            # Look up condition group mapping for this ICD code
            print(f"🔍 Looking up condition group mapping for ICD code: {icd_code}")
            icd_mapping_result = await db.execute(
                select(models.ICDConditionMap)
                .where(
                    or_(
                        models.ICDConditionMap.icd_code == icd_code,
                        # Also check for pattern matches if is_pattern is True
                        and_(
                            models.ICDConditionMap.is_pattern == True,
                            func.substring(icd_code, 1, func.length(models.ICDConditionMap.icd_code)) == models.ICDConditionMap.icd_code
                        )
                    )
                )
                .options(selectinload(models.ICDConditionMap.condition_group))
            )
            icd_mapping = icd_mapping_result.scalars().first()
            
            if icd_mapping and icd_mapping.condition_group:
                print(f"✅ Found condition group mapping: {icd_mapping.condition_group.name}")
                condition_name = icd_mapping.condition_group.name
            else:
                print(f"⚠️ No condition group mapping found for ICD code {icd_code}, using default")
    
    # If guideline rules were provided in input, use that condition group as override
    if input_data.guideline_rules and input_data.guideline_rules.condition_group:
        print(f"ℹ️ Overriding condition group with provided value: {input_data.guideline_rules.condition_group}")
        condition_name = input_data.guideline_rules.condition_group
    
    print(f"🔍 Looking up condition group: {condition_name}")
    condition_group_result = await db.execute(
        select(models.ConditionGroup).where(models.ConditionGroup.name == condition_name)
    )
    condition_group = condition_group_result.scalars().first()
    
    if not condition_group:
        print(f"🆕 Creating new condition group: {condition_name}")
        # Create new condition group
        condition_group = models.ConditionGroup(
            name=condition_name,
            description=f"Condition group for {condition_name}"
        )
        db.add(condition_group)
        await db.commit()
        await db.refresh(condition_group)
        print(f"✅ Created condition group with ID {condition_group.condition_group_id}")
    else:
        print(f"✅ Found existing condition group with ID {condition_group.condition_group_id}")
    
    try:
        # Generate care plan using LLM
        print(f"🧠 Generating care plan using LLM for encounter {encounter_id}")
        
        # Prepare input data with ICD codes from the encounter
        input_data_dict = input_data.dict()
        
        # Get ICD code from the encounter if not already provided
        if not input_data_dict.get("current_encounter", {}).get("icd_codes"):
            print(f"🔍 Fetching ICD code for LLM input")
            icd_codes = []
            
            # Check if there's a primary ICD code
            if encounter.primary_icd_code:
                print(f"✅ Found primary_icd_code: {encounter.primary_icd_code}")
                
                # Look up the ICD code in the ICDConditionMap table to get description
                icd_map_result = await db.execute(
                    select(models.ICDConditionMap).where(models.ICDConditionMap.icd_code == encounter.primary_icd_code)
                )
                icd_map = icd_map_result.scalar_one_or_none()
                
                if icd_map:
                    print(f"✅ Found ICD code in condition map: {icd_map.icd_code} - {icd_map.description}")
                    icd_codes.append({
                        "code": icd_map.icd_code,
                        "name": icd_map.description or encounter.primary_icd_code,
                        "description": icd_map.description,
                        "is_primary": True
                    })
                else:
                    # If not found in map, use the direct values
                    print(f"⚠️ ICD code not found in condition map, using direct value")
                    icd_codes.append({
                        "code": encounter.primary_icd_code,
                        "name": encounter.diagnosis or encounter.primary_icd_code,
                        "description": encounter.diagnosis,
                        "is_primary": True
                    })
            
            # Add ICD codes to input data
            if "current_encounter" not in input_data_dict:
                input_data_dict["current_encounter"] = {}
            
            input_data_dict["current_encounter"]["icd_codes"] = icd_codes
            print(f"✅ Added {len(icd_codes)} ICD codes to LLM input")
        
        # Add condition group to input data
        if "guideline_rules" not in input_data_dict:
            input_data_dict["guideline_rules"] = {}
        
        input_data_dict["guideline_rules"]["condition_group"] = condition_name
        
        # Log the enhanced input data
        print(f"📊 Enhanced input data with ICD codes and condition group")
        
        care_plan_data = await generate_care_plan_with_llm(input_data_dict)
        print(f"✅ LLM generated care plan data successfully")
        
        # Create care plan in database
        print(f"💾 Creating care plan in database for patient {encounter.patient_id}")
        care_plan = models.CarePlan(
            patient_id=encounter.patient_id,
            encounter_id = int(input_data.current_encounter.encounter_id),
            condition_group_id=condition_group.condition_group_id,
            status="proposed",
            patient_friendly_summary=care_plan_data.get("patient_friendly_summary", ""),
            clinician_summary=care_plan_data.get("clinician_summary", ""),
            plan_metadata=care_plan_data.get("metadata", {})
        )
        
        db.add(care_plan)
        await db.commit()
        await db.refresh(care_plan)
        print(f"✅ Created care plan with ID {care_plan.careplan_id}")
        
        # Create tasks for the care plan
        tasks_count = len(care_plan_data.get("tasks", []))
        print(f"🔄 Creating {tasks_count} tasks for care plan {care_plan.careplan_id}")
        
        for i, task_data in enumerate(care_plan_data.get("tasks", [])):
            task = models.CarePlanTask(
                careplan_id=care_plan.careplan_id,
                type=task_data.get("type", "other"),
                title=task_data.get("title", ""),
                description=task_data.get("description", ""),
                frequency=task_data.get("frequency", ""),
                due_date=parse_iso_date(task_data.get("due_date")),
                assigned_to=task_data.get("assigned_to", "patient"),
                requires_clinician_review=task_data.get("requires_clinician_review", False),
                status="pending"
            )
            db.add(task)
            print(f"  ✅ Created task {i+1}/{tasks_count}: {task_data.get('title', '')}")
        
        # Create audit log
        print(f"📝 Creating audit log for care plan {care_plan.careplan_id}")
        audit = models.CarePlanAudit(
            careplan_id=care_plan.careplan_id,
            action="created",
            actor_id=current_user.id,
            notes="Care plan generated automatically"
        )
        db.add(audit)
        
        await db.commit()
        print(f"✅ Committed all tasks and audit log to database")
        
        # Get the patient's user ID for notification
        print(f"🔍 Looking up patient user ID for notifications")
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.id == encounter.patient_id)
        )
        patient = patient_result.scalars().first()
        
        if patient and patient.user_id:
            print(f"📧 Scheduling notification for patient user {patient.user_id}")
            # Schedule notification in background
            background_tasks.add_task(
                send_care_plan_notification,
                patient.user_id,
                care_plan.careplan_id,
                db
            )
        else:
            print(f"⚠️ Patient user ID not found, skipping notification")
        
        print(f"🔄 Loading care plan with tasks for response")
        result = await db.execute(
            select(models.CarePlan)
            .where(models.CarePlan.careplan_id == care_plan.careplan_id)
            .options(selectinload(models.CarePlan.tasks))
        )
        care_plan = result.scalars().first()
        
        print(f"✅ Care plan generation complete for encounter {encounter_id}")
        return care_plan
        
    except Exception as e:
        print(f"❌ Error generating care plan: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate care plan: {str(e)}"
        )

@router.get("/{careplan_id}", response_model=schemas.CarePlanOut)
async def get_care_plan(
    careplan_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a care plan by ID
    """
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    # Check if user is authorized to view this care plan
    if current_user.role == "patient":
        # Check if care plan belongs to this patient
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != care_plan.patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this care plan"
            )
    elif current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this care plan"
            )
    
    result = await db.execute(
    select(models.CarePlan)
    .where(models.CarePlan.careplan_id == careplan_id)
    .options(selectinload(models.CarePlan.tasks))
)
    return result.scalars().first()

@router.get("/patient/current", response_model=List[schemas.CarePlanOut])
async def get_current_patient_care_plans(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all care plans for the currently logged-in patient
    """
    print(f"🔍 Getting care plans for current patient user: {current_user.id}")
    
    if current_user.role != "patient":
        print(f"❌ User role {current_user.role} not authorized to access current patient endpoint")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can access this endpoint"
        )
    
    # Get the patient record for the current user
    print(f"🔍 Looking up patient record for user {current_user.id}")
    patient_result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )
    patient = patient_result.scalars().first()
    
    if not patient:
        print(f"❌ Patient record not found for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found for current user"
        )
    
    print(f"✅ Found patient record with ID {patient.id}")
    
    # Get all care plans for the patient
    print(f"🔍 Retrieving care plans for patient {patient.id}")
    result = await db.execute(
        select(models.CarePlan)
        .where(models.CarePlan.patient_id == patient.id)
        .options(selectinload(models.CarePlan.tasks))
    )
    care_plans = result.scalars().all()
    print(f"✅ Found {len(care_plans)} care plans for patient {patient.id}")
    
    return care_plans

@router.get("/patient/{patient_id}", response_model=List[schemas.CarePlanOut])
async def get_patient_care_plans(
    patient_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all care plans for a patient
    """
    print(f"🔍 Looking up care plans for patient {patient_id}")
    print(f"👤 User: {current_user.id}, Role: {current_user.role}")
    
    # Check if user is authorized to view this patient's care plans
    if current_user.role == "patient":
        # Check if patient_id matches the current user's patient ID
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient:
            print(f"❌ Patient record not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient record not found for current user"
            )
            
        if patient.id != patient_id:
            print(f"❌ User {current_user.id} attempted to access care plans for patient {patient_id} but is associated with patient {patient.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this patient's care plans"
            )
            
        print(f"✅ Patient {current_user.id} authorized to view their own care plans")
        
    elif current_user.role == "doctor":
        # Check if doctor has treated this patient
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor:
            print(f"❌ Doctor record not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor record not found"
            )
        
        # Check if doctor has any encounters with this patient
        encounter_result = await db.execute(
            select(models.Encounter).where(
                and_(
                    models.Encounter.patient_id == patient_id,
                    models.Encounter.doctor_id == doctor.id
                )
            )
        )
        encounters = encounter_result.scalars().all()
        
        if not encounters:
            print(f"❌ Doctor {doctor.id} has no encounters with patient {patient_id}")
            # Instead of returning 403, return empty list for better UX
            print(f"ℹ️ Returning empty care plan list instead of 403 error")
            return []
            
        print(f"✅ Doctor {doctor.id} authorized to view care plans for patient {patient_id}")
    elif current_user.role != "admin":
        print(f"❌ User role {current_user.role} not authorized to view care plans")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view care plans"
        )
    
    # Get all care plans for the patient with eager loading of tasks
    print(f"🔍 Querying care plans for patient {patient_id}")
    result = await db.execute(
        select(models.CarePlan)
        .where(models.CarePlan.patient_id == patient_id)
        .options(selectinload(models.CarePlan.tasks))
    )
    care_plans = result.scalars().all()
    
    print(f"✅ Found {len(care_plans)} care plans for patient {patient_id}")
    return care_plans

@router.get("/encounter/{encounter_id}", response_model=schemas.CarePlanOut)
async def get_care_plan_by_encounter(
    encounter_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the most recent care plan for an encounter
    """
    print(f"🔍 Looking up care plan for encounter {encounter_id}")
    
    # Get the encounter to check permissions
    encounter_result = await db.execute(
        select(models.Encounter).where(models.Encounter.id == encounter_id)
    )
    encounter = encounter_result.scalars().first()
    
    if not encounter:
        print(f"❌ Encounter {encounter_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter with ID {encounter_id} not found"
        )
    
    # Check if user is authorized to view this encounter's care plan
    if current_user.role == "patient":
        # Check if encounter belongs to this patient
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != encounter.patient_id:
            print(f"❌ Patient {current_user.id} not authorized to view encounter {encounter_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this encounter's care plan"
            )
    elif current_user.role == "doctor":
        # Check if encounter is for a patient of this doctor
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or doctor.id != encounter.doctor_id:
            print(f"❌ Doctor {current_user.id} not authorized to view encounter {encounter_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to view this encounter's care plan"
            )
    
    # Get the care plan for this encounter
    print(f"🔍 Querying care plan for encounter {encounter_id}")
    care_plan_result = await db.execute(
        select(models.CarePlan)
        .where(models.CarePlan.encounter_id == encounter_id)
        .options(selectinload(models.CarePlan.tasks))
        .order_by(models.CarePlan.created_at.desc())
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        print(f"❌ No care plan found for encounter {encounter_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No care plan found for encounter {encounter_id}"
        )
    
    print(f"✅ Found care plan {care_plan.careplan_id} for encounter {encounter_id}")
    return care_plan

@router.put("/{careplan_id}", response_model=schemas.CarePlanOut)
async def update_care_plan(
    careplan_id: int,
    care_plan_update: schemas.CarePlanUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a care plan
    """
    # Debug information
    print(f"🔄 Received request to update care plan {careplan_id}")
    print(f"👤 User: {current_user.id}, Role: {current_user.role}")
    print(f"📝 Update data: {care_plan_update.dict()}")
    
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        print(f"❌ User role {current_user.role} not authorized to update care plans")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can update care plans"
        )
    
    # Get the care plan with eager loading of tasks to avoid lazy loading issues
    print(f"🔍 Looking up care plan with ID {careplan_id}")
    care_plan_result = await db.execute(
        select(models.CarePlan)
        .options(selectinload(models.CarePlan.tasks))
        .where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        print(f"❌ Care plan with ID {careplan_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    print(f"✅ Found care plan {careplan_id} for patient {care_plan.patient_id}")
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        print(f"🔍 Verifying doctor authorization for care plan {careplan_id}")
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        if not encounter:
            print(f"❌ Encounter {care_plan.encounter_id} not found for care plan {careplan_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Encounter not found for care plan"
            )
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor:
            print(f"❌ Doctor record not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor record not found"
            )
        
        if doctor.id != encounter.doctor_id:
            print(f"❌ Doctor {doctor.id} not authorized to update care plan for encounter {encounter.id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this care plan"
            )
        
        print(f"✅ Doctor {doctor.id} is authorized to update care plan {careplan_id}")
    # Update care plan fields
    print(f"🔄 Updating care plan {careplan_id} fields")
    updated_fields = []
    
    if care_plan_update.status is not None:
        care_plan.status = care_plan_update.status
        updated_fields.append("status")
    
    if care_plan_update.patient_friendly_summary is not None:
        care_plan.patient_friendly_summary = care_plan_update.patient_friendly_summary
        updated_fields.append("patient_friendly_summary")
    
    if care_plan_update.clinician_summary is not None:
        care_plan.clinician_summary = care_plan_update.clinician_summary
        updated_fields.append("clinician_summary")
    
    if care_plan_update.plan_metadata is not None:
        care_plan.plan_metadata = care_plan_update.plan_metadata
        updated_fields.append("plan_metadata")
    
    # Update the updated_at timestamp
    care_plan.updated_at = datetime.utcnow()
    
    print(f"✅ Updated fields: {', '.join(updated_fields)}")
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="updated",
        actor_id=current_user.id,
        notes="Care plan updated"
    )
    db.add(audit)
    
    try:
        await db.commit()
        # Refresh with eager loading to avoid lazy loading issues during serialization
        await db.refresh(care_plan)
        print(f"✅ Successfully committed care plan {careplan_id} updates to database")
        
        # Explicitly reload the care plan with all relationships to avoid lazy loading issues
        result = await db.execute(
            select(models.CarePlan)
            .options(selectinload(models.CarePlan.tasks))
            .where(models.CarePlan.careplan_id == careplan_id)
        )
        care_plan = result.scalars().first()
        
    except Exception as e:
        print(f"❌ Error committing care plan updates: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update care plan: {str(e)}"
        )
    
    # If status changed to "active", send notification to patient
    if care_plan_update.status == "active":
        # Get the patient's user ID for notification
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.id == care_plan.patient_id)
        )
        patient = patient_result.scalars().first()
        
        if patient and patient.user_id:
            # Schedule notification in background
            background_tasks.add_task(
                send_care_plan_notification,
                patient.user_id,
                care_plan.careplan_id,
                db
            )
    
    return care_plan

@router.post("/{careplan_id}/tasks", response_model=schemas.CarePlanTaskOut)
async def add_care_plan_task(
    careplan_id: int,
    task: schemas.CarePlanTaskCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a task to a care plan
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can add tasks to care plans"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan with ID {careplan_id} not found"
        )
    
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this care plan"
            )
    
    # Create new task
    new_task = models.CarePlanTask(
        careplan_id=care_plan.careplan_id,
        type=task.type,
        title=task.title,
        description=task.description,
        frequency=task.frequency,
        due_date=task.due_date,
        assigned_to=task.assigned_to,
        requires_clinician_review=task.requires_clinician_review,
        status=task.status or "pending"
    )
    
    db.add(new_task)
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_added",
        actor_id=current_user.id,
        notes=f"Task added: {task.title}"
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(new_task)
    
    return new_task

@router.put("/tasks/{task_id}", response_model=schemas.CarePlanTaskOut)
async def update_care_plan_task(
    task_id: int,
    task_update: schemas.CarePlanTaskUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a care plan task
    """
    # Get the task
    task_result = await db.execute(
        select(models.CarePlanTask).where(models.CarePlanTask.task_id == task_id)
    )
    task = task_result.scalars().first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == task.careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan for task {task_id} not found"
        )
    
    # Check if user is authorized
    if current_user.role == "patient":
        # Patients can only update status of tasks assigned to them
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.user_id == current_user.id)
        )
        patient = patient_result.scalars().first()
        
        if not patient or patient.id != care_plan.patient_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this task"
            )
        
        # Patients can only update status
        if task.assigned_to != "patient":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update tasks assigned to patients"
            )
        
        # Only allow status update
        if task_update.status is not None:
            task.status = task_update.status
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patients can only update task status"
            )
    elif current_user.role == "doctor":
        # Check if doctor is authorized to update this care plan
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this task"
            )
        
        # Doctors can update all fields
        if task_update.title is not None:
            task.title = task_update.title
        
        if task_update.description is not None:
            task.description = task_update.description
        
        if task_update.frequency is not None:
            task.frequency = task_update.frequency
        
        if task_update.due_date is not None:
            task.due_date = task_update.due_date
        
        if task_update.status is not None:
            task.status = task_update.status
        
        if task_update.requires_clinician_review is not None:
            task.requires_clinician_review = task_update.requires_clinician_review
    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this task"
        )
    else:
        # Admins can update all fields
        if task_update.title is not None:
            task.title = task_update.title
        
        if task_update.description is not None:
            task.description = task_update.description
        
        if task_update.frequency is not None:
            task.frequency = task_update.frequency
        
        if task_update.due_date is not None:
            task.due_date = task_update.due_date
        
        if task_update.status is not None:
            task.status = task_update.status
        
        if task_update.requires_clinician_review is not None:
            task.requires_clinician_review = task_update.requires_clinician_review
    
    # Update the updated_at timestamp
    task.updated_at = datetime.utcnow()
    
    # Create audit log
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_updated",
        actor_id=current_user.id,
        notes=f"Task updated: {task.title}"
    )
    db.add(audit)
    
    await db.commit()
    await db.refresh(task)
    
    return task

@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_care_plan_task(
    task_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a care plan task
    """
    # Check if user is authorized (doctor or admin)
    if current_user.role not in ["doctor", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors and admins can delete tasks"
        )
    
    # Get the task
    task_result = await db.execute(
        select(models.CarePlanTask).where(models.CarePlanTask.task_id == task_id)
    )
    task = task_result.scalars().first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID {task_id} not found"
        )
    
    # Get the care plan
    care_plan_result = await db.execute(
        select(models.CarePlan).where(models.CarePlan.careplan_id == task.careplan_id)
    )
    care_plan = care_plan_result.scalars().first()
    
    if not care_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care plan for task {task_id} not found"
        )
    
    # Check if doctor is authorized to update this care plan
    if current_user.role == "doctor":
        # Check if care plan is for a patient of this doctor
        encounter_result = await db.execute(
            select(models.Encounter).where(models.Encounter.id == care_plan.encounter_id)
        )
        encounter = encounter_result.scalars().first()
        
        doctor_result = await db.execute(
            select(models.Doctor).where(models.Doctor.user_id == current_user.id)
        )
        doctor = doctor_result.scalars().first()
        
        if not doctor or not encounter or encounter.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete tasks from this care plan"
            )
    
    # Create audit log before deleting
    audit = models.CarePlanAudit(
        careplan_id=care_plan.careplan_id,
        action="task_deleted",
        actor_id=current_user.id,
        notes=f"Task deleted: {task.title}"
    )
    db.add(audit)
    
    # Delete the task
    await db.delete(task)
    await db.commit()
    
    return None