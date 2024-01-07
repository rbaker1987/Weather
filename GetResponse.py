import requests


def get_response(url, params=None):
    try:
        return requests.get(url, params).json()['features']
    except Exception as e:
        return e