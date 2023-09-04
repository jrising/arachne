from flask import Flask, render_template, request, Response

from bs4 import BeautifulSoup
from datetime import datetime
import os, pickle, subprocess
import openai
from dotenv import load_dotenv
from whoosh.index import open_dir
from whoosh import qparser

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

def stream(input_text, past_messages, log_filename, history_text=""):
    global break_streaming
    break_streaming = False
    
    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Most recent training data: 2021-09; Current time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]

    if history_text:
        messages.append({"role": "assistant", "content": history_text})
    
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

        if past_messages:
            input_text = data['input_text']
        else:
            if data['preamble'] == 'none':
                preamble = ""
            else:
                preamble = open('prompts/' + data['preamble'] + '.md', 'r').read()
            input_text = preamble + data['input_text']

        history_text = data.get('history', '')
        if history_text:
            history_text = history_text.replace("\n\n", "\n").replace("\n\n", "\n")
            history_text = "Below are selected log entries of past conversations, as part of an experimental AI memory system. They may have no bearing on the chat.\n" + history_text
            print(history_text)
            
        srm = stream(input_text, past_messages, data['log_filename'], history_text)

        return Response(srm, mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

@app.route('/get_ip',  methods=["GET"])
def get_ip():
    return request.remote_addr

@app.route('/get-logs',  methods=['GET', 'POST'])
def get_logs():
    if request.method == "POST":
        query = request.form['query']
        print(query)
        ix = open_dir("database/whoosh")
        with ix.searcher() as searcher:
            og = qparser.OrGroup.factory(0.9)
            qp = qparser.QueryParser("content", ix.schema, group=og)
            qp.add_plugin(qparser.FuzzyTermPlugin())
            parsed = qp.parse(query)
            results = searcher.search(parsed, limit=10)
            
            lines = [result['path'][9:19] + ' ' + result['path'][20:28].replace('-', ':') + ': ' + result['line'] for result in results]
    else:
        ## Get the last 10 lines from running.log
        size = os.path.getsize("database/logs/running.log")
        with open("database/logs/running.log", 'rb') as fp:
            if size > 2048:
                fp.seek(-2048, 2)
            lines = fp.readlines()[1:][-10:]

        lines = [line.decode() for line in lines]
        
    ## Replace lines with titles, where available
    if os.path.exists("database/logs/titles.pkl"):
        with open("database/logs/titles.pkl", 'rb') as fp:
            titles = pickle.load(fp)
    else:
        titles = {}
        
    items = []
    for line in lines:
        chunks = line.split(': ', maxsplit=1)
        message = chunks[1]
        if chunks[0] in titles:
            message = titles[chunks[0]]
        items.append({'date': chunks[0].split(' ')[0], 'message': message})
        
    return render_template('history.html', items=items)

@app.route('/window_closed', methods=['POST'])
def window_closed():
    if request.remote_addr == '127.0.0.1':
        subprocess.Popen(["python", "makelog.py"])
    return '', 200  # Respond with success status

@app.route('/notes', methods=['GET'])
def notes():
    # Get current date and time without milliseconds
    current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Get the process ID
    process_id = os.getpid()

    # Create a unique log file name
    log_filename = f'log_{current_time}_{process_id}.log'

    return render_template('notes.html', log_filename=log_filename)

@app.route('/save_notes', methods=['POST'])
def save_notes():
    data = request.form
    with open(os.path.join("logs", data['log_filename']), 'w') as fp:
        fp.write("**NOTE**:\n")
        fp.write("> " + data['transcript'])
    return '', 200  # Respond with success status
        
if __name__ == '__main__':
    app.run(debug=True)
    
