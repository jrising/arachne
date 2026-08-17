import os, base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OpenAI.api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI()

# . venv2024/bin/activate

response = client.images.generate(
  model="gpt-image-2",
    prompt="""Create a detailed fantasy tabletop-RPG quest map, hand-painted on aged birch bark by woodland druids, vertical portrait orientation. A winding trail leads from the bottom-left to the top-right through a dark enchanted forest. Include eight clearly distinct numbered map landmarks, with large simple glowing rune-numbers 1 through 8 beside each location, but no other written words.

Druid Circle: ancient standing stones beneath a huge oak, moonlight and druids’ green magic.
Bramblegate: a narrow path blocked by enormous thorny vines, with small glowing eyes hidden inside.
Mossback Ford: a dangerous river crossing over the shell of a giant sleeping turtle, with broken stepping-stones nearby.
Goblin Snarewood: crooked trees holding rope traps, dangling cages, and a small goblin lookout camp.
Whispering Ravine: misty ravine with a broken rope bridge and shadowy wolf-like creatures on either side.
Moonseed Grove: a beautiful but sickly grove with one enormous silver-leaved tree, black corruption spreading through its roots, and frightened woodland animals.
Logger Camp: rough wooden palisade, sawmill, stacked logs, platforms in the trees, and a chest marked by a crescent-moon symbol.
Bramblehook’s Canopy Fort: tall tree fortress connected by rope bridges, lanterns, banners, and two masked ninja silhouettes watching from rooftops.
Add a compass rose shaped like a leaf, tiny illustrations of owls and deer around the border, glowing druidic symbols, clear travel routes, and a sense that the map itself is magical. Rich greens, moonlit blues, gold ink, high-detail fantasy cartography, family-friendly, no gore, no modern objects.

Quest challenges by map point
Bramblegate: cut, burn, solve, or climb past living thorns; 2–3 thorn blights attack if handled roughly.
Mossback Ford: save Farmer Tobin from falling in; a successful calm approach avoids waking the turtle.
Goblin Snarewood: lesser battle with 4 goblin trappers and their snares.
Whispering Ravine: cross the damaged bridge while dealing with 2 shadow wolves; failure creates a rescue complication, not a dead end.
Moonseed Grove: cure or defend the grove from corrupted plants before pursuing Bramblehook.
Logger Camp: stealth, negotiation with frightened workers, or a battle against guards.
Canopy Fort: final fight with Captain Bramblehook and the Nightleaf Twins, followed by Ekemon’s chance to recruit Kite and Moth.""",
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
