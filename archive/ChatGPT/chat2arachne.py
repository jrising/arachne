import json, datetime, os

with open("ChatGPT/conversations.json") as fp:
    dd = json.load(fp)
    for conv in dd:
        lastmsgid = conv['current_node']
        content = ""
        while lastmsgid:
            lastmsg = conv['mapping'][lastmsgid]
            if lastmsg['message'] and lastmsg['message']['author']['role'] != 'system':
                content = "**" + lastmsg['message']['author']['role'] + "**:\n> " + "\n".join(lastmsg['message']['content']['parts']).replace("\n", "\n> ") + "\n" + content
            lastmsgid = lastmsg['parent']

        time = datetime.datetime.fromtimestamp(conv['create_time'])
        current_time = time.strftime('%Y-%m-%d_%H-%M-%S')
        log_filename = f'log_{current_time}_ChatGPT.log'

        with open(os.path.join("openai-quickstart-python/logs", log_filename), 'w') as fp:
            fp.write(content)

