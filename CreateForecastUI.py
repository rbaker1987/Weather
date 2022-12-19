import csv
import datetime
from NWS import NWS
import PySimpleGUI as sg
from CreateTextOutput import create_text_output

today = datetime.date.today()
now = datetime.datetime.now()


def new_layout(i):
    return [
        [sg.InputText(today + datetime.timedelta(days=i + 1), key=('date', i), size=10),
         sg.InputText(
             datetime.datetime.strptime(str(today + datetime.timedelta(days=i + 1)), '%Y-%m-%d').strftime('%A'), key=(
                 'day', i), size=10),
         sg.T("AM Temp"), sg.InputText(key=("am-t", i), size=5),
         sg.T("PM Temp"), sg.InputText(key=("pm-t", i), size=5),
         sg.T("Weather"), sg.InputText(key=("weather", i), size=30)]
    ]


column_layout = [
    [sg.InputText(today, key='date', size=10),
     sg.InputText((today.strftime('%A')), key='day', size=10),
     sg.T("AM Temp"), sg.InputText(key="am-t", size=5),
     sg.T("PM Temp"), sg.InputText(key="pm-t", size=5),
     sg.T("Weather"), sg.InputText(key="weather", size=30)]
]

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
              headings=['  Date  ', ' Day ', 'AM Temp', 'PM Temp', '      Weather      '])],
    [sg.Multiline(key='output_text', size=(80, 5))],
    [sg.T('Save Location'), sg.InputText(key='save_as'), sg.SaveAs(target='save_as', default_extension='csv'),
     sg.Button('Export CSV'), sg.Button('Export TXT')]
]

window = sg.Window('Create Forecast', layout, resizable=True)

create_forecast = []
i = 0
while True:
    event, values = window.read()
    location = values['location']
    if event == sg.WIN_CLOSED or event == 'Cancel':
        break
    elif event == 'Load Forecast':
        nws = NWS(values['location'])
        forecast = nws.standard()
        window['nws'].update(values=forecast)
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
        with open(values['save_as'], 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Date', 'AM Temp', 'PM Temp', 'Weather'])
            writer.writerows(forecast_text)
    elif event == 'Export TXT':
        with open(values['save_as'], 'w', newline='') as file:
            file.write(forecast_text)
event, values = window.read()
window.close()
