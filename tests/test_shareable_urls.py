"""The pieces of shareable views that the server renders (the rest runs in the browser)."""

import pytest


@pytest.mark.django_db
class TestShareableViews:
    def test_home_offers_the_last_place_remembered_on_this_device(self, client):
        html = client.get("/").content.decode()

        assert 'id="lastPlace"' in html
        assert "weather:lastPlace" in html
        # Only same-site place paths are ever linked from the stored value.
        assert "startsWith('/weather/')" in html

    def test_place_page_remembers_the_place_and_restores_the_climate_date(self, client):
        html = client.get(
            "/weather/35.2226,-97.4395/", {"name": "Norman, OK"}
        ).content.decode()

        assert "weather:lastPlace" in html
        assert "/weather/35.222600,-97.439500/?name=" in html
        assert "searchParams.set('month'" in html
        assert "sharedParams.get('month')" in html

    def test_place_page_with_invalid_coordinates_does_not_try_to_remember_it(
        self, client
    ):
        html = client.get("/weather/95.0,-97.0/").content.decode()

        assert "weather:lastPlace" not in html

    def test_models_page_reads_and_writes_the_selection(self, client):
        html = client.get("/models/").content.decode()

        assert "syncSelectionToUrl" in html
        assert "restoreSelectionFromUrl" in html
        assert "params.get('models')" in html
        assert "searchParams.set('models'" in html
