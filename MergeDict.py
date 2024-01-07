from datetime import datetime, timedelta

time_hour = {'12AM': 0,
             '1AM': 1,
             '2AM': 2,
             '3AM': 3,
             '4AM': 4,
             '5AM': 5,
             '6AM': 6,
             '7AM': 7,
             '8AM': 8,
             '9AM': 9,
             '10AM': 10,
             '11AM': 11,
             '12PM': 12,
             '1PM': 13,
             '2PM': 14,
             '3PM': 15,
             '4PM': 16,
             '5PM': 17,
             '6PM': 18,
             '7PM': 19,
             '8PM': 20,
             '9PM': 21,
             '10PM': 22,
             '11PM': 23,
             }


def merge_dict(forecasts: list[dict], alerts: list[dict]):
    merged_list = []
    merged_dict = []
    alerts_new = []
    for alert in alerts:
        if alert == []:
            continue
        f = '%Y-%m-%d %I%p'
        start_dt = datetime.strptime(alert['start'], f)
        end_dt = datetime.strptime(alert['end'], f)
        dt = start_dt
        active = []
        while end_dt not in active:
            active.append(dt)
            dt = dt + timedelta(hours=1)
        active = [x.strftime(f) for x in active]
        for h in active:
            h_dict = {'location': alert['location'], 'date': h.split(' ')[0], 'time': h.split(' ')[1],
                      'event': alert['event']}
            alerts_new.append(h_dict)
    for forecast in forecasts:
        if forecast == []:
            continue
        forecast['alerts'] = []
        for a in alerts_new:
            if forecast['date'] == a['date'] and forecast['time'] == a['time']:
                forecast['alerts'].append(a['event'])
        forecast['alerts'] = list(set(forecast['alerts']))
        forecast['alerts'] = ', '.join(forecast['alerts'])
        merged_dict.append(forecast)
        merged_list.append(tuple(forecast.values()))
    return merged_list, merged_dict