from flask import Flask, render_template, request, Response

import regex as re
from bs4 import BeautifulSoup
from datetime import datetime
import os, pickle, subprocess, time
import openai, tiktoken
from dotenv import load_dotenv
from whoosh.index import open_dir
from whoosh import qparser

try:
    from TTS.api import TTS
    import pygame
    import threading
    import queue

    tts = TTS("tts_models/en/ljspeech/glow-tts")
    pygame.init()
except:
    print("No text-to-speech functionality.")
    pass

app = Flask(__name__)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
openai.api_key = os.getenv('OPENAI_API_KEY')

break_streaming = False

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.headers['Host'] == 'coupling.existencia.org':
        return render_template('custom.html', title="Coupling Human to Natural Systems",
                               welcome="Welcome to your virtual teaching assistant. What can I help you with?",
                               log_filename="", system="coupling")
    elif request.headers['Host'] == 'ccecon.existencia.org':
        return render_template('custom.html', title="Climate Change Economics",
                               welcome="Welcome to your virtual teaching assistant. What can I help you with?",
                               log_filename="", system="ccecon")
    else:
        return render_template('index.html', log_filename=get_log_filename(), menu_html=get_menu())
 
def stream(input_text, past_messages, log_filename, history_text="",
           custom_system=None, custom_model=None):
    global break_streaming
    break_streaming = False

    if custom_system:
        messages = [{"role": "system", "content": custom_system}]
    else:
        messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Most recent training data: 2021-09; Current time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]

    if history_text:
        messages.append({"role": "assistant", "content": history_text})

    if past_messages:
        for message in past_messages:
            messages.append(message)
    messages.append({"role": "user", "content": input_text})
    if len(messages) < 4:
        if custom_model:
            model = custom_model
        else:
            chatlen = chat_tokens(messages)
            if chatlen <= 3000:
                model = 'gpt-4'
            else:
                model = 'gpt-4-1106-preview'
            
        completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                  stream=True, max_tokens=2500, temperature=1)
    else:
        if custom_model:
            model = custom_model
        else:
            chatlen = chat_tokens(messages)
            if chatlen >= 15000:
                model = 'gpt-4-1106-preview'
            elif chatlen <= 3000:
                model = 'gpt-3.5-turbo'
            else:
                model = 'gpt-3.5-turbo-16k'

        if custom_model:
            completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                      stream=True, max_tokens=500, temperature=1)
        else:
            try:
                completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                          stream=True, max_tokens=2500, temperature=1)
            except openai.error.InvalidRequestError as ex:
                if model == 'gpt-4-1106-preview':
                    raise ex
                completion = openai.ChatCompletion.create(model='gpt-4-1106-preview', messages=messages,
                                                          stream=True, max_tokens=2500, temperature=1)

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
    if log_filename:
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
def completion():
    if request.method == "POST":
        return Response(completion_api(), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')
        
def completion_api(custom_system=None, custom_model=None):
    global break_streaming
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
        if data.get('preamble', 'none') == 'none':
            preamble = ""
        else:
            if data.get('context', '') != '' and os.path.exists('prompts/' + data['preamble'] + '-context.md'):
                preamble = open('prompts/' + data['preamble'] + '-context.md', 'r').read()
                preamble = preamble.replace("[CONTEXT]", data.get('context', ''))
            else:
                preamble = open('prompts/' + data['preamble'] + '.md', 'r').read()
        input_text = preamble + data['input_text']

    history_text = data.get('history', '')
    if history_text:
        history_text = history_text.replace("\n\n", "\n").replace("\n\n", "\n")
        history_text = "Below are selected log entries of past conversations, as part of an experimental AI memory system. They may have no bearing on the chat.\n" + history_text

    return stream(input_text, past_messages, data['log_filename'], history_text,
                  custom_system=custom_system, custom_model=custom_model)

## Custom AIs

@app.route('/completion_custom', methods=['GET', 'POST'])
def completion_custom():
    if request.method == "POST":
        custom_system = open('prompts/' + request.form['system'] + '.md', 'r').read()
        return Response(completion_api(custom_system, "gpt-4-1106-preview"), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

## Log Management

@app.route('/get-logs',  methods=['GET', 'POST'])
def get_logs():
    if request.method == "POST":
        query = request.form['query']
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

def get_log_filename():
    # Get current date and time without milliseconds
    current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Get the process ID
    process_id = os.getpid()

    # Create a unique log file name
    return f'log_{current_time}_{process_id}.log'

## Other Interfaces

@app.route('/notes', methods=['GET'])
def notes():
    return render_template('notes.html', log_filename=get_log_filename())

@app.route('/save_notes', methods=['POST'])
def save_notes():
    data = request.form
    with open(os.path.join("logs", data['log_filename']), 'w') as fp:
        fp.write("**NOTE**:\n")
        fp.write("> " + data['transcript'])
    return '', 200  # Respond with success status

@app.route('/audio', methods=['GET'])
def audio():
    return render_template('audio.html', log_filename=get_log_filename())

@app.route('/completion_audio', methods=['GET', 'POST'])
def completion_audio():
    if request.method == "POST":
        return Response(play_audio(completion_api()), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

## Generates the waves
def tts_consumer(qqin, qqout):
    ii = 0
    while True:
        sentence = qqin.get()
        if sentence is None or break_streaming:
            break

        tts.tts_to_file(text=sentence, file_path="waves/tts" + str(ii) + ".wav")
        qqout.put("waves/tts" + str(ii) + ".wav")
        
        qqin.task_done()  # Signal that a formerly enqueued task is complete
        ii += 1

def play_audio(srm):
    qqin = queue.Queue()
    qqout = queue.Queue()
    consumer_thread = threading.Thread(target=tts_consumer, args=(qqin, qqout))
    consumer_thread.start()

    channel = pygame.mixer.find_channel()

    currentinput = ""
    for token in srm:
        currentinput += token
        if re.search(r"[.!?] ", currentinput):
            sentences = re.split(r"[.!?] ", currentinput)
            for sentence in sentences[:-1]:
                qqin.put(sentence)
            currentinput = sentences[-1]
        yield token

        if break_streaming:
            break

        if not qqout.empty():
            if not channel.get_queue():
                my_sound = pygame.mixer.Sound(qqout.get())
                channel.queue(my_sound)

    if break_streaming:
        channel.quit()
                
    if currentinput:
        qqin.put(currentinput)

    while (not qqin.empty() or not qqout.empty()) and not break_streaming:
        if not qqout.empty() and not channel.get_queue():
            my_sound = pygame.mixer.Sound(qqout.get())
            channel.queue(my_sound)
        time.sleep(0.2)

    if break_streaming:
        channel.quit()
        
    qqin.put(None)
    while channel.get_busy():
        time.sleep(0.2)
        
    consumer_thread.join()

## Hierarchical Memory

@app.route("/get_menu", methods=["GET"])
def get_menu():
    if request.query_string[:5] == b'root=':
        root = str(request.query_string[5:], encoding='utf8')
    else:
        root = None
    #root = request.form.get("root", None)
    if root is None:
        items = [("~/", "File System"), ("tikiwiki", "TikiWiki"), ("mediawiki", "MediaWiki"), ("planet", "Planet Content")]
    elif root[0] == "~":
        items = [(os.path.join(root, entry), entry) for entry in os.listdir(os.path.expanduser(root))]
    else:
        items = [("missing", "Planet Content not implemented yet.")]

    return render_template('menu-entry.html', items=items)
    
## Other tools

@app.route('/get_ip', methods=["GET"])
def get_ip():
    return request.remote_addr

def chat_tokens(messages):
    """Returns the number of tokens for a chat."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = 0
    for message in messages:
        num_tokens += len(encoding.encode(message['content'])) + 4
    return num_tokens

if __name__ == '__main__':
    app.run(debug=True)
    
