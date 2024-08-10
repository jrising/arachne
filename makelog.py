from datetime import datetime
import os, time, glob, pickle
import openai, tiktoken
from dotenv import load_dotenv
from whoosh.index import create_in, open_dir
from whoosh.fields import *

load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')

try:
    ix = open_dir("database/whoosh")
except:
    schema = Schema(path=ID(stored=True), line=TEXT(stored=True), content=TEXT)
    ix = create_in("database/whoosh", schema)

def valid_synopsis(content, synopsis):
    if len(synopsis) > len(content) / 2 and len(synopsis) > 1000:
        return False
    if "[SYNOPSIS]" in synopsis:
        return False
    return True

def valid_logline(content, synopsis, logline):
    if len(logline) > 200:
        return False
    if "\n" in logline:
        return False
    if len(logline.split('; ')) != 2:
        return False
    if "[SYNOPSIS]" in (synopsis + logline) or "[LOG]" in (synopsis + logline):
        return False
    return True

def num_tokens_from_string(string):
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens

def converse(messages, assistant_response, user_response, max_tokens):
    messages.append({"role": "assistant", "content": assistant_response})
    messages.append({"role": "user", "content": user_response})
    completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages,
                                              max_tokens=max_tokens, temperature=1)
    return completion['choices'][0]['message']['content']

def make_log(log_filename, ixwriter):
    filenameparts = log_filename[4:-4].split('_')
    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Log time: " + filenameparts[0] + " " + filenameparts[1].replace('-', ':')}]

    prompt1 = open('prompts/makelog1.md', 'r').read()
    content = open('logs/' + log_filename, 'r').read()

    tokenlen = num_tokens_from_string(content)
    if tokenlen > 4097 - 500 - 350: # error of 350 observed
        messages = load_log('logs/' + log_filename)
        maxperstate = int((4097 - 500 - 350) / len(messages)) - 10 # **word**: ...
        content = ""
        for message in messages:
            charspertoken = len(message['content']) / num_tokens_from_string(message['content'])
            allowedlen = int(charspertoken * maxperstate)
            content += message['role'] + "\n"
            if len(message['content']) < allowedlen:
                content += message['content']
            else:
                content += message['content'][:allowedlen] + "..."
    
    extra = "\n\nPlease respond in the following template:\n\nSynopsis: [SYNOPSIS]\n"
    
    messages.append({"role": "user", "content": prompt1 + "\n" + content + extra})
    completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages,
                                              max_tokens=500, temperature=1)
    response1 = completion['choices'][0]['message']['content']

    if response1[:len("Synopsis: ")] != "Synopsis: ":
        print(response1)
        return False
        
    synopsis = response1[len("Synopsis: "):]
    if not valid_synopsis(content, synopsis):
        print(response1)
        return False

    prompt2 = open('prompts/makelog2.md', 'r').read()
    response2 = converse(messages, response1, prompt2, 50)

    allowed_attempts = 3
    logline = None
    while allowed_attempts > 0:
        allowed_attempts -= 1
        if response2[:len("Log: ")] != "Log: ":
            response2 = converse(messages, response2, "This response did not start with 'Log: '. Please use the template:\n\nLog: [Digest James]; [Digest Arachne]\n", 50)
            continue
        
        logline = response2[len("Log: "):]
        if len(logline) > 200:
            response2 = converse(messages, response2, "This response was significantly longer than the log entry I want to use. Can you try a short phrase for each digest? Again, use the template:\n\nLog: [Digest James]; [Digest Arachne]\n", 50)
            continue
            
        if len(logline.split('; ')) == 1:
            response2 = converse(messages, response2, "This response did not exactly follow the template, due to the lack of a semicolon between the digests. Please use the template:\n\nLog: [Digest James]; [Digest Arachne]\n", 50)
            continue

        if len(logline.split('; ')) > 2:
            response2 = converse(messages, response2, "This response did not exactly follow the template, due to multiple semicolons when there needs to be only one. Summarize all of James's comments together and all of your comments together. Please use the template:\n\nLog: [Digest James]; [Digest Arachne]\n", 50)
            continue

        break
    
    if not valid_logline(content, synopsis, logline):
        print(response2)
        return False

    prompt3 = open('prompts/makelog3.md', 'r').read()
    response3 = converse(messages, response2, prompt3, 50)

    if response3[:len("Title: ")] == "Title: ":
        title = response3[len("Title: "):]
        if len(title) <= 100:
            if os.path.exists("database/logs/titles.pkl"):
                with open("database/logs/titles.pkl", 'rb') as fp:
                    titles = pickle.load(fp)
            else:
                titles = {}
            titles[log_filename[4:14] + ' ' + log_filename[15:23].replace('-', ':')] = title
            with open("database/logs/titles.pkl", 'wb') as fp:
                pickle.dump(titles, fp)

    with open("database/logs/running.log", 'a+') as fp:
        fp.write(log_filename[4:14] + ' ' + log_filename[15:23].replace('-', ':') + ': ' + logline + "\n")
    with open("database/logs/" + log_filename, 'w') as fp:
        fp.write(synopsis + "\n")
    ixwriter.add_document(path="logs/" + log_filename, line=logline, content=synopsis)
        
    return True
    
if __name__ == '__main__':
    ## Find the next log that does not have a corresponding synopsis
    ixwriter = ix.writer()

    logs = sorted(os.listdir("logs"))
    syns = set(os.listdir("database/logs"))

    for done in logs:
        if not os.path.isfile(os.path.join("logs", done)):
            continue
        if done not in syns:
            log_filename = done
            print(log_filename)
            ## log_filename = "log_2023-06-19_20-50-18_54910.log"
            try:
                result = make_log(log_filename, ixwriter)
                if not result:
                    # Try again
                    result = make_log(log_filename, ixwriter)
                    if not result:
                        print("Summarizing failed on " + log_filename)
                        break
                time.sleep(1)
            except Exception as ex:
                print("Code failed on " + log_filename)
                print(ex)
                break

    ixwriter.commit()


    
