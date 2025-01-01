import csv
import PySimpleGUI as sg
# from AnalyzeForecast import analyze_forecasts
from ParseForecasts import parse_forecasts
from ParseAlerts import parse_alerts
from MergeDict import merge_dict
from ExportKMZ import create_kml


def loc_row(i):
    return [
        [sg.T("City"), sg.InputText(key=("city", i), size=20), sg.T("State"), sg.InputText(key=("state", i), size=3)]]


column_layout = [
    [sg.T("City"), sg.InputText('Austin', key="city", size=20), sg.T("State"), sg.InputText('TX', key="state", size=3)]
]

layout = [
    [sg.T('Locations to obtain forecast for:')],
    [sg.Column(column_layout, key='column')],
    [sg.Button('Run Forecast Report'), sg.Button('Add City', enable_events=True, key="add"),
     sg.Button('Run Default Cities')],
    [sg.T('NWS Forecasts:')],
    [sg.Table(key='forecast', values=[],
              headings=['   Location   ', '  Date  ', 'Time', 'Temp', 'Wind', 'A Temp', '      Weather      ',
                        '   Alert   '],
              size=(80, 10))],
    # [sg.T('Criteria to highlight:')],
    # [sg.T('Min Temp (F)'), sg.InputText(key='min_t', size=3, default_text=32),
    #  sg.T('Max Temp (F)'), sg.InputText(key='max_t', size=3, default_text=90),
    #  sg.T('Min Apparent Temp (F)'), sg.InputText(key='min_at', size=3, default_text=20),
    #  sg.T('Max Apparent Temp (F)'), sg.InputText(key='max_at', size=3, default_text=100)],
    # [sg.T('Max Sustained Wind (mph)'), sg.InputText(key='wind', size=3, default_text=20)],
    # [sg.T('Keywords to search for:')],
    # [sg.Checkbox('Heavy', key='heavy', default=True), sg.Checkbox('Strong', key='strong', default=True),
    #  sg.Checkbox('Hurricane', key='hurricane', default=True),
    #  sg.Checkbox('Tropical Storm', key='trop_storm', default=True)],
    # [sg.Checkbox('Flood', key='flood', default=True), sg.Checkbox('Thunderstorm', key='thunder', default=True),
    #  sg.Checkbox('Severe', key='severe', default=True), sg.Checkbox('Blowing', key='blowing', default=True)],
    # [sg.Checkbox('Rain', key='rain', default=True), sg.Checkbox('Snow', key='snow', default=True), sg.Checkbox(
    #     'Sleet', key='sleet', default=True), sg.Checkbox('Freezing Rain', key='freezing_rain', default=True),
    #  sg.Checkbox('Ice', key='ice', default=True)],
    # [sg.Button('Run Criteria Report')],

    [sg.T('Missing Forecasts:')],
    [sg.Table(key='m_forecasts', values=[], headings=['   Location   ', '      Reason      '], size=(80, 5))],
    [sg.InputText('CSV Save As', key='save_as_csv', size=30),
     sg.FileSaveAs('CSV Save As', target='save_as_csv', file_types=(('CSV', 'csv'),)), sg.Button('Export CSV')],
    # [sg.InputText('KML Save As', key='save_as_kml', size=30),
    #  sg.FileSaveAs('KML Save As', target='save_as_kml', file_types=(('KML', 'kml'),)), sg.Button('Export KML')],
    [sg.InputText('C:/Users/rbaker/Downloads/test.kml', key='save_as_kml', size=30),
     sg.FileSaveAs('KML Save As', target='save_as_kml', file_types=(('KML', 'kml'),)), sg.Button('Export KML')],
    [sg.T('', key='response')]
]

window = sg.Window("Generate Forecasts", layout, element_padding=(6, 5), resizable=True)
i = 1
while True:
    locations = []
    event, values = window.read()
    if event == sg.WIN_CLOSED:
        break
    elif event == 'add':
        window.extend_layout(window['column'], loc_row(i))
        i += 1

    # elif event == 'Run Criteria Report':
    #     window['response'].update('Running Criteria Report')
    #     cities = [values['city']]
    #     states = [values['state']]
    #     keywords = []
    #     for k, v in values.items():
    #         if isinstance(k, tuple):
    #             if k[0] == 'city':
    #                 cities.append(v)
    #             if k[0] == 'state':
    #                 states.append(v)
    #         if v == True:
    #             keywords.append(k)
    #     locations = [f'{x[0]}, {x[1]}' for x in zip(cities, states)]
    #     criteria = {'min_temp': values['min_t'], 'max_temp': values['max_t'],
    #                 'min_atemp': values['min_at'], 'max_atemp': values['max_at'],
    #                 'max_wind': values['wind'], 'keywords': keywords}
    #     result = analyze_forecasts(locations, criteria)
    #     if isinstance(result, str):
    #         window['response'].update(result)
    #         break
    #     window['output'].update(values=result)
    #     window['response'].update('Ran Criteria Report')

    elif event == 'Run Forecast Report':
        window['response'].update('Running Forecast Report')
        cities = [values['city']]
        states = [values['state']]
        for k, v in values.items():
            if isinstance(k, tuple):
                if k[0] == 'city':
                    cities.append(v)
                if k[0] == 'state':
                    states.append(v)
        locations = [f'{x[0]}, {x[1]}' for x in zip(cities, states)]
        forecasts_dict, forecasts_missing = parse_forecasts(locations)
        alerts_dict, alerts_missing = parse_alerts(locations)
        merged_list, merged_dict = merge_dict(forecasts_dict, alerts_dict)
        window['forecast'].update(values=merged_list)
        window['response'].update('Ran Forecast Report')
        window['m_forecasts'].update(values=forecasts_missing)

    elif event == 'Run Default Cities':
        window['response'].update('Running Forecast Report')
        locations = ['Pahrump, NV',
                     'Tyler, TX',
                     'Fort Worth, TX',
                     'Dallas, TX',
                     'Killeen, TX',
                     'Austin, TX',
                     'Waco, TX',
                     'Midland, TX',
                     'Silsbee, TX',
                     'Lumberton, TX',
                     'Paris, TX',
                     'Nacogdoches, TX',
                     'Longview, TX',
                     'Madison, FL',
                     'Tallahassee, FL',
                     'Tampa, FL',
                     'Moore Haven, FL',
                     'Columbia, SC',
                     'Greenville, SC',
                     'Duncan, OK',
                     'Lawton, OK',
                     'Raleigh, NC',
                     'Ronoake Rapids, NC',
                     'Sandusky, OH',
                     'Cochitii, OH',
                     'Norwalk, OH',
                     'Columbus, OH',
                     ]
        forecasts_dict, forecasts_missing = parse_forecasts(locations)
        alerts_dict, alerts_missing = parse_alerts(locations)
        merged_list = merge_dict(forecasts_dict, alerts_dict)
        window['forecast'].update(values=merged_list)
        window['response'].update('Ran Forecast Report')
        window['m_forecasts'].update(values=forecasts_missing)
        window['m_alerts'].update(values=alerts_missing)

    elif event == 'Export CSV':
        window['response'].update('Exporting to csv')
        try:
            with open(values['save_as_csv'], 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['Location', 'Date', 'Time', 'Temp', 'Wind', 'A Temp', 'Weather', 'Alerts'])
                writer.writerows(merged_list)
            window['response'].update('Exported to csv')
        except:
            if '.csv' not in values['save_as_csv']:
                window['response'].update('Save as csv')
            else:
                window['response'].update('Forecast not ran')

    elif event == 'Export KML':
        window['response'].update('Exporting to kml')
        try:
            create_kml(values['save_as_kml'], merged_dict)
            window['response'].update('Exported to kml')
        except:
            if '.kml' not in values['save_as_kml']:
                window['response'].update('Save as kml')
            else:
                window['response'].update('Forecast not ran')

event, values = window.read()
window.close()