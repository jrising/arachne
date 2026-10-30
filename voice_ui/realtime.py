import os
import httpx

def create_realtime_secret(system_message: str):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    response = httpx.post(
        "https://api.openai.com/v1/realtime/client_secrets",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "expires_after": {"anchor": "created_at", "seconds": 600},
            "session": {
                "type": "realtime",
                "model": "gpt-realtime",
                "instructions": system_message,
                "audio": {
                    "input": {
                        "transcription": {
                            "model": "gpt-4o-mini-transcribe"
                        }
                    },
                    "output": {"voice": "marin"},
                },
            },
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()
