from noaa_sdk import NOAA
from Geolocate import Geolocate
from NWSDateParser import nws_date_parser


class NWS:
    def __init__(self, location: str):
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
        # observations = {'location': obs_raw[0]['station'].split('/')[-1]}
        for o in obs_raw:
            for prop in o:
                if 'value' in o[prop]:
                    for x in obs_raw['properties'][property]['values']:
                        valid_raw = x['validTime']
                        valid = nws_date_parser(valid_raw)
                        value_raw = x['value']
                        if valid not in forecast:
                            forecast[valid] = {property: value_raw}
                        else:
                            forecast[valid][property] = value_raw
        return forecast


if __name__ == '__main__':
    location = input('Address to get forecast for: ')
    # location = '13851 CR 4200 Lindale, TX'

    nws = NWS(location)
    f = nws.forecasts()
    o = nws.observations()
    quit()
