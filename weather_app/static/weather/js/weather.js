// Weather App JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Initialize modals
    var modalList = [].slice.call(document.querySelectorAll('.modal'));
    modalList.forEach(function(modal) {
        new bootstrap.Modal(modal);
    });

    // Auto-refresh dashboard data
    if (document.querySelector('.dashboard-content')) {
        setInterval(refreshDashboardStats, 300000); // 5 minutes
    }

    // Initialize search functionality
    initializeSearch();
    
    // Initialize weather cards
    initializeWeatherCards();
});

// CSRF Token handling
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
           document.querySelector('meta[name=csrf-token]')?.getAttribute('content') ||
           getCookie('csrftoken') || '';
}

// API Request helper
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            ...options.headers
        }
    };

    const response = await fetch(url, { ...defaultOptions, ...options });
    
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    return response.json();
}

// Dashboard functionality
function refreshDashboardStats() {
    fetch('/api/stats/')
        .then(response => response.json())
        .then(data => {
            updateDashboardStats(data);
        })
        .catch(error => {
            console.error('Error refreshing dashboard stats:', error);
        });
}

function updateDashboardStats(stats) {
    // Update stat cards if they exist
    const locationCount = document.getElementById('location-count');
    const forecastCount = document.getElementById('forecast-count');
    const alertCount = document.getElementById('alert-count');

    if (locationCount && stats.total_locations !== undefined) {
        locationCount.textContent = stats.total_locations;
    }
    if (forecastCount && stats.total_forecasts !== undefined) {
        forecastCount.textContent = stats.total_forecasts;
    }
    if (alertCount && stats.active_alerts !== undefined) {
        alertCount.textContent = stats.active_alerts;
    }
}

// Search functionality
function initializeSearch() {
    const searchInput = document.getElementById('search-locations');
    if (searchInput) {
        let searchTimeout;
        
        searchInput.addEventListener('input', function(e) {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                const searchTerm = e.target.value;
                if (searchTerm.length > 2 || searchTerm.length === 0) {
                    performSearch(searchTerm);
                }
            }, 300);
        });
    }
}

function performSearch(searchTerm) {
    const url = new URL(window.location);
    if (searchTerm) {
        url.searchParams.set('search', searchTerm);
    } else {
        url.searchParams.delete('search');
    }
    window.location = url;
}

// Weather card functionality
function initializeWeatherCards() {
    // Add click handlers for weather cards
    document.querySelectorAll('.weather-card[data-location-id]').forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', function(e) {
            if (e.target.closest('.dropdown') || e.target.closest('button')) {
                return; // Don't trigger if clicking dropdown or button
            }
            const locationId = this.dataset.locationId;
            window.location.href = `/weather/locations/${locationId}/`;
        });
    });
}

// Location management functions
async function addLocation(formData) {
    try {
        showLoading('Adding location...');
        
        const data = await apiRequest('/api/locations/', {
            method: 'POST',
            body: JSON.stringify(formData)
        });
        
        hideLoading();
        showNotification('Location added successfully!', 'success');
        
        // Reload page after a short delay
        setTimeout(() => {
            window.location.reload();
        }, 1000);
        
        return data;
    } catch (error) {
        hideLoading();
        showNotification('Error adding location: ' + error.message, 'error');
        throw error;
    }
}

async function updateForecast(locationId) {
    try {
        showLoading('Updating forecast...');
        
        const data = await apiRequest(`/api/locations/${locationId}/update_forecast/`, {
            method: 'POST'
        });
        
        hideLoading();
        showNotification('Forecast update triggered successfully!', 'success');
        
        // Refresh forecast data
        setTimeout(() => {
            window.location.reload();
        }, 2000);
        
        return data;
    } catch (error) {
        hideLoading();
        showNotification('Error updating forecast: ' + error.message, 'error');
        throw error;
    }
}

async function deleteLocation(locationId) {
    if (!confirm('Are you sure you want to remove this location?')) {
        return;
    }
    
    try {
        showLoading('Removing location...');
        
        await fetch(`/api/locations/${locationId}/`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': getCsrfToken()
            }
        });
        
        hideLoading();
        showNotification('Location removed successfully!', 'success');
        
        // Remove the card from DOM or reload page
        setTimeout(() => {
            window.location.reload();
        }, 1000);
        
    } catch (error) {
        hideLoading();
        showNotification('Error removing location: ' + error.message, 'error');
    }
}

async function toggleLocationEnabled(locationId, currentState) {
    try {
        showLoading(currentState ? 'Disabling location...' : 'Enabling location...');
        
        const response = await fetch(`/api/locations/${locationId}/toggle_enabled/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            }
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            hideLoading();
            showNotification(data.message, 'success');
            
            // Reload the page to reflect the updated state
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            throw new Error(data.message || 'Failed to toggle location');
        }
        
    } catch (error) {
        hideLoading();
        showNotification('Error toggling location: ' + error.message, 'error');
    }
}

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
    notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show notification-toast`;
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
        day: 'numeric'
    });
}

function formatTime(timeString) {
    const time = new Date(timeString);
    return time.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });
}

// Weather icon mapping
function getWeatherIcon(condition) {
    const iconMap = {
        't-storm': 'fas fa-bolt',
        'tstorm': 'fas fa-bolt',
        'thunderstorm': 'fas fa-bolt',
        'thunder': 'fas fa-bolt',
        'storm': 'fas fa-bolt',
        'ice': 'fas fa-icicles',
        'icy': 'fas fa-icicles',
        'freezing': 'fas fa-icicles',
        'sleet': 'fas fa-icicles',
        'snow': 'fas fa-snowflake',
        'flurries': 'fas fa-snowflake',
        'blizzard': 'fas fa-snowflake',
        'fog': 'fas fa-smog',
        'mist': 'fas fa-smog',
        'haze': 'fas fa-smog',
        'rain': 'fas fa-cloud-rain',
        'showers': 'fas fa-cloud-rain',
        'drizzle': 'fas fa-cloud-rain',
        'tornado': 'fas fa-tornado',
        'hurricane': 'fas fa-hurricane',
        'wind': 'fas fa-wind',
        'partly cloudy': 'fas fa-cloud-sun',
        'partly': 'fas fa-cloud-sun',
        'clear': 'fas fa-sun',
        'sunny': 'fas fa-sun',
        'cloudy': 'fas fa-cloud',
        'overcast': 'fas fa-cloud'
    };
    
    const key = condition.toLowerCase();
    for (const [keyword, icon] of Object.entries(iconMap)) {
        if (key.includes(keyword)) {
            return icon;
        }
    }
    
    return 'fas fa-cloud'; // default icon
}

// Export functions for global use
window.weatherApp = {
    addLocation,
    updateForecast,
    deleteLocation,
    toggleLocationEnabled,
    getCsrfToken,
    apiRequest,
    showNotification,
    formatTemperature,
    formatDate,
    formatTime,
    getWeatherIcon
};