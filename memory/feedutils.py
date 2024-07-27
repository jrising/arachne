from datetime import datetime
import pytz

def parse_datetime(date_str):
    datetime_formats = [
        "%a, %d %b %Y %H:%M:%S %z",    # "Tue, 11 May 2021 20:28:00 +0000"
        "%a, %d %b %Y %H:%M:%S %z (UTC)", # Thu, 30 May 2024 15:40:22 +0000 (UTC)
        "%Y-%m-%dT%H:%M:%S.%f%z",      # "2020-06-11T17:28:00.000-07:00"
        "%a, %d %b %Y %H:%M:%S %Z",     # Wed, 07 Feb 2024 00:00:00 GMT
        "%Y-%m-%dT%H:%M:%SZ",      # "2006-08-25T13:54:48Z"
    ]

    for fmt in datetime_formats:
        try:
            # Parse the input date string into a datetime object
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Time data {date_str} not matching any known formats")
    
    # Convert the datetime to local timezone
    local_tz = pytz.timezone('America/New_York')
    local_dt = dt.astimezone(local_tz)

    return local_dt
