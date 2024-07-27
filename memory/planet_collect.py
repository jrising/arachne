import random, datetime, pytz
import feedparser
from email.utils import format_datetime
import configparser
from . import feedutils

def get_planet_ini(filepath):
    # Initialize the parser
    config = configparser.ConfigParser()

    # Read the .ini file
    config.read(filepath)

    return {config.get(section, 'name'): section for section in config.sections()}

if False:
    # Merging planet config files
    live = get_planet_ini('memory/planet-oldinis/planet-live.ini')

    print("In ALL:")
    allini = get_planet_ini('memory/planet-oldinis/planet-all.ini')
    for key, value in allini.items():
        if key not in live:
            live[key] = value
            print(f"{key} missing. Added.")
        elif live[key] != value:
            print(f"{key} changed.")

    print("In FRIENDS:")
    friendini = get_planet_ini('memory/planet-oldinis/planet-friend.ini')
    for key, value in friendini.items():
        if key not in live:
            print(f"{key} missing.")
        elif live[key] != value:
            if live[key][:len("http://www.existencia.org/feeds/lj/feed.php")] == "http://www.existencia.org/feeds/lj/feed.php":
                live[key] = value # return to normal link
            else:
                print(f"{key} changed.")

configs = {'Personal': get_planet_ini("memory/planet-personal.ini"),
           'Other': get_planet_ini("memory/planet-impersonal.ini")}
if sum([len(config) for config in configs.keys()]) > 365:
    raise Error("There are more than 365 entries in planet; we should start taking more than 1 per collect.")

def iter_feed_items():
    for key in configs:
        config = configs[key]
        name, url = random.choice(list(config.items()))
    
        # Parse the feed
        feed = feedparser.parse(url)
    
        # For each feed item...
        count = 0
        for entry in feed.entries:
            pubtime = entry.published
            dt = feedutils.parse_datetime(pubtime)
            local_tz = pytz.timezone('America/New_York')
            oldest = datetime.datetime.now(local_tz) - datetime.timedelta(days=365)
            if dt > oldest:
                count += 1
                yield f"{key}: {feed.feed.title} ({name})", entry.title, pubtime, entry.link, entry.description

        if count == 0:
            print(f"Nothing new in {name}")

if __name__ == '__main__':
    for item in iter_feed_items():
        print(item)
