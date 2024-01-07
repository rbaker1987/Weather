from NWS import multi_city_forecasts
from ParseDate import parse_date_time
from datetime import datetime, timedelta


def parse_alerts(location_list: list):
    alerts, missing = multi_city_forecasts(location_list, 'alerts')
    # alerts_list = []
    alerts_dict = []
    for city in alerts:
        for alert in alerts[city]:
            start_date, start_time = parse_date_time(alert['start'])
            if alert['end'] != None:
                end_date, end_time = parse_date_time(alert['end'])
            else:
                end_date = datetime.strftime(datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=7), '%Y-%m-%d')
                end_time = start_time
            start = f'{start_date} {start_time}'
            end = f'{end_date} {end_time}'
            # alerts_list.append((k, x['event'], start, end))
            loc_dict = {'location': city, 'event': alert['event'], 'start': start, 'end': end}
            alerts_dict.append(loc_dict)
    return alerts_dict, missing


if __name__ == '__main__':
    alerts = parse_alerts(['Lindale, TX', 'Norman, OK', 'Kansas City, MO'])
    print()