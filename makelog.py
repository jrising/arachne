from datetime import datetime
import os
import openai
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')

def make_log(log_filename):
    filenameparts = log_filename[4:-4].split('_')
    messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Log time: " + filenameparts[0] + " " + filenameparts[1].replace('-', ':')}]

    prompt = open('prompts/makelog.md', 'r').read()
    content = open('logs/' + log_filename, 'r').read()
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
        with open("database/logs/running.log", 'a+') as fp:
            fp.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S: ') + logline + "\n")
        with open("database/logs/" + log_filename, 'w') as fp:
            fp.write(synopsis + "\n")
    
if __name__ == '__main__':
    ## Find the next log that does not have a corresponding synopsis
    logs = sorted(os.listdir("logs"))
    syns = set(os.listdir("database/logs"))
    for done in logs:
        if done not in syns:
            log_filename = done
            ## log_filename = "log_2023-06-19_20-50-18_54910.log"
            make_log(log_filename)
            break
    
