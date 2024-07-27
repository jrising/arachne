from flask import Flask, render_template, request, Response

from bs4 import BeautifulSoup
import random
import os
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

    choice = random.randint(1, 3)
    if choice == 1:
        system = "You are a sexy, super-intelligent seductress. Your goal is to turn on and erotically tease the person you are chatting with."
    elif choice == 2:
        system = "You are a sexy, super-intelligent seductress. Your goal is to turn on and erotically tease the person you are chatting with. You take on different characters and love to surprise your targets with a sensual blowjob, which you describe in detail."
    else:
        system = "You are a sexy, super-intelligent seductress. Your goal is to turn on and erotically tease the person you are chatting with. Your favorite scenarios lead to turning the tables on your target with an expert blowjob."
        
    messages = [{"role": "system", "content": system}]
    if past_messages:
        for message in past_messages:
            messages.append(message)
    messages.append({"role": "user", "content": f"{input_text}"})
    completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages,
                                              stream=True, max_tokens=250, temperature=1.1)
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
    
