## For FeedCollector
from sqlalchemy import select

## To handle long-delayed functions
import concurrent.futures
import queue
import time

from . import feed_collect, imap_collect, linkedin_collect, ical_collect, planet_collect
COLLECTORS = list(feed_collect.iter_feeds()) + list(ical_collect.iter_feeds()) + [imap_collect.iter_feed_items, linkedin_collect.iter_feed_items, planet_collect.iter_feed_items]
COLLNAMES = list(feed_collect.name_feeds()) + list(ical_collect.name_feeds()) + ["IMAP", "LinkedIN", "Planet"]

def collect_feeds(engine, items):
    insert_queue = queue.Queue()

    with engine.connect() as conn:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {executor.submit(collect_feed_worker, COLLECTORS[cc], COLLNAMES[cc], insert_queue): (COLLECTORS[cc], COLLNAMES[cc]) for cc in range(len(COLLECTORS))}

            # Enforce individual timeouts for each collector
            for future, collector_and_name in futures.items():
                try:
                    if collector_and_name[0] == linkedin_collect.iter_feed_items:
                        future.result(timeout=60 * 10)
                    else:
                        future.result(timeout=10)  # Impose 10 second time out from this point
                except concurrent.futures.TimeoutError:
                    print("Timeout on " + collector_and_name[1])
                    future.cancel()  # Cancel the task if it exceeds the specified timeout
                except Exception as e:
                    print(f"Error collecting feed for {collector_and_name[0]}: {e}")

        try:
            while not insert_queue.empty():
                feed, title, pubtime, link, desc = insert_queue.get_nowait()
                insert_entry(conn, items, feed, title, pubtime, link, desc)
            conn.commit()
        except queue.Empty:
            pass

def collect_feed_worker(collector, collname, insert_queue, timeout=10):
    try:
        count = 0
        for feed, title, pubtime, link, desc in collector():
            insert_queue.put((feed, title, pubtime, link, desc))
            count += 1
        print(collname + ": " + str(count))
    except Exception as e:
        print(f"Error collecting feed {collname}: {e}")
        
def insert_entry(conn, items, feed, title, pubtime, link, desc):
    # Look for this item in the database
    result = conn.execute(
        select(items.c).where(items.c.link == link)
    ).fetchall()
                
    # If it's not already there...
    if len(result) > 0:
        print(result[0])
        return dict(zip(['id', 'feed', 'title', 'pubtime', 'link', 'description', 'uses', 'lastused'], result[0]))
    
    # Insert the new item
    result = conn.execute(items.insert().values(
        feed=feed,
        title=title,
        pubtime=pubtime,
        link=link,
        description=desc,
        uses=0,
        lastused=int(time.time())))
    return dict(id=result.inserted_primary_key[0],
                feed=feed,
                title=title,
                pubtime=pubtime,
                link=link,
                description=desc,
                uses=0,
                lastused=int(time.time()))
