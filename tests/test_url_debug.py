"""Debug script to print all registered URLs."""

import pytest
from django.urls import get_resolver


@pytest.mark.django_db
def test_print_urls():
    """Print all URL patterns to debug routing issues."""
    resolver = get_resolver()
    
    def print_url_patterns(patterns, prefix=''):
        for pattern in patterns:
            if hasattr(pattern, 'url_patterns'):
                print_url_patterns(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                print(f"{prefix}{pattern.pattern} -> {pattern.name}")
    
    print("\n=== All Registered URLs ===")
    print_url_patterns(resolver.url_patterns)
    
    assert True
