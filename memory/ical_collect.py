import requests
from icalendar import Calendar, vDatetime
from datetime import datetime, timedelta

CALENDARS = {
    'World Holidays': 'https://calendar.google.com/calendar/ical/ccnl3g71hhaivlnf039h2nvrjs%40group.calendar.google.com/public/basic.ics', # World Holidays
    'NYT Astronomy': 'https://calendar.google.com/calendar/ical/nytimes.com_89ai4ijpb733gt28rg21d2c2ek@group.calendar.google.com/public/basic.ics' # https://www.nytimes.com/explain/2024/astronomy-space-calendar
}

def iter_feeds():
    return [make_iter_feed(name, url) for name, url in CALENDARS.items()]

def make_iter_feed(name, url):
    def func():
        for tup in iter_feed_items(name, url):
            yield tup
    return func

def iter_feed_items(name, url):
    # Fetch the calendar data
    response = requests.get(url)
    response.raise_for_status()

    # Parse the ICS file
    calendar = Calendar.from_ical(response.content)

    # Get the current date and calculate the date one month ahead
    one_month_before = datetime.now() - timedelta(days=30)
    one_month_after = datetime.now() + timedelta(days=30)

    # Iterate through the events in the calendar
    for component in calendar.walk():
        if component.name == "VEVENT":
            event_start = component.get('dtstart').dt
            event_end = component.get('dtend').dt
        
            if isinstance(event_start, datetime):
                event_start_date = event_start.date()
            else:
                event_start_date = event_start
            
            if isinstance(event_end, datetime):
                event_end_date = event_end.date()
            else:
                event_end_date = event_end
            
            if event_end_date >= one_month_before.date() and event_start_date <= one_month_after.date():
                yield name, component.get('summary'), event_start.strftime('%Y-%m-%d %H:%M:%S'), component.get('uid'), component.get('description')
