## For FeedCollector
from sqlalchemy import select

## To handle long-delayed functions
import concurrent.futures
import queue
import time

from . import feed_collect, imap_collect, linkedin_collect, ical_collect, planet_collect
COLLECTORS = list(feed_collect.iter_feeds()) + list(ical_collect.iter_feeds()) + [imap_collect.iter_feed_items, linkedin_collect.iter_feed_items, planet_collect.iter_feed_items]

def collect_feeds(engine, items):
    insert_queue = queue.Queue()

    with engine.connect() as conn:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {executor.submit(collect_feed_worker, collector, insert_queue): collector for collector in COLLECTORS}

            # Enforce individual timeouts for each collector
            for future, collector in futures.items():
                try:
                    if collector == linkedin_collect.iter_feed_items:
                        future.result(timeout=60 * 10)
                    else:
                        future.result(timeout=10)  # Impose 10 second time out from this point
                except concurrent.futures.TimeoutError:
                    print("Timeout on " + str(collector))
                    future.cancel()  # Cancel the task if it exceeds the specified timeout
                except Exception as e:
                    print(f"Error collecting feed for {collector}: {e}")

        try:
            while not insert_queue.empty():
                feed, title, pubtime, link, desc = insert_queue.get_nowait()
                insert_entry(conn, items, feed, title, pubtime, link, desc)
            conn.commit()
        except queue.Empty:
            pass

def collect_feed_worker(collector, insert_queue, timeout=10):
    try:
        count = 0
        for feed, title, pubtime, link, desc in collector():
            insert_queue.put((feed, title, pubtime, link, desc))
            count += 1
        print(str(collector.__class__) + ": " + str(count))
    except Exception as e:
        print(f"Error collecting feed: {e}")
        
def insert_entry(conn, items, feed, title, pubtime, link, desc):
    # Look for this item in the database
    result = conn.execute(
        select(items.c).where(items.c.link == link)
    ).fetchall()
                
    # If it's not already there...
    if len(result) == 0:
        # Insert the new item
        conn.execute(items.insert().values(
            feed=feed,
            title=title,
            pubtime=pubtime,
            link=link,
            description=desc,
            uses=0,
            lastused=int(time.time())))
