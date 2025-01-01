import sqlite3
from datetime import datetime
from NWS import multi_city_forecasts
from ParseDate import parse_time

def parse_forecasts(location_list: list):
    forecasts, missing = multi_city_forecasts(location_list, 'standard')
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
                    # If temperature (T) is above 50F or wind speed (V) is below 5mph
                    # then the apparent temperature (aT) is equal to T
                    if T > 50 or V < 5:
                        aT = T
                    else:
                        aT = int(35.74 + (0.6215 * T) - 35.75 * (V ** 0.16) + 0.4275 * T * (V ** 0.16))
                    weather = time_forc['shortForecast']
                    try:
                        loc_dict = {'location': loc, 'date': date, 'time': time, 'temperature': T, 'wind': V,
                                    'apparent_temperature': aT, 'weather': weather}
                    except:
                        loc_dict = {'location': loc, 'date': date, 'time': time, 'temperature': 'Error',
                                    'wind': 'Error', 'apparent_temperature': 'Error', 'weather': 'Error'}
                    forecasts_dict.append(loc_dict)
    return forecasts_dict, missing


def save_to_database(forecasts):
    conn = sqlite3.connect('weather_data.db')  # Connect to SQLite database
    cursor = conn.cursor()

    # Get current timestamp for the `valid` field
    valid_timestamp = datetime.now()

    # Insert data into the table (do not drop the table)
    for forecast in forecasts:
        # Convert `forecast['time']` to 24-hour format (e.g., "01PM" becomes "13:00")
        time_24hr = datetime.strptime(f"{forecast['time']}", "%I%p").strftime("%H:%M")

        # Combine `date` and the new `time_24hr` into a single `DATETIME` value for `timestamp`
        timestamp = datetime.strptime(f"{forecast['date']} {time_24hr}", "%Y-%m-%d %H:%M")

        cursor.execute('''
            INSERT INTO forecasts (location, date, time, timestamp, valid, temperature, wind, apparent_temperature, weather)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            forecast['location'],
            forecast['date'],
            forecast['time'],
            timestamp,
            valid_timestamp,
            forecast['temperature'],
            forecast['wind'],
            forecast['apparent_temperature'],
            forecast['weather']
        ))

    conn.commit()  # Save changes
    conn.close()  # Close connection


if __name__ == '__main__':
    # Parse forecasts for given locations
    forecast, missing = parse_forecasts(['Lindale, TX'])

    # Save forecasts to the database
    save_to_database(forecast)
