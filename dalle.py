import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A caucasian man in a t-shirt with dark brown hair sitting on a couch with a laptop on his lap. A thin 5-year-old boy with brown hair and a dinosaur shirt is climbing on top of the couch onto his shoulders. A stocky 3-year-old boy with dirty blonde hair with a train on his shirt is next to the man, reaching out to the keys on the keyboard. As a colorful, detailed crayon drawing.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
