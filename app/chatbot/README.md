# Patient360 Chatbot System

## Overview

The Patient360 Chatbot is an AI-powered assistant integrated into the healthcare platform that provides role-specific support for patients, doctors, and hospital administrators. It combines advanced natural language processing with strict healthcare compliance measures to deliver personalized assistance while protecting sensitive patient information.

## Architecture

The chatbot system follows a multi-layered architecture:

### 1. Frontend Layer (`ChatbotComponent.jsx`)
- Floating action button with role-specific labeling
- Expandable chat interface with animated transitions
- Message bubbles with distinct styling for user and bot messages
- Voice input integration using Deepgram
- Suggested prompts based on user role

### 2. API Layer (`api.py`)
- FastAPI endpoints for chat interaction
- User authentication and session management
- Request validation using Pydantic models
- Role-specific suggested prompts endpoint

### 3. Orchestration Layer (`orchestrator.py`)
- Central `ChatOrchestrator` class managing the entire pipeline
- Query classification system
- Data retrieval based on query type and user permissions
- Context building for the language model
- Response generation and validation
- PHI protection mechanisms

### 4. RAG Pipeline (`rag.py`)
- Retrieval Augmented Generation for medical knowledge
- Vector database integration (ChromaDB)
- Document chunking and embedding
- Semantic search capabilities

### 5. Security Modules
- `rbac.py`: Role-Based Access Control for data access
- `phi.py`: PHI masking and de-identification
- `minimum_necessary.py`: Implementation of the HIPAA minimum necessary principle
- `response_guard.py`: Sanitization of LLM responses
- `audit.py`: Comprehensive logging of all interactions
- `consent.py`: Patient consent verification

## Query Processing Pipeline

The chatbot processes user queries through a sophisticated pipeline:

1. **Query Classification**:
   - Uses OpenAI's GPT-4o to classify queries into categories:
     - `data`: Requests for specific patient data
     - `explanation`: Requests for explanations of medical terms
     - `analytics`: Requests for aggregated statistics
     - `recommendation`: Requests for medical advice
     - `action`: Requests to perform actions
   - Supports hybrid classifications (e.g., `data+explanation`)

2. **Data Retrieval**:
   - Role-specific data access:
     - Patients: Can only access their own data
     - Doctors: Can access data for patients they've treated
     - Hospital admins: Can access aggregated hospital data
   - LLM-based data retrieval to understand natural language queries
   - Fallback to enhanced keyword matching with fuzzy search
   - Special handling for wearable device data
   - Date extraction from natural language queries

3. **Context Building**:
   - System prompt construction based on user role and query type
   - Data context formatting with PHI protection
   - Previous conversation history inclusion
   - Role-specific instructions for the language model

4. **PHI Protection**:
   - Multi-layered approach to protecting patient information:
     - Minimum necessary filtering: Only includes data relevant to the query
     - De-identification: Masks PHI elements while preserving medical dates
     - Response sanitization: Checks generated responses for PHI leakage
   - Special handling for dates and identifiers

5. **Response Generation**:
   - Uses OpenAI's GPT-4o model
   - Structured context with system instructions, data, and conversation history
   - Comprehensive error handling

6. **Audit Logging**:
   - Records all interactions including:
     - User ID and role
     - Original query
     - Generated response
     - Query classification
     - Data accessed
     - Full context sent to the LLM

## Role-Specific Functionality

### Patient Mode
- Access to personal health records only
- Simplified explanations of medical terms
- Wearable device data integration
- Medication and appointment information
- Lab result interpretation
- Suggested prompts focused on personal health

### Doctor Mode
- Access to treated patients' data
- Professional medical terminology
- Patient identification from natural language
- Clinical data presentation
- Medical reference information
- Suggested prompts focused on patient care

### Hospital Admin Mode
- Access to aggregated hospital statistics
- Patient demographics analysis
- Appointment and encounter metrics
- Operational insights
- No access to individual patient details
- Suggested prompts focused on hospital operations

## Recent Improvements

### 0. Conversational Streaming Response
- **Problem**: When the chatbot is processing a query, users have no visibility into what's happening in the backend, leading to a poor user experience.
- **Solution**:
  - Implemented a streaming response API that provides real-time progress updates
  - Added user-friendly conversational progress messages that update in place
  - Created a typing indicator that shows the chatbot is generating a response
  - Progress messages automatically disappear when the final answer begins
  - Implemented proper cancellation support for ongoing requests
### 1. Date Redaction Problem Fixed
- **Problem**: The chatbot was redacting all dates, including important medical dates like appointment dates, medication start/end dates, and lab result dates.
- **Solution**:
  - Modified PHI masking to preserve medical dates
  - Updated regex patterns to only target potentially identifiable dates
  - Added dynamic date field detection based on naming patterns
  - Enhanced response sanitization to skip date redaction for medical contexts

### 2. Medication Information Redaction Fixed
- **Problem**: The chatbot was redacting medication information (names, dosages, frequencies), making medication-related queries less useful.
- **Solution**:
  - Added medication field detection to the PHI masker
  - Created a comprehensive list of medication-related field patterns
  - Updated the deidentify_patient_data method to preserve medication information
  - Added tests to verify medication information preservation

### 3. Strict Keyword Matching Problem Fixed
- **Problem**: The chatbot was using exact substring matching for keywords, causing issues with misspellings or variations.
- **Solution**:
  - Implemented LLM-based query understanding
  - Added fallback to enhanced keyword matching with fuzzy search
  - Created a dynamic learning system that expands term mappings
  - Improved handling of typos and alternative phrasings

### 4. Async/Await Implementation Issue Fixed
- **Problem**: There was a runtime warning about a coroutine not being awaited, causing potential issues with the chat API.
- **Solution**:
  - Fixed the async/await implementation in the API layer
  - Added proper await to the _build_context method call in the chat endpoint
  - Ensured all async methods are properly awaited throughout the codebase

## Security and Compliance Features

### HIPAA Compliance
1. **Minimum Necessary Principle**:
   - Only retrieves data relevant to the specific query
   - Filters data based on query classification
   - Implements data scope restrictions by role

2. **PHI Protection**:
   - De-identifies 18 HIPAA identifiers while preserving medical dates and medication information
   - Patient names replaced with "[MASKED]"
   - Special handling for quasi-identifiers
   - Preserves critical medical information while protecting identifiable data

3. **Consent Verification**:
   - Checks patient consent records before data access
   - Verifies appropriate consent types for data categories
   - Blocks access when consent is not granted

4. **Comprehensive Audit Trail**:
   - Logs every interaction with the chatbot
   - Records all data accessed during each interaction
   - Maintains context of each interaction for compliance review

5. **Response Sanitization**:
   - Checks generated responses for potential PHI leakage
   - Applies additional masking to responses if needed
   - Prevents accidental disclosure of sensitive information

## Technical Implementation Details

### Query Classification System
The classification system uses a specialized prompt to GPT-4o:
```
You are a query classifier for a healthcare chatbot. Analyze the query and determine which categories it falls into.

Categories:
- data: Requests for specific patient data (labs, medications, vitals, etc.)
- explanation: Requests for explanations of medical terms or concepts
- analytics: Requests for aggregated statistics or trends
- recommendation: Requests for medical advice or recommendations
- action: Requests to perform an action (schedule appointment, refill medication, etc.)

A query can belong to multiple categories. If it does, join the categories with a plus sign (+).
```

### LLM-Based Data Retrieval
The LLM-based retrieval system:
- Dynamically determines available data categories
- Uses a smaller, faster model (GPT-3.5-turbo)
- Implements caching for performance optimization
- Provides fallback mechanisms for reliability

### Wearable Data Integration
The chatbot includes sophisticated handling of wearable device data:
- Extracts date information from natural language queries
- Supports queries for specific dates, date ranges, or latest readings
- Handles different vital sign types (heart rate, blood pressure, temperature, oxygen)
- Processes both real-time and historical data

### Patient Identification System
For doctor queries, the system includes a sophisticated patient identification system:
1. Extracts potential patient names from natural language
2. Matches against the doctor's patient list
3. Handles ambiguity through:
   - Confidence scoring based on name match quality
   - Recency of interaction to prioritize recently seen patients
   - Contextual clues from the conversation

### Error Handling
The chatbot implements robust error handling:
- Database connection issues
- Missing or incomplete data
- LLM API failures
- Wearable device data retrieval errors
- Patient identification ambiguity
- User-friendly error messages that maintain privacy

## Installation and Setup

### Prerequisites
- Python 3.8+
- FastAPI
- SQLAlchemy
- OpenAI API key
- spaCy with en_core_web_sm model

### Installation Steps
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```

2. Set environment variables:
   ```bash
   export LLM_API_KEY=your_openai_api_key
   ```

3. Run the application:
   ```bash
   uvicorn app.main:app --reload
   ```

### Testing
Run the test script to verify functionality:
```bash
python -m app.chatbot.test_chatbot_fixes
```
## Technical Implementation Details

### Conversational Streaming Response System
The chatbot now includes a streaming response system that provides real-time progress updates in a conversational style:
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│  Frontend       │◄────┤  Streaming API  │◄────┤  Orchestrator   │
│  (React)        │     │  (FastAPI)      │     │  (Python)       │
│                 │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
       ▲                                               │
       │                                               │
       └───────────────────────────────────────────────┘
                    Progress Updates
```

1. The frontend sends a request to the `/api/chatbot/chat-stream` endpoint
2. The backend processes the request in steps, sending progress updates for each step:
   - "I'm thinking about your question..."
   - "Let me search for relevant information in your records..."
   - "I'm preparing your answer now..."
3. The frontend displays a single progress message that updates in place
4. When the final response is ready, the progress message disappears and the answer is shown with a typing effect
## Future Enhancements


1. **Enhanced NLP Capabilities**:
   - Add more sophisticated entity recognition for medical terms
   - Implement a feedback loop to improve the LLM-based retrieval
   - Expand context-aware date preservation logic

2. **Performance Optimizations**:
   - Implement more advanced caching strategies
   - Add batch processing for multiple queries
   - Optimize vector search for RAG pipeline

3. **Additional Features**:
   - Multi-language support
   - Image recognition for medical documents
   - Integration with more wearable devices
   - Proactive health insights and reminders

4. **Expanded Testing**:
   - Add more comprehensive unit tests
   - Implement integration tests with the frontend
   - Create performance benchmarks
   - Add security and compliance testing

## Conclusion

The Patient360 Chatbot represents a sophisticated implementation of AI in healthcare, balancing advanced natural language processing capabilities with strict compliance requirements. Its multi-layered architecture ensures both a seamless user experience and robust protection of sensitive patient information. The recent improvements to date handling and query understanding have significantly enhanced its utility while maintaining HIPAA compliance.