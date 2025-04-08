import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A coloring book outline scene of a plague of frogs in the streets of ancient Egypt.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
