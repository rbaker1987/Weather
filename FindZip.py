from uszipcode import SearchEngine

def find_zip(location):
    zip_search = SearchEngine()
    city = location.split(',')[0].strip()
    state = location.split(',')[1].strip()
    try:
        return zip_search.by_city_and_state(city, state)[0].zipcode
    except Exception as e:
        return e