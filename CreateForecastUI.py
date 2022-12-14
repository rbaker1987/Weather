import datetime

import PySimpleGUI as sg

today = datetime.date.today()


def new_layout(i):
    return [
        [sg.T("AM Temp"), sg.InputText(key=("am-t", i), size=5), sg.T("PM Temp"), sg.InputText(key=("pm-t", i), size=5),
         sg.T("Weather"), sg.InputText(key=("weather", i))]]


column_layout = [
    [sg.T("AM Temp"), sg.InputText(key="am-t", size=5), sg.T("PM Temp"), sg.InputText(key="pm-t", size=5),
     sg.T("Weather"), sg.InputText(key="weather"), sg.Button('Add', enable_events=True, key="add")]
]

sg.theme('DarkAmber')  # Add a touch of color
# All the stuff inside your window.
layout = [[sg.Column(column_layout, key='column')], [sg.Submit()]]

# Create the Window
window = sg.Window('Create Forecast', layout)
# Event Loop to process "events" and get the "values" of the inputs
i = 1
while True:
    event, values = window.read()
    create_forecast = []
    if event == sg.WIN_CLOSED or event == 'Cancel':  # if user closes window or clicks cancel
        break
    elif event == 'add':
        f_date = today + datetime.timedelta(days=i-1)
        f_row = {'created': today, 'date': f_date, 'temp_am': values['am-t'],
                 'temp_pm': values['pm-t'], 'weather': values['weather']}
        create_forecast.append(f_row)
        window.extend_layout(window['column'], new_layout(i))
        i += 1
    elif event == 'Submit':
        f_date = today + datetime.timedelta(days=i - 1)
        f_row = {'created': today, 'date': f_date, 'temp_am': values['am-t'],
                 'temp_pm': values['pm-t'], 'weather': values['weather']}
        create_forecast.append(f_row)
        break

event, values = window.read()
print(create_forecast)
window.close()
