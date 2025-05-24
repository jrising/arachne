import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A view out a plane window at dawn, looking down on a futuristic green utopia. Pockets of buildings are integrated with colorful nature, connected through dense forests and rolling hills. Digital art.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
