// Place search and "use my location". The chosen place is carried in the URL
// (/weather/<lat>,<lon>/), so nothing is stored on the server or in the session.
(function () {
  'use strict';

  const root = document.getElementById('placeSearch');
  if (!root) {
    return;
  }

  const form = document.getElementById('placeSearchForm');
  const input = document.getElementById('placeSearchInput');
  const status = document.getElementById('placeSearchStatus');
  const results = document.getElementById('placeSearchResults');
  const myLocation = document.getElementById('placeUseMyLocation');
  const geocodeUrl = root.dataset.geocodeUrl;

  function setStatus(message, isError) {
    status.textContent = message;
    status.classList.toggle('text-danger', Boolean(isError));
  }

  function goTo(latitude, longitude, name) {
    const coords = `${latitude.toFixed(4)},${longitude.toFixed(4)}`;
    const query = name ? `?name=${encodeURIComponent(name)}` : '';
    window.location.href = `/weather/${coords}/${query}`;
  }

  function showResults(items) {
    results.replaceChildren();
    items.forEach(function (item) {
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      const link = document.createElement('a');
      link.href = item.url;
      link.textContent = item.label;
      link.className = 'stretched-link text-decoration-none';
      li.appendChild(link);
      results.appendChild(li);
    });
  }

  async function search(query) {
    setStatus('Searching…', false);
    results.replaceChildren();
    try {
      const response = await fetch(`${geocodeUrl}?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || 'Search failed', true);
        return;
      }
      if (data.results.length === 0) {
        setStatus('No places found. Try a nearby city or ZIP code.', true);
      } else if (data.results.length === 1) {
        window.location.href = data.results[0].url;
      } else {
        setStatus('Choose a place:', false);
        showResults(data.results);
      }
    } catch (_error) {
      setStatus('Search failed. Check your connection and try again.', true);
    }
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    const query = input.value.trim();
    if (query) {
      search(query);
    }
  });

  myLocation.addEventListener('click', function () {
    if (!navigator.geolocation) {
      setStatus('Your browser does not support location lookup.', true);
      return;
    }
    setStatus('Finding your location…', false);
    navigator.geolocation.getCurrentPosition(
      function (position) {
        goTo(position.coords.latitude, position.coords.longitude, 'My location');
      },
      function () {
        setStatus('Could not get your location. Search for a place instead.', true);
      },
      { timeout: 10000 }
    );
  });
})();
