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
    f = nws.forecasts()
    f_keys = list(f[0].keys())
    o = nws.observations()
    o_keys = list(f[0].keys())
    quit()
