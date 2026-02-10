"""Forms for authentication flows."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class UniqueUsernameCreationForm(UserCreationForm):
    """User creation form with case-insensitive username validation."""

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            return username
        normalized = username.lower()
        user_model = get_user_model()
        if user_model.objects.filter(username__iexact=normalized).exists():
            raise forms.ValidationError(
                "That username is already taken. Please choose another."
            )
        return normalized
