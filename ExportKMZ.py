import simplekml
from FindLL import find_lat_lon
from prettytable import PrettyTable


def create_table(data):
    pt = PrettyTable()
    pt.field_names = ['Location', 'Date', 'Time', 'Temp', 'Wind', 'A Temp', 'Weather', 'Alerts']
    for row in data:
        pt.add_row(row.values())
    table = pt.get_html_string()
    string = []
    for word in table.split(' '):
        if word != '':
            if word != '':
                if '<table>' in word:
                    word = word.replace('<table>', '<table border="1">')
            string.append(word)
    return ' '.join(string)


def create_kml(kml_name, features):
    kml = simplekml.Kml()
    style = simplekml.Style()

    cities_list = []
    cities = []
    for feature in features:
        loc = feature['location']
        if loc not in cities_list:
            cities_list.append(loc)
    for city in cities_list:
        lat, lon = find_lat_lon(city)
        row = (city, [(lon, lat)], [])
        cities.append(row)
    for feature in features:
        for i, city in enumerate(cities):
            if city[0] == feature['location']:
                cities[i][2].append(feature)
    for city in cities:
        table = create_table(city[2])
        pnt = kml.newpoint(name=city[0], coords=city[1])
        pnt.style.balloonstyle.text = table
        pnt.style.balloonstyle.bgcolor = simplekml.Color.black
        pnt.style.balloonstyle.textcolor = simplekml.Color.aquamarine
        print()
    kml.save(kml_name)
    print()


if __name__ == '__main__':
    k = create_kml('test.kml', [{}])