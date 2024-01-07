from noaa_sdk import NOAA
from Geolocate import Geolocate
from Converter import MetricToImperial
from NWSDateParser import parse_times
import json


class Forecast:
    def __init__(self, location: str):
        self.nws = NOAA()
        self.geo = Geolocate()
        self.mi = MetricToImperial()
        self.geoloc = self.geo.get_lat_lon(location)
        self.lat = self.geoloc[0]
        self.lon = self.geoloc[1]

    def get_forecast(self):
        forecast_raw = self.nws.points_forecast(self.lat, self.lon, type='forecastGridData')
        forecast_parameters = ['temperature', 'dewpoint', 'windDirection', 'windSpeed', 'windGust', 'weather',
                               'probabilityOfPrecipitation', 'quantitativePrecipitation', 'iceAccumulation',
                               'snowfallAmount']
        temperature = []
        dewpoint = []
        windDirection = []
        windSpeed = []
        windGust = []
        weather = []
        probabilityOfPrecipitation = []
        quantitativePrecipitation = []
        iceAccumulation = []
        snowfallAmount = []
        for parameter in forecast_parameters:
            valid_list = []
            value_list = []
            for x in forecast_raw['properties'][parameter]['values']:
                valid_raw = x['validTime']
                valid = parse_times(valid_raw)
                value_raw = x['value']
                # value = int(self.mi.c_to_f(value_raw))
                valid_list.append(valid)
                value_list.append(value_raw)
            parameter_forecast = list(zip(valid_list, value_list))
            if parameter == 'temperature':
                temperature.append(parameter_forecast)
            if parameter == 'dewpoint':
                dewpoint.append(parameter_forecast)
            if parameter == 'windDirection':
                windDirection.append(parameter_forecast)
            if parameter == 'windSpeed':
                windSpeed.append(parameter_forecast)
            if parameter == 'windGust':
                windGust.append(parameter_forecast)
            if parameter == 'weather':
                weather.append(parameter_forecast)
            if parameter == 'probabilityOfPrecipitation':
                probabilityOfPrecipitation.append(parameter_forecast)
            if parameter == 'quantitativePrecipitation':
                quantitativePrecipitation.append(parameter_forecast)
            if parameter == 'iceAccumulation':
                iceAccumulation.append(parameter_forecast)
            if parameter == 'snowfallAmount':
                snowfallAmount.append(parameter_forecast)
        forecast = zip(temperature, dewpoint, windDirection, windSpeed, windGust, weather, probabilityOfPrecipitation,
                       quantitativePrecipitation, iceAccumulation, snowfallAmount)
        # forecast_series = pd.Series(parameter_forecast)
        # forecast_series.to_csv(f'{parameter}.csv')
        return forecast

    def parse_forecast(self):
        forecast = self.get_forecast()
        pass


class Observations:
    def observations(self):
        observations = self.nws.get_observations(self.geoloc, 'US')
        for observation in observations:
            print(observation)


if __name__ == '__main__':
    # with open('secrets.json') as f:
    #     data = json.load(f)
    #     address = data['address']
    #
    # pass

    location = '332 Lakeview, Dr, Hideaway, TX, USA'
    # try:
    #     location = address
    # except:
    #     location = input('Address to get forecast for: ')

    f = Forecast(location)
    f.parse_forecast()
    # o = Observations(location)
    # o.observations()


# with open('secrets.json') as f:
    #     data = json.load(f)
    #     address = data['address']