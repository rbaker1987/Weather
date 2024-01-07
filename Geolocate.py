from geopy.geocoders import Nominatim
import time
from pprint import pprint


class Geolocate:
    def __init__(self):
        # instantiate a new Nominatim client
        self.app = Nominatim(user_agent="weather")

    def get_lat_lon(self, location: str):
        sleep = 0
        for x in range(0, 10):
            try:
                print('Attempting to obtain Lat/Lon from address. Attempt 1')
                location_raw = self.app.geocode(location).raw
                location_lat = location_raw['lat']
                location_lon = location_raw['lon']
                location_lat_lon = ','.join([location_lat, location_lon])
                print('Success')
                return float(location_lat), float(location_lon)
            except:
                if x < 10:
                    print(f'Attempting to obtain Lat/Lon from address. Attempt {sleep + 1}')
                    sleep += 1
                    time.sleep(sleep)
                    return self.get_lat_lon(location)
                else:
                    print(f'Failed after {sleep + 1} attempts.')
                    break

    def get_address(self, latitude: str, longitude: str, language: str = "en"):
        """This function returns a location as raw from a location
        will repeat until success"""
        # build coordinates string to pass to reverse() function
        coordinates = f"{latitude}, {longitude}"
        # sleep for a second to respect Usage Policy
        sleep = 0
        for x in range(0, 10):
            try:
                return self.app.reverse(coordinates, language=language).raw
            except:
                if x < 10:
                    sleep += 1
                    time.sleep(sleep)
                    return self.get_address(latitude, longitude)
                else:
                    break


if __name__ == '__main__':
    location = input('Location to convert to lat/lon: ')
    lat_lon = input('Lat, Lon to get address for: ')
    lat_lon_split = lat_lon.split(',')
    lat = float(lat_lon_split[0].strip())
    lon = float(lat_lon_split[1].strip())

    geo = Geolocate()
    geo.get_lat_lon(location)
    geo.get_address(str(lat), str(lon))
