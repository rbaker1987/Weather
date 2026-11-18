"""URL path converters."""


class CoordinatesConverter:
    """Match a ``lat,lon`` pair such as ``35.2226,-97.4395``."""

    regex = r"-?\d{1,3}(?:\.\d+)?,-?\d{1,3}(?:\.\d+)?"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return str(value)
