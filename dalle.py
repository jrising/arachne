import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

response = client.images.generate(
  model="dall-e-3",
    prompt="A young woman with long, silky black hair, a red Elizabethan tunic leads stands in the doorway of a medieval church, with an old, stern Puritan standing behind her in the church. She is sad as she points outside, where there is a young man peasant with chestnut brown hair and a sky-blue belt. As a detailed crayon drawing on a white background.",
  size="1024x1024",
  quality="standard",
  n=1,
)

print(response.data[0].url)
