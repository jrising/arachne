import time, pickle
import html2text
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

def setup():
    # Configure WebDriver
    chrome_options = webdriver.chrome.options.Options()
    chrome_options.add_argument("user-data-dir=memory/selenium")
    return webdriver.Chrome(options=chrome_options)

def infinite_scroll(driver):
    # Do some infinite scrolling
    SCROLL_PAUSE_TIME = 20
    
    # Get scroll height
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    for ii in range(10):
        # Scroll down to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        # Wait to load page
        time.sleep(SCROLL_PAUSE_TIME)
        # Calculate new scroll height and compare with last scroll height
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            return
        last_height = new_height

def iter_webelts():
    driver = setup()
    driver.get('https://www.linkedin.com/')
    
    # Allow time for login and page loading
    while len(driver.find_elements(By.CSS_SELECTOR, "div.feed-shared-update-v2")) == 0:
        time.sleep(20)
    
    infinite_scroll(driver)
    
    posts = driver.find_elements(By.CSS_SELECTOR, "div.feed-shared-update-v2")

    for post in posts:
        yield post
    
    # Close the driver
    driver.quit()

def iter_feed_items():
    converter = html2text.HTML2Text()
    converter.ignore_images = False  # To keep images in the markdown
    converter.ignore_links = False

    for post in iter_webelts():
        person = post.find_elements(By.CSS_SELECTOR, "span.update-components-actor__title")[0]
        name = person.text.split("\n")[0]
        ## fp.write(name + "\n\n")
        html = post.get_attribute('innerHTML')
        markdown = converter.handle(html)
        ## fp.write(markdown)

        yield "LinkedIn", name + ": LinkedIn update", datetime.today().strftime('%Y-%m-%d %H:%M:%S'), "https://www.linkedin.com/feed/?hash=" + str(hash(markdown)), markdown
