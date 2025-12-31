# Patient360 Role-Based Chatbot System

This module implements a secure, role-based chatbot system for the Patient360 healthcare platform. The system is designed with HIPAA compliance and strict access controls in mind.

## Architecture

The chatbot system follows a backend-first architecture with the following components:

### 1. RBAC Middleware (`rbac.py`)

- Enforces role-based access control for all chatbot interactions
- Determines data scope based on user role (patient, doctor, hospital)
- Validates and filters data access requests
- Ensures users can only access data they are authorized to see

### 2. Chat Orchestrator (`orchestrator.py`)

- Classifies user queries (data, explanation, analytics)
- Resolves data scope based on user role
- Fetches appropriate data from the correct source
- Builds role-safe context for the LLM
- Validates responses for scope violations

### 3. RAG Pipeline (`rag.py`)

- Implements Retrieval-Augmented Generation for medical knowledge
- Uses Chroma vector database for storing and retrieving medical information
- Provides role-appropriate medical explanations
- Ensures no PHI is stored in the vector database

### 4. API Endpoints (`api.py`)

- Provides FastAPI endpoints for chatbot interactions
- Handles authentication and authorization
- Processes chat requests and generates responses
- Logs interactions for audit purposes

### 5. Audit Logging (`audit.py`)

- Implements comprehensive audit logging for all chatbot interactions
- Tracks user queries, data access, and responses
- Essential for HIPAA compliance and security

## Access Rules

The system enforces strict access rules based on user roles:

### Patient
- Can access ONLY their own data
- Labs, medications, encounters, vitals, discharge summaries
- Cannot access other patients or hospital analytics

### Doctor
- Can access ONLY patients they have treated (encounter-based)
- Can view labs, vitals, encounters, notes for those patients
- Cannot access hospital-wide analytics or other doctors' patients

### Hospital
- Can access ONLY aggregated analytics
- Patient-level PHI only
- No clinical notes
- No identifiable lab values

## Chat Flow

1. Receive chat request with JWT
2. Validate authentication and role
3. Resolve data scope (patient_id, doctor_id, hospital_id)
4. Classify user query (data, explanation, analytics)
5. Fetch ONLY allowed data from correct source
6. Build a role-safe context
7. Call LLM with strict instructions
8. Validate response for scope violations
9. Log audit trail
10. Return response

## Usage

The chatbot can be accessed through the `/api/chatbot/chat` endpoint. The frontend component (`ChatbotComponent.jsx`) provides a user-friendly interface for interacting with the chatbot.

### Example API Request

```json
POST /api/chatbot/chat
Authorization: Bearer <jwt_token>

{
  "message": "What were my lab results from last week?",
  "user_id": 123,
  "previous_messages": [
    {
      "role": "user",
      "content": "Hello"
    },
    {
      "role": "assistant",
      "content": "Hello! How can I help you today?"
    }
  ]
}
```

### Example API Response

```json
{
  "response": "Your lab results from last week showed a normal complete blood count (CBC) with all values within the reference range. Your glucose level was 95 mg/dL, which is within the normal range of 70-99 mg/dL.",
  "query_type": "data"
}
```

## Security Considerations

- No direct DB access by LLM
- No PHI inside vector database
- No hallucinated medical advice
- All access enforced BEFORE LLM call
- Comprehensive audit logging