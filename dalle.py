import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A teenage Puritan girl in a cloak follows a trail into the woods at dusk. Further along the trail, firelight a visible but mostly hidden behind trees. As a colorful, detailed crayon drawing.",
#"A lego version of the Greek goddess Artemis, with a bow and a crescent moon headband, against a white background.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
