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

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        return cleaned_data


class ProfileEditForm(forms.ModelForm):
    """Form for editing user profile information."""

    password = forms.CharField(
        label="New Password (leave blank to keep current)",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password_confirm = forms.CharField(
        label="Confirm New Password",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password != password_confirm:
            self.add_error("password_confirm", "Passwords do not match.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
