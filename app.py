from flask import Flask, render_template, request, Response

import os, pickle, subprocess, time, random, glob, json, base64
import regex as re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import openai
from dotenv import load_dotenv
from whoosh.index import open_dir
from whoosh import qparser
import numpy as np
from pypdf import PdfReader

from chatwrap import gemini, chatlog
import utils
from utils import create_chat, fillin_training_end, chat_tokens, chat_tokens_each, chat_tokens_one

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
                               log_filename=utils.get_log_filename('coupling'), system="coupling", logofile="coupling.png")
    elif request.headers['Host'] == 'ccecon.existencia.org':
        return render_template('custom-menued.html', title="Climate Change Economics",
                               welcome="Welcome to your virtual teaching assistant. What can I help you with?",
                               log_filename=utils.get_log_filename('ccecon'), system="ccecon", logofile="ccecon.png", menu_html=get_menu())
    else:
        load_filename = request.args.get('load')
        if load_filename:
            pastmessages = chatlog.load_log(utils.get_default_system_message(), glob.glob('logs/log_' + load_filename.replace(' ', '_').replace(':', '-') + "*.log")[0])
            print(pastmessages)
            return render_template('index.html', log_filename=utils.get_log_filename(), menu_html=get_menu(),
                                   pastmessages=pastmessages)
        else:
            return render_template('index.html', log_filename=utils.get_log_filename(), menu_html=get_menu())
 
def stream(input_text, past_messages, log_filename, history_text="",
           custom_system=None, custom_model=None, on_stream_end=None):
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
                model = 'gpt-4o-2024-08-06'
            else:
                model = 'gpt-4o-2024-08-06'

        fillin_training_end(messages, model)
        print(model)
        completion = openai.ChatCompletion.create(model=model, messages=messages,
                                                  stream=True, max_tokens=max(2500, min(4096, chat_tokens_one(input_text) + 500)), temperature=1)
    else:
        if not custom_model or custom_model == 'cheap':
            chatlen = chat_tokens(messages)
            if chatlen >= 15000:
                model = 'gpt-4o-2024-08-06'
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
        chatlog.save_log(os.path.join("logs", log_filename), messages)

    if on_stream_end:
        on_stream_end(response)

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
    print(results)
        
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
        items.append({'date': chunks[0].split(' ')[0], 'message': message, 'filename': chunks[0]})
        
    return render_template('history.html', items=items)

@app.route('/window_closed', methods=['POST'])
def window_closed():
    if request.remote_addr == '127.0.0.1':
        subprocess.Popen(["python", "makelog.py"])
    return '', 200  # Respond with success status

## Other Interfaces

@app.route('/notes', methods=['GET'])
def notes():
    return render_template('notes.html', log_filename=utils.get_log_filename())

@app.route('/save_notes', methods=['POST'])
def save_notes():
    data = request.form
    with open(os.path.join("logs", data['log_filename']), 'w') as fp:
        fp.write("**NOTE**:\n")
        fp.write("> " + data['transcript'])
    return '', 200  # Respond with success status

@app.route('/audio', methods=['GET'])
def audio():
    return render_template('audio.html', log_filename=utils.get_log_filename())

@app.route('/completion_audio', methods=['GET', 'POST'])
def completion_audio():
    if request.method == "POST":
        return Response(completion_api(custom_system=utils.get_default_system_message().replace("Your answer will be rendered as Markdown.", "You are interacting through a speech-to-text and text-to-speech system, which does not handle Markdown. There may be speech misinterpretations in the input text.")), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

def load_document_metadata(docsdir):
    ## Metadata: { pdfpath: { 'next-page': N, 'log-filename': ..., 'context': ... } }
    metadocs = {}
    for root, dirs, files in os.walk(docsdir, followlinks=True):
        for filename in files:
            fullpath = os.path.join(root, filename)
            if os.path.splitext(filename)[1] == '.pdf':
                if fullpath not in metadocs:
                    metadocs[fullpath] = {}
            elif os.path.splitext(filename)[1] == '.json':
                with open(fullpath, 'r') as fp:
                    metadocs[fullpath.replace(".json", ".pdf")] = json.load(fp)

    return metadocs

@app.route('/reader', methods=['GET'])
def reader():
    metadocs = load_document_metadata('readdocs')
    return render_template('reader.html', log_filename=utils.get_log_filename(), metadocs=metadocs)

def log_summary(prompt, response, log_filename):
    new_messages = [{ "role": "user",
                      "content": prompt + "Please write this in a stream appropriate for a text-to-speech reader." },
                    { "role": "assistant",
                      "content": response }]
    if not os.path.exists(os.path.join("logs", log_filename)):
        chatlog.save_log(os.path.join("logs", log_filename), new_messages)
        return

    ## Summarize the previous page
    messages = chatlog.load_log(utils.get_default_system_message(), os.path.join("logs", log_filename))
    # Collect all notes after the page
    notes = []
    while len(messages) > 0 and messages[-1]['role'] == 'user':
        notes.insert(0, messages[-1])
        messages = messages[:-1]

    completion = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=messages + [
            { "role": "user",
              "content": "Now, please provide a short summary of the previous page. Include this in a block as follows: ```[summary here]```." }])
    matches = re.findall(r'```(.*?)```', completion.choices[0].message.content, re.DOTALL)
    
    if len(matches) == 0:
        summary = completion.choices[0].message.content
    else:
        summary = matches[0]

    past_messages = messages[:-2]
    if past_messages:
        past_messages.append({'role': "user", 'content': "Summarize the next page."})
    else:
        past_messages.append({'role': "user", 'content': "Summarize the first page."})
        
    past_messages.append({'role': "assistant", 'content': summary})
    
    chatlog.save_log(os.path.join("logs", log_filename), past_messages + notes + new_messages)

def load_reader_metadata(document, default_log_filename):
    metadatapath = document.replace('.pdf', '.json')
    if os.path.exists(metadatapath):
        with open(metadatapath, 'r') as fp:
            return json.load(fp)
    else:
        return {'log-filename': default_log_filename}
    
@app.route('/completion_reader', methods=['GET', 'POST'])
def completion_reader():
    if request.method == "POST":
        try:
            data = request.form

            metadata = load_reader_metadata(data['document'], data['log_filename'])
            metadatapath = data['document'].replace('.pdf', '.json')

            if 'page' in data:
                nextpage = int(data['page'])
            else:
                nextpage = metadata.get('next-page', 0) + 1
            metadata['next-page'] = nextpage
            with open(metadatapath, 'w') as fp:
                json.dump(metadata, fp, indent=4)
        except:
            return "Cannot load metadata."
            
        try:
            reader = PdfReader(data['document'])

            page = reader.pages[nextpage - 1]
            text = page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False, layout_mode_strip_rotated=False)
        except:
            return "Cannot read PDF."
            
        try:
            ## Process images
            imagetexts = []
            for count, image_file_object in enumerate(page.images):
                if len(image_file_object.data) > 1024 * 1024 * 4:
                    detail = "low"
                else:
                    detail = "high"
                encoded = base64.b64encode(image_file_object.data).decode("utf-8")

                completion = openai.ChatCompletion.create(
                    model="gpt-4o",
                    messages=[
                        { "role": "user",
                          "content": [
                              { "type": "text", "text": "Please describe this image in detail." },
                              { "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{encoded}",
                                    "detail": detail
                                }}]}])

                imagetexts.append(completion.choices[0].message.content)
        except:
            return "Cannot process images."

        try:
            if nextpage == 1:
                prompt = "Here is the first page of a PDF, in a text-based layout:\n===\n" + text + "\n===\n"
            else:
                prompt = f"Here is page {nextpage} of a PDF, in a text-based layout:\n===\n" + text + "\n===\n"
            if len(imagetexts) > 0:
                prompt += "In addition, the page has the following images, as described below:\n===\n" + "\n===\n".join(imagetexts) + "\n===\n"

            if os.path.exists(os.path.join("logs", metadata['log-filename'])):
                messages = chatlog.load_log(utils.get_default_system_message(), os.path.join("logs", metadata['log-filename']))
                history = messages[-2:]
            else:
                history = []
            
            strm = stream(prompt + "Please write this in a stream appropriate for a text-to-speech reader which does not handle symbols well (it names each one). Use only the provided text, and include everything except background images unless there are number-heavy tables, which you can summarize. Incorporate abbreviated footnote material into the text stream and specify references as Name et al. YYYY (for academic papers) or Report Title YYYY (for institution reports).", history, None, on_stream_end=lambda response: log_summary(prompt, response, metadata['log-filename']))

            return Response(strm, mimetype='text/event-stream')
        except:
            return "Cannot create translation."
    else:
        return completion()

@app.route('/completion_reader_summary', methods=['POST'])
def completion_reader_summary():
    data = request.form
    metadata = load_reader_metadata(data['document'], data['log_filename'])
    messages = chatlog.load_log(utils.get_default_system_message(), os.path.join("logs", metadata['log-filename']))

    strm = stream("Now, please provide a summary of the entire document to this point and any notes from me.", messages, None)

    return Response(strm, mimetype='text/event-stream')

@app.route('/reader_document', methods=['GET'])
def reader_document():
    metadata = load_reader_metadata(request.args.get('document'), request.args.get('log_filename'))

    pagenum = metadata.get('next-page', 0)
    reader = PdfReader(request.args.get('document'))
    
    return {"total": len(reader.pages), "nextpage": pagenum+1}

@app.route('/reader_note', methods=['POST'])
def reader_note():
    data = request.form
    metadata = load_reader_metadata(data['document'], data['log_filename'])
    messages = chatlog.load_log(utils.get_default_system_message(), os.path.join("logs", metadata['log-filename']))

    chatlog.save_log(os.path.join("logs", metadata['log-filename']), messages + [{'role': "user", 'content': data['input_text']}])

    return '', 200  # Respond with success status

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
        
    messages = chatlog.load_log(utils.get_default_system_message(), filepath.replace('.pkl', '.log'))
    
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

    log_filename = utils.get_log_filename('news')
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
        
    log_filename = utils.get_log_filename('news')
    return render_template('index.html', welcome=welcome, log_filename=log_filename)

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
    
