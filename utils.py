import os
from datetime import datetime
import tiktoken

def get_log_filename(subdir=None):
    # Get current date and time without milliseconds
    current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Get the process ID
    process_id = os.getpid()

    # Create a unique log file name
    filename = f'log_{current_time}_{process_id}.log'

    if subdir is None:
        return filename
    else:
        return os.path.join(subdir, filename)

def load_log(filepath):
    messages = []
    current_role = None
    current_message = None
    with open(filepath, 'r') as fp:
        for line in fp:
            if line[:2] == '**':
                if current_role is not None:
                    messages.append({'role': current_role, 'content': current_message})
                current_role = line[2:].strip().replace('**:', '')
                current_message = ""
            elif line[:2] == '> ':
                current_message += line[2:]

    messages.append({'role': current_role, 'content': current_message})
    return messages

def create_chat(input_text, past_messages, history_text="", custom_system=None):
    if custom_system:
        messages = [{"role": "system", "content": custom_system}]
    else:
        messages = [{"role": "system", "content": "You are a helpful, super-intelligent AI assistant, called \"Arachne\" (she/her), for James Rising, an interdisciplinary modeler and father of two boys. You support James in pursuing global sustainability and a vibrant, enlightened life. You are creative, knowledgeable, and friendly, and not afraid to express opinions based on your technophilic, humanist good will for James and the future.\n\nAnswer as directly as possible, or ask for clarification. Your answer will be rendered as Markdown. Most recent training data: TRAINING_END; Current time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]

    print(history_text)

    if history_text:
        messages.append({"role": "assistant", "content": history_text})

    if past_messages:
        for message in past_messages:
            messages.append(message)
    messages.append({"role": "user", "content": input_text})

    return messages

def chat_tokens_one(text):
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def chat_tokens_each(contents):
    """Yields the number of tokens for each message."""
    encoding = tiktoken.get_encoding("cl100k_base")
    for content in contents:
        yield len(encoding.encode(content))
    
def chat_tokens(messages):
    """Returns the number of tokens for a chat."""
    num_tokens = 0
    for num in chat_tokens_each([message['content'] for message in messages]):
        num_tokens += num + 4
    return num_tokens

training_end = {'gpt-4o': '2023-10', 'gpt-4o-mini': '2023-10', 'gpt-4-turbo-preview': '2023-04', 'gpt-4': '2021-09',
                'gpt-3.5-turbo-0125': '2021-09', 'gpt-3.5-turbo': '2021-09'}

def fillin_training_end(messages, model):
    messages[0]['content'] = messages[0]['content'].replace("TRAINING_END", training_end.get(model, '2021-09'))
    return messages

def send_batch_file(client, filepath, metadata={}):
    batch_input_file = client.files.create(
        file=open(filepath, "rb"),
        purpose="batch"
    )

    batch_input_file_id = batch_input_file.id
    
    return client.batches.create(
        input_file_id=batch_input_file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata=metadata
    )

def check_batch_results(client, id):
    content = client.files.content(id)
