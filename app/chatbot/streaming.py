"""
Streaming response implementation for the Patient360 Chatbot.

This module provides streaming response functionality for the chatbot,
allowing the frontend to show progress updates while waiting for the full response.
"""

import json
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List
from fastapi import HTTPException

from app.models import User
from app.chatbot.rbac import DataScope
from app.chatbot.orchestrator import ChatOrchestrator, Message

# Configure logging
logger = logging.getLogger(__name__)

class StreamingChatProcessor:
    """
    Handles streaming chat responses with progress updates.
    """
    
    def __init__(self, orchestrator: ChatOrchestrator):
        """
        Initialize the streaming chat processor.
        
        Args:
            orchestrator: The chat orchestrator to use for processing requests.
        """
        self.orchestrator = orchestrator
    
    async def process_chat_request_stream(
        self,
        user: User,
        message: str,
        previous_messages: List[Message],
        data_scope: DataScope,
        db = None
    ) -> AsyncGenerator[str, None]:
        """
        Process a chat request and stream the response with progress updates.
        
        Args:
            user: The user making the request.
            message: The user's message.
            previous_messages: Previous messages in the conversation.
            data_scope: The user's data scope.
            db: The database session.
            
        Yields:
            Progress updates and the final response.
        """
        try:
            # Step 1: Yield initial progress update
            yield self._format_progress_update("I'm thinking about your question...", 1, 3)
            
            # Step 2: Classify query
            query_type = await self.orchestrator._classify_query(message)
            logger.info(f"Query type: {query_type}")
            
            # Step 3: Yield progress update for data retrieval
            yield self._format_progress_update("Let me search for relevant information in your records...", 2, 3)
            
            # Step 4: Retrieve relevant data
            data, data_accessed = await self.orchestrator._retrieve_data(
                user=user,
                message=message,
                query_type=query_type,
                data_scope=data_scope,
                db=db
            )
            
            # Step 5: Build context with PHI protection
            context = await self.orchestrator._build_context(
                user=user,
                message=message,
                previous_messages=previous_messages,
                query_type=query_type,
                data=data,
                data_scope=data_scope
            )
            
            # Step 6: Yield progress update for response generation
            yield self._format_progress_update("I'm preparing your answer now...", 3, 3)
            
            # Add a small delay to make the progress updates more visible
            await asyncio.sleep(0.5)
            
            # Step 7: Generate response with formatting instructions
            # Create a copy of the context list
            enhanced_context = context.copy()
            
            # Add formatting instructions to the last system message or add a new one
            formatting_instructions = """
Format your response to be easy to read with the following guidelines:
1. Use '**text**' for important information that should be bold
2. Use '__text__' for information that should be underlined
3. Use '!text!' for critical information that should be highlighted
4. Start sections with clear headings followed by a colon
5. Use bullet points (- or *) for lists
6. Include proper spacing between paragraphs
7. Format medical values and units consistently
"""
            
            # Find the last system message or add a new one
            system_message_found = False
            for i in range(len(enhanced_context) - 1, -1, -1):
                if enhanced_context[i]["role"] == "system":
                    enhanced_context[i]["content"] += "\n\n" + formatting_instructions
                    system_message_found = True
                    break
                    
            if not system_message_found:
                # Add a new system message with formatting instructions
                enhanced_context.append({
                    "role": "system",
                    "content": formatting_instructions
                })
            
            response_text = await self.orchestrator._generate_response(enhanced_context)
            
            # Step 8: Sanitize response
            from app.chatbot.response_guard import sanitize_response
            sanitized_response = sanitize_response(response_text)
            
            # Step 9: Validate response
            validated_response = self.orchestrator._validate_response(
                response=sanitized_response,
                data_scope=data_scope
            )
            
            # Step 10: Log the interaction
            from app.chatbot.audit import log_chat_interaction
            await log_chat_interaction(
                user_id=user.id,
                message=message,
                response=validated_response,
                query_type=query_type,
                data_accessed=data_accessed,
                context=context,
                db=db
            )
            
            # Step 11: Yield the final response
            # Ensure data_accessed is always a list
            if isinstance(data_accessed, str):
                data_accessed_list = [data_accessed]
            elif not isinstance(data_accessed, list):
                data_accessed_list = [str(data_accessed)]
            else:
                data_accessed_list = data_accessed
                
            yield self._format_final_response(
                validated_response,
                query_type,
                data_accessed_list
            )
            
        except Exception as e:
            logger.error(f"Error in streaming chat processing: {e}")
            # Yield error message
            yield self._format_error(str(e))
    
    def _format_progress_update(self, message: str, step: int, total_steps: int) -> str:
        """
        Format a progress update as a JSON string.
        
        Args:
            message: The progress message.
            step: The current step number.
            total_steps: The total number of steps.
            
        Returns:
            A JSON string representing the progress update.
        """
        return json.dumps({
            "type": "progress",
            "message": message,
            "step": step,
            "total_steps": total_steps
        })
    
    def _format_final_response(self, response: str, query_type: str, data_accessed: List[str]) -> str:
        """
        Format the final response as a JSON string.
        
        Args:
            response: The response text.
            query_type: The query type.
            data_accessed: The data accessed.
            
        Returns:
            A JSON string representing the final response.
        """
        # Extra safety check to ensure data_accessed is a list
        if not isinstance(data_accessed, list):
            data_accessed = [str(data_accessed)] if data_accessed is not None else []
            
        return json.dumps({
            "type": "response",
            "response": response,
            "query_type": query_type,
            "data_accessed": data_accessed
        })
    
    def _format_error(self, error_message: str) -> str:
        """
        Format an error message as a JSON string.
        
        Args:
            error_message: The error message.
            
        Returns:
            A JSON string representing the error.
        """
        return json.dumps({
            "type": "error",
            "message": f"Error processing chat request: {error_message}"
        })