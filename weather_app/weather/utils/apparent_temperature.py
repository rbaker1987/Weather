"""Apparent temperature (feels like) calculation utilities."""

import math
from typing import Optional


def calculate_apparent_temperature(
    temp_f: float,
    humidity_pct: Optional[float] = None,
    wind_speed_mph: Optional[float] = None,
    dew_point_c: Optional[float] = None,
    dew_point_f: Optional[float] = None,
) -> int:
    """Calculate apparent temperature (feels like) from weather conditions.
    
    Implements NWS heat index and wind chill formulas to determine how
    temperature actually feels based on humidity and wind.
    
    Args:
        temp_f: Temperature in Fahrenheit (required)
        humidity_pct: Relative humidity percentage (0-100), optional
        wind_speed_mph: Wind speed in mph, optional
        dew_point_c: Dew point in Celsius, optional
        dew_point_f: Dew point in Fahrenheit, optional
        
    Returns:
        Apparent temperature in Fahrenheit (rounded to nearest degree)
        
    Notes:
        - Heat index used for temps ≥80°F with humidity
        - Wind chill used for temps ≤50°F with wind ≥3mph
        - Otherwise returns actual temperature
        - If humidity not provided but dewpoint is, calculates RH from dewpoint
        - Falls back to 50% RH assumption if neither humidity nor dewpoint available
    """
    if temp_f is None:
        return None
        
    # Heat Index for hot conditions (≥80°F)
    if temp_f >= 80:
        rh = humidity_pct if humidity_pct is not None else None
        
        # If no direct humidity but we have dewpoint, calculate RH
        if rh is None and (dew_point_c is not None or dew_point_f is not None):
            # Convert dewpoint to Fahrenheit if given in Celsius
            if dew_point_f is not None:
                dew_f = dew_point_f
            else:
                dew_f = (dew_point_c * 9/5) + 32
            
            # Calculate RH using Magnus-Tetens formula
            temp_c = (temp_f - 32) * 5/9
            dew_c = (dew_f - 32) * 5/9
            
            # Magnus formula constants
            a = 17.625
            b = 243.04
            
            # Calculate saturation vapor pressure and actual vapor pressure
            alpha_t = (a * temp_c) / (b + temp_c)
            alpha_d = (a * dew_c) / (b + dew_c)
            
            rh = 100 * math.exp(alpha_d - alpha_t)
            rh = max(0, min(100, rh))  # Clamp to 0-100%
        
        # Default to 50% RH if we still don't have humidity
        if rh is None:
            rh = 50
            
        # Rothfusz regression heat index formula
        hi = -42.379 + (2.04901523 * temp_f) + (10.14333127 * rh)
        hi += (-0.22475541 * temp_f * rh) + (-0.00683783 * temp_f * temp_f)
        hi += (-0.05481717 * rh * rh) + (0.00122874 * temp_f * temp_f * rh)
        hi += (0.00085282 * temp_f * rh * rh) + (-0.00000199 * temp_f * temp_f * rh * rh)
        
        return int(round(hi))
        
    # Wind Chill for cold conditions (≤50°F with wind ≥3mph)
    elif temp_f <= 50 and wind_speed_mph and wind_speed_mph >= 3:
        wc = 35.74 + 0.6215 * temp_f - 35.75 * (wind_speed_mph ** 0.16)
        wc += 0.4275 * temp_f * (wind_speed_mph ** 0.16)
        
        return int(round(wc))
        
    # Moderate conditions - apparent temperature equals actual temperature
    return int(round(temp_f))
