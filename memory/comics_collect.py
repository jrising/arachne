import yaml, os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import feedparser
from email.utils import format_datetime
from PIL import Image
from io import BytesIO
from urllib.parse import urljoin

FEEDS = {
    'https://www.giantitp.com/comics/oots.rss': 'biggest'
    
}

# Function to calculate image size
def calculate_image_size(image_url):
    response = requests.head(image_url)
    if 'Content-Length' in response.headers:
        file_size = int(response.headers['Content-Length'])
        if file_size > 1024:
            response = requests.get(image_url)
            if response.status_code == 200:
                image_data = BytesIO(response.content)
                image = Image.open(image_data)
                return image.size[0] * image.size[1]
            else:
                return None
        return None

def iter_feed_items():
    if os.path.exists('memory/lastread.yml'):
        with open('memory/lastread.yml', 'r') as fp:
            lastreads = yaml.safe_load(fp)
    else:
        lastreads = {}

    for url in FEEDS:
        # Parse the feed
        feed = feedparser.parse(url)
            
        # For each feed item...
        firstlink = None
        for entry in feed.entries:
            if lastreads.get(url) == entry.link:
                break
            if firstlink is None:
                firstlink = entry.link

            uselink = entry.link

            if FEEDS[url]:
                response = requests.get(uselink)
                if response.status_code != 200:
                    print(f"Failed to retrieve the webpage. Status code: {response.status_code}")
                    continue

                soup = BeautifulSoup(response.content, 'html.parser')
                if FEEDS[url] == 'biggest':
                    images = soup.find_all('img')
                    largest_imageurl = None
                    largest_imagesize = 0
                    for img in images:
                        image_url = urljoin(uselink, img['src'])
                        size = calculate_image_size(image_url)
                        if size and size > largest_imagesize:
                            largest_imageurl = image_url
                            largest_imagesize = size
                    uselink = largest_imageurl
                else:
                    image_tag = soup.select_one(css_selector)
                    if image_tag:
                        uselink = image_tag['src']

            try:
                pubtime = entry.published
            except:
                pubtime = format_datetime(datetime.utcnow())
            yield feed.feed.title, entry.title, pubtime, uselink, entry.description

        if firstlink is not None:
            lastreads[url] = firstlink

    with open('memory/lastread.yml', 'w') as fp:
        yaml.dump(lastreads, fp)

if __name__ == '__main__':
    for item in iter_feed_items():
        print(item)
