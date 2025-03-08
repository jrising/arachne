try:
    from TTS.api import TTS
    import pygame
    import threading
    import queue
        
    tts = TTS("tts_models/en/ljspeech/glow-tts")
    pygame.init()
except:
    print("No text-to-speech functionality.")
    pass

## Generates the waves
def tts_consumer(qqin, qqout):
    ii = 0
    while True:
        sentence = qqin.get()
        if sentence is None or break_streaming:
            break

        tts.tts_to_file(text=sentence, file_path="waves/tts" + str(ii) + ".wav")
        qqout.put("waves/tts" + str(ii) + ".wav")
        
        qqin.task_done()  # Signal that a formerly enqueued task is complete
        ii += 1

def play_audio(srm):
    qqin = queue.Queue()
    qqout = queue.Queue()
    consumer_thread = threading.Thread(target=tts_consumer, args=(qqin, qqout))
    consumer_thread.start()

    channel = pygame.mixer.find_channel()

    currentinput = ""
    for token in srm:
        currentinput += token
        if re.search(r"[.!?] ", currentinput):
            sentences = re.split(r"[.!?] ", currentinput)
            for sentence in sentences[:-1]:
                qqin.put(sentence)
            currentinput = sentences[-1]
        yield token

        if break_streaming:
            break

        if not qqout.empty():
            if not channel.get_queue():
                my_sound = pygame.mixer.Sound(qqout.get())
                channel.queue(my_sound)

    if break_streaming:
        channel.quit()
                
    if currentinput:
        qqin.put(currentinput)

    while (not qqin.empty() or not qqout.empty()) and not break_streaming:
        if not qqout.empty() and not channel.get_queue():
            my_sound = pygame.mixer.Sound(qqout.get())
            channel.queue(my_sound)
        time.sleep(0.2)

    if break_streaming:
        channel.quit()
        
    qqin.put(None)
    while channel.get_busy():
        time.sleep(0.2)
        
    consumer_thread.join()
