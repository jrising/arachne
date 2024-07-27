from flask import Flask, render_template, request, Response

import os, pickle, subprocess, time, random
import regex as re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import openai
from dotenv import load_dotenv
from whoosh.index import open_dir
from whoosh import qparser
import numpy as np

from wrappers import gemini
from utils import get_log_filename, create_chat, fillin_training_end, chat_tokens, chat_tokens_each, chat_tokens_one

do_tts = False

if do_tts:
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
                               log_filename=get_log_filename('coupling'), system="coupling", logofile="coupling.png")
    elif request.headers['Host'] == 'ccecon.existencia.org':
        return render_template('custom-menued.html', title="Climate Change Economics",
                               welcome="Welcome to your virtual teaching assistant. What can I help you with?",
                               log_filename=get_log_filename('ccecon'), system="ccecon", logofile="ccecon.png", menu_html=get_menu())
    else:
        return render_template('index.html', log_filename=get_log_filename(), menu_html=get_menu())
 
def stream(input_text, past_messages, log_filename, history_text="",
           custom_system=None, custom_model=None):
    global break_streaming
    break_streaming = False

    messages = create_chat(input_text, past_messages, history_text=history_text, custom_system=custom_system)
    
    if len(messages) < 4:
        if custom_model == 'cheap':
            model = 'gpt-4o-mini'
        elif custom_model:
            model = custom_model
        else:
            chatlen = chat_tokens(messages)
            if chatlen <= 3000:
                model = 'gpt-4o'
            else:
                model = 'gpt-4o'

        fillin_training_end(messages, model)
        print(model)
        completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                  stream=True, max_tokens=max(2500, min(4096, chat_tokens_one(input_text) + 500)), temperature=1)
    else:
        if not custom_model or custom_model == 'cheap':
            chatlen = chat_tokens(messages)
            if chatlen >= 15000:
                model = 'gpt-4o'
            elif chatlen <= 3000:
                model = 'gpt-4o-mini'
            else:
                model = 'gpt-4o-mini'
        else:
            model = custom_model

        if custom_model:
            fillin_training_end(messages, model)
            completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                      stream=True, max_tokens=500, temperature=1)
        else:
            try:
                fillin_training_end(messages, model)
                completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                          stream=True, max_tokens=2500, temperature=1)
            except openai.error.InvalidRequestError as ex:
                if model == 'gpt-4o':
                    raise ex
                fillin_training_end(messages, 'gpt-4o')
                completion = openai.ChatCompletion.create(model='gpt-4o', messages=messages,
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
            before_user = True
            for message in messages:
                if message['role'] == 'system':
                    continue
                messagetext = message['content']
                if message['role'] == 'assistant' and before_user:
                    messagetext = messagetext[:100]
                else:
                    before_user = False

                fp.write(f"**{message['role']}**:\n")
                for line in messagetext.split("\n"):
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
        
def completion_api(custom_system=None, custom_model=None, custom_context=""):
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

    if custom_context:
        history_text = custom_context
    else:
        histchoice = random.choice(["history", "gemini", "none"])
        if histchoice == 'history':
            history_text = data.get('history', '')
            if history_text:
                history_text = history_text.replace("\n\n", "\n").replace("\n\n", "\n")
                history_text = "Below are selected log entries of past conversations, as part of an experimental AI memory system. They may have no bearing on the chat.\n" + history_text
        elif histchoice == 'gemini':
            results = get_logs_raw(input_text)
            history_text = gemini.single_prompt("The following query has been submitted to a super-intelligent AI assistant named Arachne, which you support as a memory system:\n===\n" + input_text + "\n===\nThe following past discussion synopses have been retrieved, which may relate to this query:\n===\n" + "\n===\n".join([result['path'][9:19] + ' ' + result['path'][20:28].replace('-', ':') + ': ' + result['content'] for result in results]) + "\n===\nPlease excerpt and summarize any entries that are relevant to the query.")
            print(history_text)
        else:
            history_text = ""

    return stream(input_text, past_messages, data['log_filename'], history_text,
                  custom_system=custom_system, custom_model=custom_model)

## Custom AIs

@app.route('/completion_custom', methods=['GET', 'POST'])
def completion_custom():
    if request.method == "POST":
        custom_system = open('prompts/' + request.form['system'] + '.md', 'r').read()
        custom_context = ""
        if request.form.get('menu-option'):
            if request.headers['Host'] == 'ccecon.existencia.org':
                with open(os.path.join('ccecon', request.form.get('menu-option')), 'r') as fp:
                    custom_context = "The question below may pertain to the following material from the course:\n===\n" + fp.read() + "\n===\n"
        return Response(completion_api(custom_system, "cheap", custom_context=custom_context), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

## Log Management

def get_logs_raw(query=None):
    if query:
        ix = open_dir("database/whoosh")
        with ix.searcher() as searcher:
            og = qparser.OrGroup.factory(0.9)
            qp = qparser.QueryParser("content", ix.schema, group=og)
            qp.add_plugin(qparser.FuzzyTermPlugin())
            parsed = qp.parse(query)
            results = searcher.search(parsed, limit=10)

            allres = []
            for result in results:
                with open(os.path.join("database", result['path'])) as fp:
                    allres.append(dict(path=result['path'], line=result['line'], content=fp.read()))

            return allres
    else:
        ## Get the last 10 lines from running.log
        size = os.path.getsize("database/logs/running.log")
        with open("database/logs/running.log", 'rb') as fp:
            if size > 2048:
                fp.seek(-2048, 2)
            lines = fp.readlines()[1:][-10:]

        return [dict(path='running.log', line=line.decode(), content=line) for line in lines]

@app.route('/get-logs',  methods=['GET', 'POST'])
def get_logs():
    if request.method == "POST":
        query = request.form['query']
        results = get_logs_raw(query)
        lines = [result['path'][9:19] + ' ' + result['path'][20:28].replace('-', ':') + ': ' + result['line'] for result in results]
    else:
        results = get_logs_raw()
        lines = [result['line'] for result in results]
        
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
    root = request.args.get('root')
    if request.headers['Host'] == 'ccecon.existencia.org':
        if root is None:
            items = [(entry, entry) for entry in os.listdir('ccecon')]
        else:
            # Check that this is a subdirectory of ccecon
            topdir = os.path.abspath('ccecon')
            askdir = os.path.abspath(os.path.join('ccecon', root))
            if os.path.commonprefix([topdir, askdir]) != topdir:
                items = []
            elif os.path.isdir(askdir):
                items = [(os.path.join(root, entry), entry) for entry in os.listdir(askdir)]
            else:
                items = []

        return render_template('menu-entry.html', items=items)
                
    if root is None:
        items = [("~/", "File System"), ("tikiwiki", "TikiWiki"), ("mediawiki", "MediaWiki"), ("planet", "Planet Content")]
    else:
        parts = root.split('::')
        if len(parts) == 2:
            root = parts[0]
            page = int(parts[1])
        else:
            page = 1
            
        if root == 'missing':
            items = []
        elif root[0] == "~":
            if os.path.isdir(os.path.expanduser(root)):
                try:
                    items = [(os.path.join(root, entry), entry) for entry in os.listdir(os.path.expanduser(root))]
                except:
                    items = []
            else:
                items = []
        else:
            items = [("missing", "Planet/Wiki content not implemented yet.")]

    if len(items) > 20 and page != 'all':
        items = items[((page-1)*19):(page*19 + 1)] + [(root + '::' + str(page + 1), 'More...')]

    return render_template('menu-entry.html', items=items)
    
## Other tools

@app.route('/get_ip', methods=["GET"])
def get_ip():
    return request.remote_addr

@app.route("/news", methods=["GET"])
def news():
    from memory import bulletin, news
    nowstr = request.args.get('date')
    if nowstr is not None:
        now = datetime.strptime(nowstr, "%Y-%m-%d")
    else:
        now = datetime.now()

    engine, items = bulletin.get_engine_items()

    while not os.path.exists(news.get_daily_filepath(now).replace('.pkl', '.log')):
        print("Nothing available for " + news.get_daily_filepath(now).replace('.pkl', ''))
        now -= timedelta(days=1)
    prev = now - timedelta(days=1)

    filepath = news.get_daily_filepath(now)
    with open(filepath.replace('.pkl', '-texts.pkl'), 'rb') as fp:
        texts = pickle.load(fp)
        
    messages = load_log(filepath.replace('.pkl', '.log'))
    
    welcome = now.strftime('# Daily Bulletin: %Y-%m-%d') + prev.strftime(' (<a href="/news?date=%Y-%m-%d">Previous</a>)\n\n') + process_bulletin(messages[0]['content'], texts, lambda ids: bulletin.incremenet_uses(engine, items, ids, 1))

    return render_template('index.html', welcome=welcome, log_filename=filepath.replace('.pkl', '.log'))

@app.route("/news-now", methods=["GET"])
def news_now():
    print("Preparing memo...")
    from memory import bulletin
    
    engine, items = bulletin.get_engine_items()
    print("Retrieving items...")
    collect.collect_feeds(engine, items)

    print("Evaluating documents...")
    texts = bulletin.get_input_text(engine, items, 20)
    idtokens = dict(zip(texts.keys(), list(chat_tokens_each(texts.values()))))
    for id, tokens in idtokens.items():
        allowed_tokens = 100 + np.random.exponential(100)
        if tokens > allowed_tokens:
            texts[id] = texts[id][:int(len(texts[id]) * (allowed_tokens / tokens))]
    print(texts)
    for num in chat_tokens_each(texts.values()):
        print(num)
    
    prompt = open('prompts/news.md', 'r').read()
    prompt = prompt.replace("[CONTEXT]", "\n\n".join([f"ID: {ii}\n{text}" for ii, text in texts.items()]))

    log_filename = get_log_filename('news')
    welcome = ""
    for content in stream(prompt, [], log_filename):
        welcome += content

    welcome2 = process_bulletin(welcome, texts, lambda ids: bulletin.incremenet_uses(engine, items, ids, 1))

    return render_template('index.html', welcome=welcome2, log_filename=log_filename)

@app.route("/news-nonet", methods=["GET"])
def news_nonet():
    from memory import bulletin

    engine, items = bulletin.get_engine_items()

    print("Evaluating documents...")
    texts = bulletin.get_input_text(engine, items, 20)

    welcome = "# Daily Memo"
    for ii, text in texts.items():
        welcome += "\n - " + generate_news_links(ii, texts)
        entries = text.split('\n')
        welcome += "\n - " + "\n - ".join(entries[2:])

    bulletin.incremenet_uses(engine, items, texts.keys(), 1 / 3. - 0.1)
        
    log_filename = get_log_filename('news')
    return render_template('index.html', welcome=welcome, log_filename=log_filename)

def load_log(filepath):
    messages = []
    current_role = None
    current_message = None
    with open(filepath, 'r') as fp:
        for line in fp:
            if line[:2] == '**':
                if current_role is not None:
                    messages.append({'role': current_role, 'content': current_message})
                current_role = line[2:-3]
                current_message = ""
            elif line[:2] == '> ':
                current_message += line[2:]

    messages.append({'role': current_role, 'content': current_message})
    return messages

def process_bulletin(welcome, texts, handle_ids):
    # Look for numbers in brackets
    pattern = re.compile(r'\[(\d+)\]')
    ids = [int(match.group(1)) for match in pattern.finditer(welcome)]
    handle_ids(ids)
    return pattern.sub(lambda match: generate_news_links(int(match.group(1)), texts), welcome)

def generate_news_links(index, texts):
    entries = texts[index].split('\n')
    feed = entries[0][6:]
    url = entries[1][6:]
    pubtime = entries[2][len('Published at: '):]
    return render_template('news-link.html', feed=feed, url=url, pubtime=pubtime, link_id=index)

@app.route("/vote-updown", methods=["GET"])
def vote_updown():
    from memory import bulletin
    id = int(request.args.get('id'))
    prob = float(request.args.get('prob'))
    bulletin.vote_updown(id, prob)
    return "Success."

if __name__ == '__main__':
    app.run(debug=True)
    
