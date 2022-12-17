from noaa_sdk import NOAA
from Geolocate import Geolocate
from NWSDateParser import nws_date_parser
from uszipcode import SearchEngine
import datetime

today = datetime.date.today()


class NWS:
    def __init__(self, location):
        self.location = location
        self.nws = NOAA()
        self.geo = Geolocate()
        self.geoloc = self.geo.get_lat_lon(location)
        self.lat = self.geoloc[0]
        self.lon = self.geoloc[1]

    def get_zip(self):
        zip_search = SearchEngine()
        city = self.location.split(',')[0].strip()
        state = self.location.split(',')[1].strip()
        try:
            return zip_search.by_city_and_state(city, state)[0].zipcode
        except Exception as e:
            return e

    def standard(self):
        if isinstance(self.location, str):
            zip = self.get_zip()
        else:
            zip = self.location
        forecast_raw = self.nws.get_forecasts(zip, 'US', type='forecastHourly')
        forecast_dict = {}
        forecast = []
        for d in range(8):
            d_str = str(today + datetime.timedelta(days=d))
            forecast_dict[d_str] = {}
            for h in range(24):
                forecast_dict[d_str][h] = {}
        for row in forecast_raw:
            date = row['startTime'][:10]
            hour = int(row['startTime'][11:13])
            temperature = row['temperature']
            wind_speed = row['windSpeed']
            wind_dir = row['windDirection']
            wind = f'{wind_speed} {wind_dir}'
            weather = row['shortForecast']
            forecast.append((date, hour, temperature, wind, weather))
        return forecast

    def detailed(self):
        forecast_raw = self.nws.points_forecast(self.lat, self.lon, type='forecastGridData')
        forecast_dict = {}
        for property in forecast_raw['properties']:
            if 'values' in forecast_raw['properties'][property]:
                for x in forecast_raw['properties'][property]['values']:
                    valid_raw = x['validTime']
                    valid = nws_date_parser(valid_raw)
                    value_raw = x['value']
                    if valid not in forecast_dict:
                        forecast_dict[valid] = {'f_location': self.geoloc,
                                                'f_update_time': forecast_raw['properties']['updateTime'],
                                                'f_valid_time': forecast_raw['properties']['validTimes'],
                                                property: value_raw}
                    else:
                        forecast_dict[valid][property] = value_raw
        forecast = []
        for k, v in forecast_dict.items():
            f_dict = v
            f_dict['valid'] = k
            forecast.append(f_dict)
        return forecast

    def observations(self):
        obs_raw = self.nws.get_observations(self.location, 'US')
        obs_list = [x for x in obs_raw]
        observations_dict = {}
        for obs_row in obs_list:
            timestamp = obs_row['timestamp']
            observations_dict[timestamp] = {}
            for prop in obs_row:
                if prop == 'station':
                    observations_dict[timestamp][prop] = obs_row[prop].split('/')[-1]
                if isinstance(obs_row[prop], dict) and 'value' in obs_row[prop]:
                    observations_dict[timestamp][prop] = obs_row[prop]['value']
        observations = []
        for k, v in observations_dict.items():
            o_dict = v
            o_dict['valid'] = k
            observations.append(o_dict)
        return observations


if __name__ == '__main__':
    # location = input('Address to get forecast for: ')
    location = 75771

    nws = NWS(location)
    f = nws.standard()
    f_keys = list(f[0].keys())
    o = nws.observations()
    o_keys = list(f[0].keys())
    quit()
