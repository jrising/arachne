from flask import Flask, render_template, request, Response

from bs4 import Tag, NavigableString, BeautifulSoup
import unstructured
from datetime import datetime
import os
import openai
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
openai.api_key = os.getenv('OPENAI_API_KEY')

break_streaming = False

@app.route('/', methods=['GET', 'POST'])
def index():
    # Get current date and time without milliseconds
    current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Get the process ID
    process_id = os.getpid()

    # Create a unique log file name
    log_filename = f'log_{current_time}_{process_id}.log'

    return render_template('index.html', log_filename=log_filename)

def prompt(query):
     return query

def stream(input_text, past_messages, log_filename):
    global break_streaming
    break_streaming = False

    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown."}]
    if past_messages:
        for message in past_messages:
            messages.append(message)
    messages.append({"role": "user", "content": f"{prompt(input_text)}"})
    if len(messages) == 2:
        completion = openai.ChatCompletion.create(model="gpt-4", messages=messages,
                                                  stream=True, max_tokens=2000, temperature=1)
    else:
        completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages,
                                                  stream=True, max_tokens=500, temperature=1)

    response = ""
    for line in completion:
        if 'content' in line['choices'][0]['delta']:
            token = line['choices'][0]['delta']['content']
            response += token
            yield token
        if break_streaming:
            break
    messages.append({"role": "assistant", "content": response})
        
    ## Write all out to logs
    with open(os.path.join("logs", log_filename), 'w') as fp:
        for message in messages:
            if message['role'] == 'system':
                continue
            fp.write(f"**{message['role']}**:\n")
            for line in message['content'].split("\n"):
                fp.write(f"> {line}\n")

@app.route('/stop-stream', methods=['POST'])
def stop_stream():
    global break_streaming
    break_streaming = True
    return {"status": "success", "message": "Streaming stopped"}
        
@app.route('/completion', methods=['GET', 'POST'])
def completion_api():
    global break_streaming
    
    if request.method == "POST":
        data = request.form
        input_text = data['input_text']
        soup = BeautifulSoup(data['past_messages'], 'html.parser')
        past_messages = []
        for div in soup.find_all('div'):
            if div['class'][0] == 'usermessage':
                past_messages.append({"role": "user", "content": div.text.strip()})
            elif div['class'][0] == 'appmessage':
                past_messages.append({"role": "assistant", "content": div.text.strip()})
        ## Drop the last message from the user (added later)
        if past_messages[-1]['role'] == 'user':
            past_messages = past_messages[:-1]

        srm = stream(input_text, past_messages, data['log_filename'])

        return Response(srm, mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

@app.route('/get_ip',  methods=["GET"])
def get_ip():
    return request.remote_addr
    
if __name__ == '__main__':
    app.run(debug=True)
    
