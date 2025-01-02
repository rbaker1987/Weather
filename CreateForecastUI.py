import csv
import datetime
from NWS import forecast
import PySimpleGUI as sg
from CreateTextOutput import create_text_output

# Get current date and time
today = datetime.date.today()

# List of weather options with associated emojis
weather_list = [
    "Sunny", "Partly Cloudy", "Cloudy", "Foggy", "Windy",
    "Drizzle", "Rain Showers", "Rain", "Heavy Rain", "Thunderstorms",
    "Flurries", "Snow Showers", "Snow", "Heavy Snow", "Freezing Drizzle",
    "Freezing Rain", "Mixed Showers", "Sleet"
]

emoji_list = [
    "☀️", "⛅", "☁️", "🌫️", "💨", "🌦️", "🌧️", "🌩️", "❄️", "🧊", "🌡️", "🥶", "🔥"
]


# Function to dynamically create a new layout for additional days
def new_layout(i):
    date = today + datetime.timedelta(days=i + 1)
    formatted_date = str(date)
    day_name = date.strftime('%A')
    return [
        [sg.InputText(formatted_date, key=('date', i), size=10),
         sg.InputText(day_name, key=('day', i), size=10),
         sg.T("AM Temp"), sg.InputText(key=("am-t", i), size=5, justification='right'),
         sg.T("PM Temp"), sg.InputText(key=("pm-t", i), size=5, justification='right'),
         sg.T("Weather"), sg.Combo(weather_list, key=("weather", i), size=30),
         sg.T("Emoji"), sg.Combo(emoji_list, key=("emoji", i), size=5)]
    ]


# Initial column layout
column_layout = [
    [sg.InputText(str(today), key='date', size=10),
     sg.InputText(today.strftime('%A'), key='day', size=10),
     sg.T("AM Temp"), sg.InputText(key="am-t", size=5, justification='right'),
     sg.T("PM Temp"), sg.InputText(key="pm-t", size=5, justification='right'),
     sg.T("Weather"), sg.Combo(weather_list, key="weather", size=30, enable_events=True),
     sg.T("Emoji"), sg.Combo(emoji_list, key="emoji", size=5)]
]

# Main layout
layout = [
    [sg.T('Location'), sg.InputText('Lindale, TX', key='location')],
    [sg.T('NWS Forecast:'), sg.Button('Load Forecast')],
    [sg.Table(key='nws', values=[], size=(80, 5),
              headings=['  Date  ', '  Day  ', 'Time', 'Temp', '  Wind  ', '      Weather      '])],
    [sg.T('Enter forecast for day:')],
    [sg.Column(column_layout, key='column')],
    [sg.Button('Add Day'), sg.Submit()],
    [sg.T('Custom forecast:')],
    [sg.Table(key='output_table', values=[], size=(80, 5),
              headings=['  Date  ', '  Day  ', 'AM Temp', 'PM Temp', 'Weather', 'Emoji'])],
    [sg.Multiline(key='output_text', size=(80, 5))],
    [sg.Button('Copy')],
    [sg.T('Save Location'), sg.InputText(key='save_as'), sg.SaveAs(target='save_as', default_extension='csv'),
     sg.Button('Export CSV'), sg.Button('Export TXT')]
]

# Create the PySimpleGUI window
window = sg.Window('Create Forecast', layout, resizable=True)

# Initialize variables
forecast_table = []
i = 0


# Function to check if a string is numeric
def is_numeric(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


# Event loop
while True:
    event, values = window.read()
    if event == sg.WIN_CLOSED or event == 'Cancel':
        break
    elif event == 'Load Forecast':
        try:
            nws_forecast = forecast(values['location'])
            window['nws'].update(values=nws_forecast)
        except Exception as e:
            sg.popup_error(f"Error loading forecast: {e}")
    elif event == 'Add Day':
        window.extend_layout(window['column'], new_layout(i))
        i += 1
    elif event == 'Submit':
        # Validate the temperature inputs
        valid = True
        for i in range(i + 1):
            am_temp = values.get(f"am-t", "").strip()
            pm_temp = values.get(f"pm-t", "").strip()

            if not (is_numeric(am_temp) and is_numeric(pm_temp)):
                valid = False
                sg.popup_error(
                    f"Invalid temperature input for day {i + 1}. Please enter numeric values for both AM and PM temperatures.")
                break

        if valid:
            date = [values['date']]
            day = [values['day']]
            am_temp = [values['am-t']]
            pm_temp = [values['pm-t']]
            weather = [values['weather']]
            emoji = [values['emoji']]
            for k, v in values.items():
                if isinstance(k, tuple):
                    if k[0] == 'date':
                        date.append(v)
                    if k[0] == 'day':
                        day.append(v)
                    if k[0] == 'am-t':
                        am_temp.append(v)
                    if k[0] == 'pm-t':
                        pm_temp.append(v)
                    if k[0] == 'weather':
                        weather.append(v)
                    if k[0] == 'emoji':
                        emoji.append(v)
            forecast_table = [x for x in zip(date, day, am_temp, pm_temp, weather, emoji)]
            window['output_table'].update(values=forecast_table)
            forecast_text = create_text_output(forecast_table)
            window['output_text'].update(forecast_text)
    elif event == 'Export CSV':
        file_path = values['save_as']
        if file_path:
            try:
                with open(file_path, 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(['Date', 'Day', 'AM Temp', 'PM Temp', 'Weather', 'Emoji'])
                    writer.writerows(forecast_table)
            except Exception as e:
                sg.popup_error(f"Error saving CSV: {e}")
        else:
            sg.popup_error('Please provide a valid file name for saving.')
    elif event == 'Export TXT':
        file_path = values['save_as']
        if file_path:
            try:
                with open(file_path, 'w') as file:
                    file.write(create_text_output(forecast_table))
            except Exception as e:
                sg.popup_error(f"Error saving TXT: {e}")
        else:
            sg.popup_error('Please provide a valid file name for saving.')
    elif event == 'Copy':
        # Copy the content of the output text box to the clipboard
        sg.clipboard_copy(values['output_text'])
        sg.popup('Text copied to clipboard!')

window.close()
