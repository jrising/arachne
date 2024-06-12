import os, pickle, json, datetime
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from memory import feeds, news
import utils

def get_texts(engine, items):
    print("Retrieving items...")
    feeds.collect_feeds(engine, items)

    print("Evaluating documents...")
    texts = feeds.get_input_text(engine, items)
    idtokens = dict(zip(texts.keys(), list(utils.chat_tokens_each(texts.values()))))
    for id, tokens in idtokens.items():
        allowed_tokens = 100 + np.random.exponential(100)
        if tokens > allowed_tokens:
            texts[id] = texts[id][:int(len(texts[id]) * (allowed_tokens / tokens))]

    return texts

def make_batchfile(texts):
    prompt = open('prompts/news.md', 'r').read()
    prompt = prompt.replace("[CONTEXT]", "\n\n".join([f"ID: {ii}\n{text}" for ii, text in texts.items()]))

    messages = utils.create_chat(prompt, [])
    utils.fillin_training_end(messages, 'gpt-4o')
    
    line = dict(custom_id="sole",
                method='POST',
                url="/v1/chat/completions",
                body={'model': 'gpt-4o',
                      "messages": messages,
                      'max_tokens': 2500})

    jsonl_filename = "batch.jsonl" # always use this and overwrite
    with open(jsonl_filename, 'w') as fp:
        json.dump(line, fp)
        fp.write("\n")
    return jsonl_filename

def submit_batch(client, filepath):
    engine, items = feeds.get_engine_items()

    texts = get_texts(engine, items)
    jsonl_filename = make_batchfile(texts)

    batch = utils.send_batch_file(client, jsonl_filename, metadata={'type': 'news'})

    with open(filepath.replace('.pkl', '-texts.pkl'), 'wb') as fp:
        pickle.dump(texts, fp)
    with open(filepath.replace('.pkl', '-batch.pkl'), 'wb') as fp:
        pickle.dump(batch, fp)

def check_batch(client, filepath):
    # Check if the log is already there
    outpath = filepath.replace('.pkl', '.log')
    if os.path.exists(outpath):
        return

    with open(filepath.replace('.pkl', '-batch.pkl'), 'rb') as fp:
        batch = pickle.load(fp)

    batch = client.batches.retrieve(batch.id)
    if batch.status in ['failed', 'expired', 'cancelling', 'cancelled']:
        with open(outpath, 'w') as fp:
            fp.write("**assistant**:\n")
            fp.write("> Batch returned the result: " + batch.status + "\n")
    elif batch.status == 'completed':
        content = client.files.content(batch.output_file_id)
        message = content.json()['response']['body']['choices'][0]['message']['content']

        with open(outpath, 'w') as fp:
            fp.write("**assistant**:\n")
            for line in message.split("\n"):
                fp.write(f"> {line}\n")

if __name__ == '__main__':
    load_dotenv()
    OpenAI.api_key = os.getenv('OPENAI_API_KEY')
    client = OpenAI()

    ## Look for file generated today
    today_filename = news.get_daily_filepath(datetime.datetime.now())

    if os.path.exists(today_filename.replace('.pkl', '-batch.pkl')):
        print("Checking batch " + today_filename)
        check_batch(client, today_filename)
    else:
        print("Submitting batch " + today_filename)
        submit_batch(client, today_filename)
        
    ## Same for file generated yesterday
    yesterday_filename = news.get_daily_filepath(datetime.datetime.now() - datetime.timedelta(days=1))
    if os.path.exists(yesterday_filename.replace('.pkl', '-batch.pkl')):
        print("Checking batch " + yesterday_filename)
        check_batch(client, yesterday_filename)
