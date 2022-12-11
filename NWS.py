from noaa_sdk import NOAA
from Geolocate import Geolocate
from NWSDateParser import nws_date_parser


class NWS:
    def __init__(self, location):
        self.location = location
        self.nws = NOAA()
        self.geo = Geolocate()
        self.geoloc = self.geo.get_lat_lon(location)
        self.lat = self.geoloc[0]
        self.lon = self.geoloc[1]

    def forecasts(self):
        forecast_raw = self.nws.points_forecast(self.lat, self.lon, type='forecastGridData')
        forecast = {'location': self.geoloc, 'update_time': forecast_raw['properties']['updateTime'],
                    'valid_time': forecast_raw['properties']['validTimes']}
        for property in forecast_raw['properties']:
            if 'values' in forecast_raw['properties'][property]:
                for x in forecast_raw['properties'][property]['values']:
                    valid_raw = x['validTime']
                    valid = nws_date_parser(valid_raw)
                    value_raw = x['value']
                    if valid not in forecast:
                        forecast[valid] = {property: value_raw}
                    else:
                        forecast[valid][property] = value_raw
        return forecast

    def observations(self):
        obs_raw = self.nws.get_observations(self.location, 'US')
        obs_list = [x for x in obs_raw]
        stations = list(set([x['station'].split('/')[-1] for x in obs_list]))
        observations = {'station': stations[0]}
        for obs_row in obs_list:
            timestamp = obs_row['timestamp']
            observations[timestamp] = {}
            for prop in obs_row:
                if isinstance(obs_row[prop], dict) and 'value' in obs_row[prop]:
                    observations[timestamp][prop] = obs_row[prop]['value']
        return observations


if __name__ == '__main__':
    # location = input('Address to get forecast for: ')
    location = 75771

    nws = NWS(location)
    f = nws.forecasts()
    o = nws.observations()
    quit()
