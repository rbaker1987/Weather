from datetime import datetime
from tzlocal import get_localzone


def nws_date_parser(nws_date):
    split = nws_date.split('/')
    date = split[0].split('T')[0]
    start_time = split[0].split('T')[1].split('+')[0]
    duration_hour = split[1][2]
    year = date.split('-')[0]
    month = date.split('-')[1]
    day = date.split('-')[2]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1]
    second = start_time.split(':')[2]
    utc_dt_str = f"{year}-{month}-{day} {hour}:{minute}:{second}"
    utc_dt = datetime.strptime(utc_dt_str, "%Y-%m-%d %H:%M:%S")
    local_dt = utc_dt.astimezone(get_localzone()).isoformat()
    return local_dt

def list_times(data):
    times = []
    for i, item in enumerate(data[0]):
        for x, slot in enumerate(item):
            slot_time = slot[0]
            parsed_time = parse_times(slot_time)
            times.append(parsed_time)
            pass
    times_unique = list(set(times))
    times_unique.sort()
    return times_unique


if __name__ == '__main__':
    date = input('Date: ')
    parse_times(date)
