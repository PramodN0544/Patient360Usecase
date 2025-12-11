# deepgram_token.py
from fastapi import FastAPI
import requests
import os
from pydantic import BaseModel

app = FastAPI()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")  # Store securely in env
PROJECT_ID = os.getenv("DEEPGRAM_PROJECT_ID")     # Also required

class TokenResponse(BaseModel):
    token: str

@app.get("/deepgram-token", response_model=TokenResponse)
def get_deepgram_token():
    """
    Generates a short-lived Deepgram temporary token.
    This token can be safely used by the frontend to authenticate WebSocket streaming.
    """
    url = f"https://api.deepgram.com/v1/projects/{PROJECT_ID}/keys"

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "comment": "temporary browser token",
        "scopes": ["listen:write"]  # required permission for streaming
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

        token = response.json().get("key")

        return TokenResponse(token=token)

    except requests.exceptions.RequestException as e:
        print("Error generating Deepgram token:", e)
        raise RuntimeError("Failed to create Deepgram temporary token")
