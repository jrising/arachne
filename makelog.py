import datetime
import os, time, glob, pickle
from openai import OpenAI
import tiktoken
from dotenv import load_dotenv
from whoosh.index import create_in, open_dir
from whoosh.fields import *
from chatwrap import chatlog
import memory
from memory import integration_long_term, default

ltm = default.create_long_term()

load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

attempts = 3
user_id = "jar"

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
    completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages,
                                              max_tokens=max_tokens, temperature=1)
    return completion.choices[0].message.content

def make_log(log_filename, ixwriter):
    filenameparts = log_filename[4:-4].split('_')
    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Log time: " + filenameparts[0] + " " + filenameparts[1].replace('-', ':')}]
    
    prompt1 = open('prompts/makelog1.md', 'r').read()
    content = open('logs/' + log_filename, 'r').read()

    tokenlen = num_tokens_from_string(content)
    if tokenlen > 4097 - 500 - 350: # error of 350 observed
        messages = chatlog.load_log('', 'logs/' + log_filename)
        if messages[0]['role'] == 'memory':
            messages.pop(0)
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
    
    extra = "\nPlease respond in the following template:\n\nSynopsis: [SYNOPSIS]\n"

    messages.append({"role": "user", "content": prompt1 + "\n===\n" + content + "\n===\n" + extra})

    for ii in range(attempts):
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages,
                                                  max_tokens=500, temperature=1)
        response = completion.choices[0].message.content
        response1 = response.lstrip("#* \t\n")
    
        if not (response1[:len("Synopsis:")] in ["Synopsis:", "Synopsis\n", "Synopsis*"]):
            if ii == attempts-1:
                print("Bad start: " + response1)
                return False
            
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "That response does not start with the text 'Synopsis:'. Can you try again? Make sure to not include any preliminary response text before the Synopsis."})
            continue

        synopsis = response1[len("Synopsis"):]
        synopsis = synopsis.lstrip(":#* \t\n")
        if not valid_synopsis(content, synopsis):
            if ii == attempts-1:
                print("Invalid synopsis: " + response1)
                return False

            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "The synoposis in that response was invalid. Maybe try a shorter synoposis?"})
            continue

        break
            
    prompt2 = open('prompts/makelog2.md', 'r').read()
    response2 = converse(messages, response1, prompt2, 50)
    response2 = response2.lstrip("#* \t\n")

    allowed_attempts = attempts
    logline = None
    while allowed_attempts > 0:
        allowed_attempts -= 1
        if response2[:len("Log:")] != "Log:":
            response2 = converse(messages, response2, "This response did not start with 'Log:'. Please use the template:\n\nLog: [Digest James]; [Digest Arachne]\n", 50)
            continue
        
        logline = response2[len("Log:"):]
        logline = logline.lstrip("#* \t\n")
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
        print("Invalid logline: " + response2)
        return False
    
    prompt3 = open('prompts/makelog3.md', 'r').read()
    response3 = converse(messages, response2, prompt3, 50)
    response3 = response3.lstrip("#* \t\n")
    
    if response3[:len("Title:")] == "Title:":
        title = response3[len("Title:"):]
        title = title.lstrip("#* \t\n")
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

    memories = set()
    
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

            myuser_id = user_id
            log4memory = chatlog.load_log(None, os.path.join("logs", done))
            if log4memory[0]['role'] == 'memory':
                myuser_id = log4memory[0]['content'].strip()
                log4memory.pop(0)
            print('"' + myuser_id + '"')
            
            integration_long_term.ingest_conversation(
                ltm, user_id=myuser_id,
                conversation_id=done,
                messages=log4memory,
                started_at=datetime.datetime.strptime(done[4:23], "%Y-%m-%d_%H-%M-%S"),
                ended_at=datetime.datetime.now()
            )

            memories.add(myuser_id)

    ixwriter.commit()

    print("Consolidating long-term memory.")
    for myuser_id in memories:
        notes = ltm.consolidate_user_memory_incremental(myuser_id, memory_batch_size=40, task_batch_size=15)
        for note in notes:
            print(note)


    
