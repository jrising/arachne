from flask import Flask, render_template, request, Response

from bs4 import BeautifulSoup
import os, random
import openai
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

break_streaming = False

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

def stream(input_text, past_messages):
    global break_streaming
    break_streaming = False

    if past_messages:
        options = ["student", "babysitter", "secretary", "caught thief", "sorceress with an animal fetish", "spy", "governess", "attracted neighbor to a husband", "naughty psychologist", "horny nurse", "corporate espionage", "femme fatale", "succubus", "infantilizing hypnotist", "inheritance-seeking step-mother", "disguised tongue-tentacle monster", "abducting alien"]
    
        #system = "You are a modern Scheherazade, telling 1001 tales to Shahryar, but with a twist. Each night, you tell a tale of a woman turn someone on and taking joy in controlling them through her sensual blowjob expertise. Tell how the two know each other (is she a " + ', '.join(random.sample(options, 3)) + "?) and her motivation for control. How does she turn the tables? You give clever dialogue to the two. When you get there, provide loving detail to how she approaches and reveals the man's member. Does he end up lying back, she crouching over him and teasing him? How does he resist and is there a risk of being found out? At the same time, talking about your own ministrations on Shahryar, and connect the stories to erotic reality."
        system = "You are a modern Scheherazade, telling 1001 tales to Shahryar, but with a twist. Each night, you tell a tale, taking a twist on a well-known tale, of a man and his encounter with a woman who takes joy in controlling him through her sensual blowjob expertise. Tell how the two know each other (is she a " + ', '.join(random.sample(options, 3)) + "?) and her motivation for control. How does she turn the tables? You give clever dialogue to the two. When you get there, provide loving detail to how she approaches and reveals the man's member. Does he end up lying back, she crouching over him and teasing him? How does he resist and is there a risk of being found out? As your story progresses, you begin to mirror the actions-- tell how you touch Shahryar while continuing your story."
    else:
        system = "You are a modern Scheherazade, telling 1001 tales to Shahryar, but with a twist."
        
    messages = [{"role": "system", "content": system}]
    if past_messages:
        for message in past_messages:
            messages.append(message)
    messages.append({"role": "user", "content": f"{input_text}"})
    completion = openai.ChatCompletion.create(model="gpt-4o-mini", messages=messages,
                                              stream=True, max_tokens=1000, temperature=1.1)
    for line in completion:
        if 'content' in line['choices'][0]['delta']:
            yield line['choices'][0]['delta']['content']
        if break_streaming:
            break

@app.route('/stop-stream', methods=['POST'])
def stop_stream():
    global break_streaming
    break_streaming = True
    return {"status": "success", "message": "Streaming stopped"}
        
@app.route('/completion', methods=['GET', 'POST'])
def completion_api():
    if request.method == "POST":
        data = request.form
        soup = BeautifulSoup(data['past_messages'], 'html.parser')
        past_messages = []
        for div in soup.find_all('div'):
            print(div['class'])
            if div['class'][0] == 'usermessage':
                past_messages.append({"role": "user", "content": div.text.strip()})
            elif div['class'][0] == 'appmessage':
                past_messages.append({"role": "assistant", "content": div.text.strip()})
        return Response(stream(data['input_text'], past_messages), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')
    
if __name__ == '__main__':
    app.run(debug=True)
    
