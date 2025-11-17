"""Django admin configuration for weather app."""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import Location, HourlyForecast, DailyForecast, WeatherAlert, ForecastRequest


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """Admin interface for locations."""
    
    list_display = ['name', 'zip_code', 'coordinates_display', 'forecast_count', 'last_update', 'created_by', 'is_active']
    list_filter = ['is_active', 'created_at', 'nws_office', 'created_by']
    search_fields = ['name', 'zip_code', 'nws_office']
    readonly_fields = ['id', 'created_at', 'updated_at', 'nws_office', 'grid_x', 'grid_y']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'is_active', 'created_by')
        }),
        ('Geographic Data', {
            'fields': ('point', 'zip_code')
        }),
        ('NWS Data', {
            'fields': ('nws_office', 'grid_x', 'grid_y'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at', 'last_forecast_update'),
            'classes': ('collapse',)
        })
    )
    
    def coordinates_display(self, obj):
        """Display coordinates in a readable format."""
        if obj.latitude and obj.longitude:
            return f"{obj.latitude:.4f}, {obj.longitude:.4f}"
        return "No coordinates"
    coordinates_display.short_description = "Coordinates"
    
    def forecast_count(self, obj):
        """Display count of forecasts."""
        count = obj.forecasts.count()
        if count > 0:
            url = reverse('admin:weather_dailyforecast_changelist')
            return format_html(
                '<a href="{}?location__id__exact={}">{} forecasts</a>',
                url, obj.id, count
            )
        return "0 forecasts"
    forecast_count.short_description = "Forecasts"
    
    def last_update(self, obj):
        """Display last forecast update."""
        if obj.last_forecast_update:
            return obj.last_forecast_update.strftime("%Y-%m-%d %H:%M")
        return "Never"
    last_update.short_description = "Last Update"

    actions = ['update_forecasts', 'deactivate_locations']
    
    def update_forecasts(self, request, queryset):
        """Trigger forecast update for selected locations."""
        count = 0
        for location in queryset:
            # This would trigger your weather service
            location.last_forecast_update = timezone.now()
            location.save()
            count += 1
        
        self.message_user(
            request,
            f"Triggered forecast update for {count} locations."
        )
    update_forecasts.short_description = "Update forecasts"
    
    def deactivate_locations(self, request, queryset):
        """Deactivate selected locations."""
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"Deactivated {count} locations."
        )
    deactivate_locations.short_description = "Deactivate selected locations"


@admin.register(DailyForecast)
class DailyForecastAdmin(admin.ModelAdmin):
    """Admin interface for daily forecasts."""
    
    list_display = ['location_name', 'forecast_date', 'temperature_display', 'short_forecast', 'wind_info', 'created_at']
    list_filter = ['forecast_date', 'temperature_unit', 'wind_direction', 'created_at']
    search_fields = ['location__name', 'short_forecast', 'detailed_forecast']
    readonly_fields = ['id', 'created_at', 'updated_at', 'apparent_temperature']
    date_hierarchy = 'forecast_date'
    ordering = ['-forecast_date', 'location__name']
    
    fieldsets = (
        ('Location & Time', {
            'fields': ('location', 'forecast_date', 'period_start', 'period_end')
        }),
        ('Temperature', {
            'fields': ('temperature', 'temperature_unit', 'apparent_temperature', 'high_temperature', 'low_temperature')
        }),
        ('Weather Conditions', {
            'fields': ('short_forecast', 'detailed_forecast', 'precipitation_probability')
        }),
        ('Wind', {
            'fields': ('wind_speed', 'wind_direction', 'wind_gust')
        }),
        ('Data Source', {
            'fields': ('nws_data_url', 'raw_data'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def location_name(self, obj):
        """Display location name with link."""
        url = reverse('admin:weather_location_change', args=[obj.location.id])
        return format_html('<a href="{}">{}</a>', url, obj.location.name)
    location_name.short_description = "Location"
    
    def temperature_display(self, obj):
        """Display temperature range."""
        if obj.high_temperature and obj.low_temperature:
            return f"{obj.low_temperature}°{obj.temperature_unit} - {obj.high_temperature}°{obj.temperature_unit}"
        return f"{obj.temperature}°{obj.temperature_unit}"
    temperature_display.short_description = "Temperature"
    
    def wind_info(self, obj):
        """Display wind information."""
        wind = f"{obj.wind_speed} mph"
        if obj.wind_direction:
            wind += f" {obj.wind_direction}"
        if obj.wind_gust:
            wind += f" (gusts {obj.wind_gust})"
        return wind
    wind_info.short_description = "Wind"


@admin.register(HourlyForecast)
class HourlyForecastAdmin(admin.ModelAdmin):
    """Admin interface for hourly forecasts."""
    
    list_display = ['location_name', 'period_start', 'temperature_display', 'short_forecast', 'wind_speed', 'humidity']
    list_filter = ['forecast_date', 'temperature_unit', 'wind_direction', 'created_at']
    search_fields = ['location__name', 'short_forecast']
    readonly_fields = ['id', 'created_at', 'updated_at', 'apparent_temperature']
    date_hierarchy = 'period_start'
    ordering = ['-period_start', 'location__name']
    
    def location_name(self, obj):
        """Display location name."""
        return obj.location.name
    location_name.short_description = "Location"
    
    def temperature_display(self, obj):
        """Display temperature with feels-like."""
        temp = f"{obj.temperature}°{obj.temperature_unit}"
        if obj.apparent_temperature and obj.apparent_temperature != obj.temperature:
            temp += f" (feels {obj.apparent_temperature}°)"
        return temp
    temperature_display.short_description = "Temperature"


@admin.register(WeatherAlert)
class WeatherAlertAdmin(admin.ModelAdmin):
    """Admin interface for weather alerts."""
    
    list_display = ['event', 'location_name', 'severity', 'urgency', 'onset', 'expires', 'is_active', 'is_expired']
    list_filter = ['severity', 'urgency', 'is_active', 'event', 'onset']
    search_fields = ['event', 'headline', 'location__name', 'nws_alert_id']
    readonly_fields = ['id', 'created_at', 'updated_at', 'is_expired']
    date_hierarchy = 'onset'
    ordering = ['-onset']
    
    fieldsets = (
        ('Alert Information', {
            'fields': ('nws_alert_id', 'event', 'headline', 'description')
        }),
        ('Location & Timing', {
            'fields': ('location', 'onset', 'expires')
        }),
        ('Classification', {
            'fields': ('severity', 'urgency', 'is_active')
        }),
        ('Raw Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at', 'is_expired'),
            'classes': ('collapse',)
        })
    )
    
    def location_name(self, obj):
        """Display location name."""
        return obj.location.name
    location_name.short_description = "Location"
    
    def is_expired(self, obj):
        """Check if alert is expired."""
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = "Expired"
    
    actions = ['deactivate_alerts']
    
    def deactivate_alerts(self, request, queryset):
        """Deactivate selected alerts."""
        count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {count} alerts.")
    deactivate_alerts.short_description = "Deactivate selected alerts"


@admin.register(ForecastRequest)
class ForecastRequestAdmin(admin.ModelAdmin):
    """Admin interface for forecast requests."""
    
    list_display = ['user_display', 'request_type', 'status', 'location_count', 'response_time_display', 'created_at']
    list_filter = ['request_type', 'status', 'cache_hit', 'created_at']
    search_fields = ['user__username', 'error_message']
    readonly_fields = ['id', 'created_at', 'response_time_display', 'location_names']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('Request Information', {
            'fields': ('user', 'request_type', 'status', 'locations_requested')
        }),
        ('Performance', {
            'fields': ('response_time_ms', 'response_time_display', 'cache_hit')
        }),
        ('Error Details', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'location_names'),
            'classes': ('collapse',)
        })
    )
    
    def user_display(self, obj):
        """Display user name or Anonymous."""
        return obj.user.username if obj.user else "Anonymous"
    user_display.short_description = "User"
    
    def location_count(self, obj):
        """Display number of locations requested."""
        return obj.locations_requested.count()
    location_count.short_description = "Locations"
    
    def response_time_display(self, obj):
        """Display response time in readable format."""
        if obj.response_time_ms:
            if obj.response_time_ms < 1000:
                return f"{obj.response_time_ms}ms"
            else:
                return f"{obj.response_time_ms / 1000:.2f}s"
        return "N/A"
    response_time_display.short_description = "Response Time"
    
    def location_names(self, obj):
        """Display requested location names."""
        names = list(obj.locations_requested.values_list('name', flat=True))
        return ', '.join(names) if names else "None"
    location_names.short_description = "Requested Locations"


# Customize admin site
admin.site.site_header = "Weather Forecast Administration"
admin.site.site_title = "Weather Admin"
admin.site.index_title = "Weather Application Management"