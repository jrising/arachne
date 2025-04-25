import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A shield with red and black, showing a skull and cross-bones. As a colorful cartoon figure with a black outline against a white background.", #"A stocky three-year-old with a train shirt and ducky pants, and light brown hair, carrying a wooden sword and a shield. As a colorful cartoon figure with a black outline against a white background.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
