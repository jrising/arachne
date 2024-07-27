from TTS.api import TTS
import pygame
pygame.init()

for model in TTS().list_models():
    if "/en/" in model:# or "multilingual" in model:
        tts = TTS(model)
        tts.tts_to_file(text="This is a story for Austin and Oliver.", file_path="tts.wav")
        channel = pygame.mixer.find_channel()
        my_sound = pygame.mixer.Sound('tts.wav')
        channel.queue(my_sound)

## tts_models/en/ek1/tacotron2
 # TOO SLOW
## tts_models/en/ljspeech/glow-tts
 # > Processing time: 0.6924841403961182
 # > Real-time factor: 0.20923694496456927
## tts_models/en/jenny/jenny
 # > Processing time: 10.90257716178894
 # > Real-time factor: 3.778183144896248
## tts_models/en/ljspeech/tacotron2-DDC
 # BAD
## tts_models/en/ljspeech/vits
 # BROKEN

from TTS.api import TTS
tts = TTS("tts_models/en/ek1/tacotron2")
tts.tts_to_file(text="Austin and Oliver were walking to BOK.", file_path="story2.wav")
tts.tts_to_file(text="They saw on the ground a really nice rock.", file_path="story3.wav")
