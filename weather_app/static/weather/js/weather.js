// Weather App JavaScript
document.addEventListener('DOMContentLoaded', function () {
  // Initialize tooltips
  const tooltipTriggerList = [].slice.call(
    document.querySelectorAll('[data-bs-toggle="tooltip"]')
  );
  tooltipTriggerList.forEach(function (el) {
    new bootstrap.Tooltip(el);
  });

  // Initialize modals
  const modalList = [].slice.call(document.querySelectorAll('.modal'));
  modalList.forEach(function (modal) {
    new bootstrap.Modal(modal);
  });

  // Initialize weather cards
  initializeWeatherCards();
});

// Centralized weather icon logic
function getWeatherIcon(conditions, isDaytime = true, pop = null) {
  const c = conditions.toLowerCase();
  const isStorm = c.includes('storm') || c.includes('thunder') || c.includes('t-storm');
  const isSnow = c.includes('snow') || c.includes('flurries') || c.includes('blizzard');
  const isIce =
    c.includes('ice') ||
    c.includes('icy') ||
    c.includes('freezing') ||
    c.includes('sleet');
  const isRain =
    (c.includes('rain') || c.includes('shower') || c.includes('drizzle')) &&
    !isSnow &&
    !isIce;
  const isMixed = isRain && isSnow;

  // If we have precipitation probability, adjust icon based on it
  if (pop !== null && pop !== undefined) {
    const popVal = parseInt(pop);

    if (popVal >= 45) {
      // High chance: show precipitation type
      if (isStorm) {
        return 'bolt';
      }
      if (isMixed) {
        return 'cloud-meatball';
      }
      if (isSnow) {
        return 'snowflake';
      }
      if (isIce) {
        return 'cloud-meatball';
      }
      if (isRain) {
        return 'tint';
      }
    } else if (popVal >= 15) {
      // Medium chance: show cloud + precipitation
      if (isStorm) {
        return 'cloud-bolt';
      }
      if (isMixed) {
        return 'cloud-meatball';
      }
      if (isSnow) {
        return 'cloud-snow';
      }
      if (isIce) {
        return 'cloud-meatball';
      }
      if (isRain) {
        return 'cloud-rain';
      }
    } else {
      // Low chance: show just sky type
      if (c.includes('partly')) {
        return isDaytime ? 'cloud-sun' : 'cloud-moon';
      }
      if (c.includes('sunny') || c.includes('clear')) {
        return isDaytime ? 'sun' : 'moon';
      }
      if (c.includes('cloud') || c.includes('overcast')) {
        return 'cloud';
      }
    }
  }

  // Default behavior (no PoP or couldn't parse it)
  if (isStorm) {
    return 'bolt';
  }
  if (isIce) {
    return 'cloud-meatball';
  }
  if (isSnow) {
    return 'snowflake';
  }
  if (c.includes('fog') || c.includes('mist') || c.includes('haze')) {
    return 'smog';
  }
  if (isRain) {
    return 'cloud-rain';
  }
  if (c.includes('wind') && !c.includes('cloudy')) {
    return 'wind';
  }
  if (c.includes('partly')) {
    return isDaytime ? 'cloud-sun' : 'cloud-moon';
  }
  if (c.includes('sunny') || c.includes('clear') || c.includes('fair')) {
    return isDaytime ? 'sun' : 'moon';
  }
  if (c.includes('cloud') || c.includes('overcast')) {
    return 'cloud';
  }
  return isDaytime ? 'cloud-sun' : 'cloud-moon';
}

// CSRF Token handling
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop().split(';').shift();
  }
  return '';
}

function getCsrfToken() {
  return (
    document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
    document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
    document.querySelector('meta[name=csrf-token]')?.getAttribute('content') ||
    getCookie('csrftoken') ||
    ''
  );
}

// API Request helper
async function apiRequest(url, options = {}) {
  const defaultOptions = {
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
      ...options.headers,
    },
  };

  const response = await fetch(url, { ...defaultOptions, ...options });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  return response.json();
}

// Weather card functionality
function initializeWeatherCards() {
  // Add click handlers for forecast cards (show hourly modal)
  document.querySelectorAll('.forecast-card[data-forecast-date]').forEach((card) => {
    card.style.cursor = 'pointer';
    card.addEventListener('click', function (e) {
      if (e.target.closest('.dropdown') || e.target.closest('button')) {
        return;
      }
      const forecastDate = this.dataset.forecastDate;
      showHourlyForecastModal(forecastDate);
    });
  });
}

// Show hourly forecast modal for a given date
async function showHourlyForecastModal(forecastDate) {
  const modalBody = document.getElementById('hourlyForecastModalBody');
  const modalTitle = document.getElementById('hourlyForecastModalLabel');

  // Format date for display
  const dateObj = new Date(forecastDate + 'T12:00:00');
  const dateStr = dateObj.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
  modalTitle.textContent = `Hourly Forecast - ${dateStr}`;

  modalBody.innerHTML =
    '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-3 text-muted">Loading hourly forecast...</p></div>';
  const modal = new bootstrap.Modal(document.getElementById('hourlyForecastModal'));
  modal.show();

  try {
    // Get current location coords from browser location
    if (!browserLocationCoords) {
      modalBody.innerHTML =
        '<p class="text-center text-warning">Location not available. Please enable location access.</p>';
      return;
    }

    // Fetch hourly forecast for the selected date
    const resp = await apiRequest(
      `/api/hourly_forecast/?lat=${browserLocationCoords.lat}&lon=${
        browserLocationCoords.lon
      }&date=${encodeURIComponent(forecastDate)}&hours=24`
    );

    if (resp && resp.hours && resp.hours.length > 0) {
      let html = '<div class="row g-2">';
      resp.hours.forEach((hour) => {
        const tempClass = `temp-bg-${hour.temp}`;
        html += `
                    <div class="col-6 col-md-4 col-lg-3">
                        <div class="card h-100 border-0">
                            <div class="card-body p-2 text-center ${tempClass}">
                                <div class="fw-bold mb-1">${hour.time}</div>
                                <i class="fas fa-${
                                  hour.icon
                                } mb-2" style="font-size: 1.5rem;"></i>
                                <div class="h5 mb-1">${hour.temp}&deg;F</div>
                                <small class="d-block mb-1" style="opacity: 0.9;">${
                                  hour.condition
                                }</small>
                                ${
                                  hour.wind
                                    ? `<small class="d-block" style="opacity: 0.85;"><i class="fas fa-wind"></i> ${
                                        hour.wind
                                      }${
                                        hour.windGust
                                          ? ` (gust ${hour.windGust} mph)`
                                          : ''
                                      }</small>`
                                    : ''
                                }
                                ${
                                  hour.pop !== null && hour.pop !== undefined
                                    ? `<small class="d-block" style="opacity: 0.85;"><i class="fas fa-cloud-rain"></i> ${hour.pop}%</small>`
                                    : ''
                                }
                            </div>
                        </div>
                    </div>
                `;
      });
      html += '</div>';
      modalBody.innerHTML = html;
    } else {
      modalBody.innerHTML =
        '<p class="text-center text-muted">No hourly data available for this date.</p>';
    }
  } catch (err) {
    console.error('Error loading hourly forecast:', err);
    modalBody.innerHTML =
      '<p class="text-danger text-center">Error loading hourly forecast. Please try again.</p>';
  }
}

// Load next 6 hours for dashboard
window.loadNext6Hours = async function loadNext6Hours(lat, lon) {
  const next6Body = document.getElementById('next6HoursBody');
  if (!next6Body) {
    console.warn('next6HoursBody element not found');
    return;
  }

  next6Body.innerHTML =
    '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-3 text-muted">Loading next 6 hours...</p></div>';

  try {
    // Fetch next 6 hours
    const resp = await apiRequest(
      `/api/hourly_forecast/?lat=${lat}&lon=${lon}&hours=6`
    );

    if (resp && resp.hours && resp.hours.length > 0) {
      let html = '<div class="row g-2">';
      resp.hours.forEach((hour) => {
        const tempClass = `temp-bg-${hour.temp}`;
        html += `
                    <div class="col-6 col-md-4">
                        <div class="card h-100 border-0">
                            <div class="card-body p-3 text-center ${tempClass}">
                                <div class="fw-bold mb-2">${hour.time}</div>
                                <i class="fas fa-${
                                  hour.icon
                                } mb-2" style="font-size: 2rem;"></i>
                                <div class="h4 mb-2">${hour.temp}&deg;F</div>
                                <small class="d-block mb-1" style="opacity: 0.9;">${
                                  hour.condition
                                }</small>
                                ${
                                  hour.wind
                                    ? `<small class="mt-1 d-block" style="opacity: 0.85;"><i class="fas fa-wind"></i> ${
                                        hour.wind
                                      } ${hour.windDir}${
                                        hour.windGust
                                          ? ` (gust ${hour.windGust} mph)`
                                          : ''
                                      }</small>`
                                    : ''
                                }
                                ${
                                  hour.pop !== null && hour.pop !== undefined
                                    ? `<small class="d-block" style="opacity: 0.85;"><i class="fas fa-cloud-rain"></i> ${hour.pop}%</small>`
                                    : ''
                                }
                            </div>
                        </div>
                    </div>
                `;
      });
      html += '</div>';
      next6Body.innerHTML = html;
    } else {
      next6Body.innerHTML =
        '<p class="text-center text-muted">No hourly data available.</p>';
    }
  } catch (err) {
    console.error('Error loading next 6 hours:', err);
    next6Body.innerHTML =
      '<p class="text-danger text-center">Unable to load hourly forecast.</p>';
  }
};

// UI Helper functions
function showLoading(message = 'Loading...') {
  const loadingEl = document.getElementById('loading-indicator');
  if (loadingEl) {
    loadingEl.textContent = message;
    loadingEl.style.display = 'block';
  }
}

function hideLoading() {
  const loadingEl = document.getElementById('loading-indicator');
  if (loadingEl) {
    loadingEl.style.display = 'none';
  }
}

function showNotification(message, type = 'info') {
  // Create notification element
  const notification = document.createElement('div');
  notification.className = `alert alert-${
    type === 'error' ? 'danger' : type
  } alert-dismissible fade show notification-toast`;
  notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        min-width: 300px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    `;

  notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

  document.body.appendChild(notification);

  // Auto remove after 5 seconds
  setTimeout(() => {
    if (notification.parentNode) {
      notification.remove();
    }
  }, 5000);
}

// Weather data formatting
function formatTemperature(temp, unit = 'F') {
  return `${Math.round(temp)}°${unit}`;
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function formatTime(timeString) {
  const time = new Date(timeString);
  return time.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

// Calculate apparent temperature (feels like) in JS
function calculateApparentTemperature(tempF, humidityPct, windSpeedMph) {
  if (tempF === null || tempF === undefined) {
    return null;
  }
  // Heat Index for hot conditions (≥80°F)
  if (tempF >= 80 && humidityPct !== null && humidityPct !== undefined) {
    const rh = humidityPct;
    // Rothfusz regression heat index formula
    let hi = -42.379 + 2.04901523 * tempF + 10.14333127 * rh;
    hi += -0.22475541 * tempF * rh + -0.00683783 * tempF * tempF;
    hi += -0.05481717 * rh * rh + 0.00122874 * tempF * tempF * rh;
    hi += 0.00085282 * tempF * rh * rh + -0.00000199 * tempF * tempF * rh * rh;
    return Math.round(hi);
  }
  // Wind Chill for cold conditions (≤50°F with wind ≥3mph)
  if (
    tempF <= 50 &&
    windSpeedMph !== null &&
    windSpeedMph !== undefined &&
    windSpeedMph >= 3
  ) {
    let wc = 35.74 + 0.6215 * tempF - 35.75 * Math.pow(windSpeedMph, 0.16);
    wc += 0.4275 * tempF * Math.pow(windSpeedMph, 0.16);
    return Math.round(wc);
  }
  // Moderate conditions - apparent temperature equals actual temperature
  return Math.round(tempF);
}

// Export functions for global use
window.weatherApp = {
  getCsrfToken,
  apiRequest,
  showNotification,
  formatTemperature,
  formatDate,
  formatTime,
  getWeatherIcon,
};
