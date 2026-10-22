from flask import Flask, render_template, request, Response, send_file

from bs4 import BeautifulSoup
import random, base64, io
import os, json, hashlib, requests
from urllib.parse import urljoin
from datetime import datetime
from xai_sdk import Client
from xai_sdk.chat import user, system, assistant
from dotenv import load_dotenv
from memory import integration_short_term, integration_long_term
from memory import store_sqlalchemy, model_openai, index_whoosh, long_term

## . venv2026/bin/activate
## flask --app appx-meta run --port=8081

include_images = True

app = Flask(__name__)

load_dotenv()
client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    timeout=3600
)

break_streaming = False
last_conversation = None
last_imageprompt = None
last_imagebytes = None
last_imagetool = None

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('illustrated.html')

def stream(input_text, past_messages):
    global break_streaming
    break_streaming = False

    system_message = "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her). In this project, you are asked to clearly, concretely, and creatively improve an AI-based sex bot."

    chat = client.chat.create(model="grok-4.3")
    chat.append(system(system_message))

    if past_messages:
        for message in past_messages:
            if message['role'] == 'user':
                chat.append(user(message['content']))
            elif message['role'] == 'assistant':
                chat.append(assistant(message['content']))
            else:
                print("Unknown role: " + message['role'])
    
    chat.append(user(input_text))
    response = chat.stream()

    for response, chunk in chat.stream():
        yield chunk.content
        if break_streaming:
            break

@app.route('/stop-stream', methods=['POST'])
def stop_stream():
    global break_streaming
    break_streaming = True
    return {"status": "success", "message": "Streaming stopped"}

def get_past_messages(data):
    soup = BeautifulSoup(data['past_messages'], 'html.parser')
    past_messages = []
    for div in soup.find_all('div'):
        print(div['class'])
        if div['class'][0] == 'usermessage':
            past_messages.append({"role": "user", "content": div.text.strip()})
        elif div['class'][0] == 'appmessage':
            past_messages.append({"role": "assistant", "content": div.text.strip()})

    return past_messages

@app.route('/completion', methods=['GET', 'POST'])
def completion_api():
    global last_conversation
    if request.method == "POST":
        data = request.form
        past_messages = get_past_messages(data)
        last_conversation = past_messages
        return Response(stream(data['input_text'], past_messages), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
    
