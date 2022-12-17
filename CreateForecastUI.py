import csv
import datetime
from NWS import NWS
import PySimpleGUI as sg

today = datetime.date.today()
now = datetime.datetime.now()


def new_layout(i):
    return [
        [sg.T('Date'), sg.InputText(today + datetime.timedelta(days=i + 1), key=('date', i), size=10),
         sg.T("AM Temp"), sg.InputText(key=("am-t", i), size=5),
         sg.T("PM Temp"), sg.InputText(key=("pm-t", i), size=5),
         sg.T("Weather"), sg.InputText(key=("weather", i), size=30)]
    ]


column_layout = [
    [sg.T('Date'), sg.InputText(today, key='date', size=10),
     sg.T("AM Temp"), sg.InputText(key="am-t", size=5),
     sg.T("PM Temp"), sg.InputText(key="pm-t", size=5),
     sg.T("Weather"), sg.InputText(key="weather", size=30)]
]

layout = [
    [sg.T('Location'), sg.InputText('Lindale, TX', key='location')],
    [sg.T('NWS Forecast:'), sg.Button('Load Forecast')],
    [sg.Table(key='nws', values=[], headings=['  Date  ', 'Hour', 'Temp', '  Wind  ', '      Weather      '])],
    [sg.T('Enter forecast for day:')],
    [sg.Column(column_layout, key='column')],
    [sg.Button('Add Day'), sg.Submit()],
    [sg.T('Custom forecast:')],
    [sg.Table(key='output', values=[], headings=['  Date  ', 'AM Temp', 'PM Temp', '      Weather      '])],
    [sg.T('Save Location'), sg.InputText(key='save_as'), sg.SaveAs(target='save_as', default_extension='csv'),
     sg.Button('Export')]
]

window = sg.Window('Create Forecast', layout)

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
        am_temp = [values['am-t']]
        pm_temp = [values['pm-t']]
        weather = [values['weather']]
        date = [today]
        for k, v in values.items():
            if isinstance(k, tuple):
                if k[0] == 'date':
                    date.append(v)
                if k[0] == 'am-t':
                    am_temp.append(v)
                if k[0] == 'pm-t':
                    pm_temp.append(v)
                if k[0] == 'weather':
                    weather.append(v)
        create_forecast = [x for x in zip(date, am_temp, pm_temp, weather)]
        window['output'].update(values=create_forecast)
    elif event == 'Export':
        with open(values['save_as'], 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Date', 'AM Temp', 'PM Temp', 'Weather'])
            writer.writerows(create_forecast)
event, values = window.read()
window.close()
