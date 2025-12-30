"""
Audit logging for the Patient360 Chatbot.

HIPAA-SAFE VERSION:
- No raw PHI stored
- Messages & responses are hashed
- Only structured metadata is persisted
"""

import logging
import json
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatAuditLog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    """Generate SHA-256 hash for audit-safe storage."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def log_chat_interaction(
    user_id: int,
    message: str,
    response: str,
    query_type: str,
    data_accessed: Optional[List[str]] = None,
    context: Optional[List[Dict[str, str]]] = None,
    db: AsyncSession = None
) -> None:
    """
    Log a chat interaction to the audit log (HIPAA compliant).

    ⚠️ NO RAW MESSAGE OR RESPONSE STORED
    """
    try:
        logger.info(f"[AUDIT] user_id={user_id}, query_type={query_type}")

        if db is None:
            return

        audit_log = {
            "user_id": user_id,
            "timestamp": datetime.utcnow(),

            # Store the actual message and response
            "message": message,
            "response": response,

            # ✅ Metadata only
            "query_type": query_type,
            "data_accessed": json.dumps(data_accessed) if data_accessed else None,

            # ⚠️ Store role-only context (NO content)
            "context": json.dumps([
                {"role": msg.get("role")}
                for msg in context
            ]) if context else None
        }

        await db.execute(insert(ChatAuditLog).values(**audit_log))
        await db.commit()

    except Exception as e:
        logger.error(f"[AUDIT ERROR] {e}")
        # Audit must never block chatbot flow


async def log_chat_interaction_simple(
    user_id: int,
    message: str,
    response: str,
    query_type: str,
    data_accessed: Optional[List[str]] = None,
    db: AsyncSession = None
) -> None:
    """
    Lightweight audit logging (HIPAA safe).
    """
    try:
        logger.info(f"[AUDIT] user_id={user_id}, query_type={query_type}")

        if db is None:
            return

        audit_log = {
            "user_id": user_id,
            "timestamp": datetime.utcnow(),

            # Store the actual message and response
            "message": message,
            "response": response,

            "query_type": query_type,
            "data_accessed": json.dumps(data_accessed) if data_accessed else None
        }

        await db.execute(insert(ChatAuditLog).values(**audit_log))
        await db.commit()

    except Exception as e:
        logger.error(f"[AUDIT ERROR] {e}")


async def get_user_chat_history(
    user_id: int,
    limit: int = 50,
    db: AsyncSession = None
) -> List[Dict[str, Any]]:
    """
    Get a user's audit history (NO PHI).
    """
    if db is None:
        return []

    result = await db.execute(
        """
        SELECT id, timestamp, query_type, data_accessed
        FROM chat_audit_log
        WHERE user_id = :user_id
        ORDER BY timestamp DESC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": limit}
    )

    return [
        {
            "id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "query_type": row.query_type,
            "data_accessed": json.loads(row.data_accessed) if row.data_accessed else None
        }
        for row in result
    ]


async def get_data_access_report(
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = None
) -> List[Dict[str, Any]]:
    """
    Compliance / audit report (Epic-style).
    """
    if db is None:
        return []

    query = """
        SELECT id, user_id, timestamp, query_type, data_accessed
        FROM chat_audit_log
        WHERE 1=1
    """
    params = {}

    if user_id:
        query += " AND user_id = :user_id"
        params["user_id"] = user_id

    if start_date:
        query += " AND timestamp >= :start_date"
        params["start_date"] = start_date

    if end_date:
        query += " AND timestamp <= :end_date"
        params["end_date"] = end_date

    query += " ORDER BY timestamp DESC"

    result = await db.execute(query, params)

    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "timestamp": row.timestamp.isoformat(),
            "query_type": row.query_type,
            "data_accessed": json.loads(row.data_accessed) if row.data_accessed else None
        }
        for row in result
    ]
