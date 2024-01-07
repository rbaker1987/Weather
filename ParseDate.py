def parse_date_time(long_date):
    date = long_date[:10]
    hour = int(long_date[11:13])
    if hour == 0:
        time = f'12AM'
    elif hour < 10:
        time = f'0{hour}AM'
    elif hour < 12:
        time = f'{hour}AM'
    elif hour == 12:
        time = f'{hour}PM'
    elif hour < 22:
        time = f'0{hour-12}PM'
    else:
        time = f'{hour - 12}PM'
    return date, time

def parse_date_hour(long_date):
    date = long_date[:10]
    hour = int(long_date[11:13])
    return date, hour

def parse_date(long_date):
    return long_date[:10]

def parse_time(long_date):
    if isinstance(long_date, str):
        hour = int(long_date[11:13])
    else:
        hour = long_date
    if hour == 0:
        time = f'12AM'
    elif hour < 10:
        time = f'0{hour}AM'
    elif hour < 12:
        time = f'{hour}AM'
    elif hour == 12:
        time = f'{hour}PM'
    elif hour < 22:
        time = f'0{hour-12}PM'
    else:
        time = f'{hour - 12}PM'
    return time

def parse_hour(long_date):
    return int(long_date[11:13])

