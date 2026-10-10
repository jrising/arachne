import os, random
import traceback
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
import httpx
import utils

load_dotenv()

app = Flask(__name__)

# Ensure your key exists
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("❌ ERROR: OPENAI_API_KEY is missing from your .env file!")

@app.route('/')
def index():
    return render_template('realtime.html')

@app.route('/session', methods=['GET'])
def get_session():
    """Fetches an ephemeral WebRTC token from OpenAI with explicit terminal logging."""
    if not OPENAI_API_KEY:
        return jsonify({"error": "Server API key missing"}), 500

    try:
        print("--- Initiating token request to OpenAI ---")
        
        # Production endpoint structure for Realtime WebRTC sessions
        url = "https://api.openai.com/v1/realtime/client_secrets"
        
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "expires_after": { "anchor": "created_at", "seconds": 600 },
            "session": {
                "type": "realtime",
                "model": "gpt-realtime", # Points to OpenAI's production real-time model
                "instructions": utils.get_default_system_message(),
                "audio": {
                    "output": { "voice": "marin" } # coral, sage, shimmer
                }
            }
        }

        response = httpx.post(url, headers=headers, json=payload, timeout=10.0)
        
        # Log response status to terminal
        print(f"OpenAI Response Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ OpenAI Error Payload: {response.text}")
            return jsonify({"error": f"OpenAI rejected request: {response.text}"}), response.status_code

        data = response.json()
        print("✅ Ephemeral token successfully retrieved from OpenAI.")
        return jsonify(data)

    except Exception as e:
        print("❌ Server Crash Internal Error:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
