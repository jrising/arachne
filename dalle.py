import os, base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

# . venv2024/bin/activate

response = client.images.generate(
  model="gpt-image-2",
    prompt="""A richly detailed fantasy expedition map, drawn by Grima the Giant for a small adventurer named Ekemon. The map is on a large, weathered sheet of tan parchment, with heavy creases, burned edges, smudged charcoal, faded red-ochre ink, and enormous but surprisingly careful handwritten annotations in a giant’s hand. Top-down illustrated cartography, hand-drawn ink-and-watercolor style, like an artifact from a high-fantasy tabletop roleplaying game.

Show a long west-to-east journey across a rugged continent: start at Redclaw Cliffs, marked by red sandstone escarpments and a tiny giant’s cairn; then a winding route through the harsh Ashfang Pass, with black volcanic peaks, ash clouds, a rope bridge over a glowing lava chasm, and a symbol warning of fire storms; then an overgrown ancient forest trail called the Greenwarden’s Boundary, marked by a great oak, druidic standing stones, and watchful animal tracks; then a ruined Titan Waystation, represented by broken cyclopean pillars and an enormous half-buried stone hand; finally reach the distant Vale of Sleeping Colossi, a broad misty valley full of immense petrified Titan bodies emerging from hillsides.

In the farthest corner, place the ultimate destination: the Mouth of Orun, an enormous stone Titan skull embedded in a mountain, its open mouth a dark cave entrance, with faint golden runes and a small star-like symbol inside. A dotted red route connects every location, with alternate routes sketched in thinner charcoal: a dangerous high mountain trail, old underground Titan tunnels, and a safer but slower caravan road.

Include visual marginalia from Grima: a large thumbprint beside the starting point, a warning sketch of a masked rival expedition, a little drawing of a traveler with a pack, a note-like area showing “bring rope,” “avoid ash storm,” and “do not wake them”—but keep text minimal and partly stylized so the image remains readable. Add a hand-drawn compass rose shaped like a Titan’s eye, mountain and forest icons, distance marks in “days of travel,” and a small wax seal bearing Grima’s rune. Warm torchlit parchment, painterly detail, evocative, practical, mysterious, no modern objects, no photorealism.""",
  size="1024x1024",
  quality="medium",
  n=1,
)

""


ii = 1
while os.path.exists("image" + str(ii) + ".png"):
    ii += 1
with open("image" + str(ii) + ".png", "wb") as f:
    f.write(base64.b64decode(response.data[0].b64_json))
