from pyzipcode import ZipCodeDatabase

def find_zip(location):

    # Create a ZipCodeDatabase object
    zcdb = ZipCodeDatabase()

    # Get zip codes for the city and state
    split = location.split(",")
    city = split[0].strip()
    state =  split[1].strip()
    zip_codes = zcdb.find_zip(city=city, state=state)

    if zip_codes:
        # Return the first zip code found (most likely the primary one)
        return zip_codes[0].zip
    else:
        return "Zip code not found."

# Example usage
print(find_zip("Amarillo, TX"))
