from NWS import multi_city_forecasts
from ParseDate import parse_time


def parse_forcasts(location_list: list):
    forecasts, missing = multi_city_forecasts(location_list, 'standard')
    # forecasts_list = []
    forecasts_dict = []
    for loc, dates in forecasts.items():
        if not isinstance(dates, dict):
            continue
        for date, hours in dates.items():
            for hour, time_forc in hours.items():
                time = parse_time(hour)
                if len(time_forc) != 0:
                    T = time_forc['temperature']
                    V = int(time_forc['windSpeed'])
                    if T > 50 or V < 5:
                        aT = T
                    else:
                        aT = int(35.74 + (0.6215 * T) - 35.75 * (V ** 0.16) + 0.4275 * T * (V ** 0.16))
                    weather = time_forc['shortForecast']
                    try:
                        # forecasts_list.append((loc, date, time, T, V, aT, weather))
                        loc_dict = {'location': loc, 'date': date, 'time': time, 'temperature': T, 'wind': V,
                                    'apparent_temperature': aT, 'weather': weather}
                    except:
                        # forecasts_list.append((loc, date, time, 'Error', 'Error', 'Error', 'Error'))
                        loc_dict = {'location': loc, 'date': date, 'time': time, 'temperature': 'Error',
                                    'wind': 'Error', 'apparent_temperature': 'Error', 'weather': 'Error'}
                    forecasts_dict.append(loc_dict)
    return forecasts_dict, missing


if __name__ == '__main__':
    print(parse_forcasts(['Lindale, TX']))
    print()