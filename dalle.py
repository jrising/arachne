import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A drawing of a 17th century Flyte ship. As a colorful cartoon drawing in the center of the frame with a black outline against a white background.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)





## A sequence of drawings of monkeys, all hanging and swinging. As colorful cartoon figures with a black outline against a white background.
