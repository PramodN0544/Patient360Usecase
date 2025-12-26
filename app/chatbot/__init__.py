"""
Patient360 Role-Based Chatbot System.

This package implements a secure, role-based chatbot system for the Patient360 healthcare platform.
It enforces strict access controls based on user roles and ensures HIPAA compliance.
"""

# Import main components for easier access
from app.chatbot.api import router
from app.chatbot.rag import RAGPipeline
from app.chatbot.rbac import DataScope
from app.chatbot.orchestrator import ChatOrchestrator
from app.chatbot.audit import log_chat_interaction