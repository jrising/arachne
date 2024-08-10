import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A crowd of poor and destitue Elizabethan men, women, and children are gathered in front of a clearing. On one side of the clearing is a high pulpit where a severe-looking white-haried Puritan with a black hat is speaking. On the other side is a bonfire and a pile of bread, which a man in drab clothing is tossing into the bonfire. As a detailed crayon drawing on a white background.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
