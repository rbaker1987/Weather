from noaa_sdk import NOAA
from Geolocate import Geolocate
from Converter import MetricToImperial
from NWSDateParser import nws_date_parser


class NWS:
    def __init__(self, location: str):
        self.nws = NOAA()
        self.geo = Geolocate()
        self.mi = MetricToImperial()
        self.geoloc = self.geo.get_lat_lon(location)
        self.lat = self.geoloc[0]
        self.lon = self.geoloc[1]

    def forecasts(self):
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
                valid = nws_date_parser(valid_raw)
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
        forecast = list(
            zip(temperature, dewpoint, windDirection, windSpeed, windGust, weather, probabilityOfPrecipitation,
                quantitativePrecipitation, iceAccumulation, snowfallAmount))
        # forecast_series = pd.Series(parameter_forecast)
        # forecast_series.to_csv(f'{parameter}.csv')
        return forecast

    def observations(self):
        observations = self.nws.get_observations(self.geoloc, 'US')
        for observation in observations:
            print(observation)


if __name__ == '__main__':
    location = input('Address to get forecast for: ')

    nws = NWS(location)
    nws.forecasts()
    # nws.observations()
