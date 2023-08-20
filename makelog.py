from datetime import datetime
import os, time
import openai, tiktoken
from dotenv import load_dotenv
from whoosh.index import create_in
from whoosh.fields import *

load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')

schema = Schema(logline=TEXT(stored=True), path=ID(stored=True), content=TEXT)
ix = create_in("database/whoosh", schema)

def num_tokens_from_string(string):
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens

def make_log(log_filename):
    filenameparts = log_filename[4:-4].split('_')
    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Log time: " + filenameparts[0] + " " + filenameparts[1].replace('-', ':')}]

    prompt = open('prompts/makelog.md', 'r').read()
    content = open('logs/' + log_filename, 'r').read()

    tokenlen = num_tokens_from_string(content)
    if tokenlen > 4097 - 500 - 350: # error of 350 observed
        lines = content.splitlines()
        people = []
        states = []
        for line in lines:
            if line in ['**user**:', '**assistant**:']:
                people.append(line)
                states.append("")
            else:
                states[-1] = states[-1] + line + "\n"
        maxperstate = int((4097 - 500 - 350) / len(people)) - 10 # **word**: ...
        content = ""
        for ii in range(len(people)):
            charspertoken = len(states[ii]) / num_tokens_from_string(states[ii])
            allowedlen = int(charspertoken * maxperstate)
            content += people[ii] + "\n"
            if len(states[ii]) < allowedlen:
                content += states[ii]
            else:
                content += states[ii][:allowedlen] + "..."
    
    extra = "\n\nPlease respond in the following template:\n\nSynopsis: [SYNOPSIS]\n\nLog: [LOG]\n"
    
    messages.append({"role": "user", "content": prompt + "\n" + content + extra})
    completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages,
                                              max_tokens=500, temperature=1)

    response = completion['choices'][0]['message']['content']
    parts1 = response.split("Synopsis:")
    parts2 = parts1[-1].split("Log:")
    synopsis = parts2[0].strip()
    logline = parts2[1].strip()
    if synopsis and logline:
        if len(synopsis) > 150*6:
            return False
        if len(logline) > 100:
            return False
        if "Udemy, Coursera, LinkedIn" in (synopsis + logline) and "Udemy" not in content:
            return False # Common failure mode
        with open("database/logs/running.log", 'a+') as fp:
            fp.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S: ') + logline + "\n")
        with open("database/logs/" + log_filename, 'w') as fp:
            fp.write(synopsis + "\n")
        return True
    return False
    
if __name__ == '__main__':
    ## (Re)generate index
    writer = ix.writer()
    with open("database/logs/running.log", 'r') as fp:
        for line in fp.readlines():
            pass
    
    ## Find the next log that does not have a corresponding synopsis
    logs = sorted(os.listdir("logs"))
    syns = set(os.listdir("database/logs"))
    for done in logs:
        if done not in syns:
            log_filename = done
            print(log_filename)
            ## log_filename = "log_2023-06-19_20-50-18_54910.log"
            try:
                result = make_log(log_filename)
                if not result:
                    print("Summarizing failed on " + log_filename)
                time.sleep(1)
            except Exception as ex:
                print("Code failed on " + log_filename)
                print(ex)
                # raise ex

    
