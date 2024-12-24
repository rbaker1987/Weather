from NWS import multi_city_forecasts
from ParseDate import parse_time


def analyze_forecasts(location_list: list, criteria: dict, detail: bool = False):
    forecasts, missings = multi_city_forecasts(location_list)
    highlight_forecasts = []
    for loc, dates in forecasts.items():
        try:
            for date, hours in dates.items():
                for hour, time_forc in hours.items():
                    if len(time_forc) != 0:
                        for k, v in time_forc.items():
                            time = parse_time(hour)
                            if 'temperature' == k:
                                if v < int(criteria['min_temp']):
                                    highlight_forecasts.append((loc, date, time, k, v))
                                if v > int(criteria['max_temp']):
                                    highlight_forecasts.append((loc, date, time, k, v))
                            if 'windSpeed' == k:
                                if int(v.split(' ')[0].strip()) > int(criteria['max_wind']):
                                    highlight_forecasts.append((loc, date, time, k, v))
                            if 'shortForecast' == k:
                                for word in criteria['keywords']:
                                    if word.lower() in v.lower():
                                        highlight_forecasts.append((loc, date, time, k, v))
        except:
            highlight_forecasts.append((loc, dates, dates, dates, dates))
    return highlight_forecasts


if __name__ == '__main__':
    a = analyze_forecasts(['Lindale, TX', 'Boston, MA', 'Seattle, WA'],
                          {'min_temp': '32', 'max_temp': '50', 'max_gust': '20', 'weather': 'Severe'})