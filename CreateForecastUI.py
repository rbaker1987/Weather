import csv
import datetime
from NWS import forecast
import PySimpleGUI as sg
from CreateTextOutput import create_text_output

# Get current date and time
today = datetime.date.today()

# Function to dynamically create a new layout for additional days
def new_layout(i):
    date = today + datetime.timedelta(days=i + 1)
    formatted_date = str(date)
    day_name = date.strftime('%A')
    return [
        [sg.InputText(formatted_date, key=('date', i), size=10),
         sg.InputText(day_name, key=('day', i), size=10),
         sg.T("AM Temp"), sg.InputText(key=("am-t", i), size=5),
         sg.T("PM Temp"), sg.InputText(key=("pm-t", i), size=5),
         sg.T("Weather"), sg.InputText(key=("weather", i), size=30)]
    ]

# Initial column layout
column_layout = [
    [sg.InputText(str(today), key='date', size=10),
     sg.InputText(today.strftime('%A'), key='day', size=10),
     sg.T("AM Temp"), sg.InputText(key="am-t", size=5),
     sg.T("PM Temp"), sg.InputText(key="pm-t", size=5),
     sg.T("Weather"), sg.InputText(key="weather", size=30)]
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
              headings=['  Date  ', '  Day  ', 'AM Temp', 'PM Temp', '      Weather      '])],
    [sg.Multiline(key='output_text', size=(80, 5))],
    [sg.T('Save Location'), sg.InputText(key='save_as'), sg.SaveAs(target='save_as', default_extension='csv'),
     sg.Button('Export CSV'), sg.Button('Export TXT')]
]

# Create the PySimpleGUI window
window = sg.Window('Create Forecast', layout, resizable=True)

# Initialize variables
forecast_table = []
i = 0

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
        date = [values['date']]
        day = [values['day']]
        am_temp = [values['am-t']]
        pm_temp = [values['pm-t']]
        weather = [values['weather']]
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
        forecast_table = [x for x in zip(date, day, am_temp, pm_temp, weather)]
        window['output_table'].update(values=forecast_table)
        forecast_text = create_text_output(forecast_table)
        window['output_text'].update(forecast_text)
    elif event == 'Export CSV':
        file_path = values['save_as']
        if file_path:
            try:
                with open(file_path, 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(['Date', 'Day', 'AM Temp', 'PM Temp', 'Weather'])
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

window.close()
