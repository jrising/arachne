from datetime import datetime
import feedparser
from email.utils import format_datetime
from bs4 import BeautifulSoup
import html2text

# class MaterialCollector(ABC):
#     (1, 1, 'http://www.sciencemag.org/rss/current.xml', 'Science Magazine', '<p><a href=\"http://www.sciencemag.org/rss/current.xml\">Table of contents, current issue</a></p>', '	Table of contents, current issue [1]\n\n[1] http://www.sciencemag.org/rss/current.xml', 0, NULL),
# (2, 1, 'http://rss.sciencedirect.com/publication/science/03043800', 'Ecological Modeling', '<p>Ecological Modeling</p>', '	Ecological Modeling', 0, 'http://rss.sciencedirect.com/publication/science/03043800'),
# (3, 1, 'http://jpr.sagepub.com/rss/current.xml', 'Journal of Peace Research', '<p class=\"p1\">Journal of Peace Research</p>\r\n<p> </p>', '	Journal of Peace Research \n\n	 ', 0, NULL),
# (4, 1, 'http://content.apa.org/journals/psp-ofp.rss', 'Journal of Personality and Social Psychology', '<p class=\"p1\">Journal of Personality and Social Psychology</p>\r\n<p> </p>', '	Journal of Personality and Social Psychology \n\n	 ', 0, NULL),
# (5, 1, 'http://feeds.nature.com/NatureLatestResearch?format=xml', 'Nature Latest Research', '<p class=\"p1\">Nature Latest Research</p>\r\n<p> </p>', '	Nature Latest Research \n\n	 ', 0, NULL),
# (6, 1, 'http://www.g-feed.com/feeds/posts/default', 'G-FEED (Sol, Wolfram)', '<p class=\"p1\">G-FEED (Sol, Wolfram)</p>\r\n<p> </p>', '	G-FEED (Sol, Wolfram) \n\n	 ', 0, NULL),
# (8, 1, 'http://feeds.feedburner.com/pnas/SMZM?format=xml', 'Proceedings of the National Academy of Sciences', '<p>PNAS</p>', '	PNAS', 0, NULL),
# (9, 1, 'http://www.ecologyandsociety.org/rss', 'Ecology and Society', '<p>Ecology and Society</p>', '	Ecology and Society', 0, NULL),
# (10, 1, 'http://existencia.org/feeds/scholar.pl', 'Google Scholar Alerts', '<p>Google Scholar Alerts, extracted using IFTTT -&gt; Blogger -&gt; Perl.</p>', '	Google Scholar Alerts, extracted using IFTTT -> Blogger -> Perl.', 0, NULL),
# (11, 1, 'http://rss.sciam.com/ScientificAmerican-Global?format=xml', 'Scientific American', '<p>Scientific American</p>', '	Scientific American', 0, 'http://rss.sciam.com/ScientificAmerican-Global?format=xml'),
# (12, 1, 'http://icesjms.oxfordjournals.org/rss/current.xml', 'ICES Journal of Marine Science', '<p>ICES Journal of Marine Science</p>', '	ICES Journal of Marine Science', 0, 'http://icesjms.oxfordjournals.org/rss/current.xml'),
# (13, 1, 'http://rss.sciencedirect.com/publication/science/01657836', 'Fisheries Research', '<p>Fisheries Research</p>', '	Fisheries Research', 0, 'http://rss.sciencedirect.com/publication/science/01657836');

FEEDS = [
    'http://www.sciencemag.org/rss/current.xml',
    'http://rss.sciencedirect.com/publication/science/03043800',
    'https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=jpra&type=etoc&feed=rss',
    'https://www.nature.com/nature.rss',
    'http://www.g-feed.com/feeds/posts/default',
    'http://feeds.feedburner.com/pnas/SMZM?format=xml',
    'http://www.ecologyandsociety.org/rss',
    'http://rss.sciam.com/ScientificAmerican-Global?format=xml',
    'http://icesjms.oxfordjournals.org/rss/current.xml',
    'http://rss.sciencedirect.com/publication/science/01657836',
    'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'https://rss.nytimes.com/services/xml/rss/nyt/US.xml',
    'https://rss.nytimes.com/services/xml/rss/nyt/EnergyEnvironment.xml',
    'https://rss.nytimes.com/services/xml/rss/nyt/Science.xml',
    'https://rss.sciencedirect.com/publication/science/00950696', # JEEM
    'https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=reep', # REEP
    'https://back.nber.org/rss/new.xml' # NBER
]

def make_iter_feed(url):
    def func():
        for tup in iter_feed_items(url):
            yield tup
    return func    
    
def iter_feeds():
    return [make_iter_feed(url) for url in FEEDS]

def iter_feed_items(url):
    print(url)
    # Parse the feed
    feed = feedparser.parse(url)
            
    # For each feed item...
    print(len(feed.entries))
    for entry in feed.entries:
        # Remove unnecessary HTML
        soup = BeautifulSoup(entry.description, 'html.parser')
        h = html2text.HTML2Text()
        h.ignore_links = False
        markdowndesc = h.handle(soup.prettify())
        
        try:
            pubtime = entry.published
        except:
            pubtime = format_datetime(datetime.utcnow())

        yield feed.feed.title, entry.title, pubtime, entry.link, markdowndesc
