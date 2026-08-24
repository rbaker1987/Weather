"""Tests for authentication and profile forms."""

import pytest
from django.contrib.auth.models import User

from weather.forms import ProfileEditForm, UniqueUsernameCreationForm


@pytest.mark.django_db
class TestUniqueUsernameCreationForm:
    def valid_data(self, **overrides):
        data = {
            "username": "  NewUser  ",
            "first_name": "New",
            "last_name": "User",
            "email": "new@example.com",
            "password1": "A-secure-password-123!",
            "password2": "A-secure-password-123!",
        }
        data.update(overrides)
        return data

    def test_normalizes_username_and_saves_profile_fields(self):
        form = UniqueUsernameCreationForm(data=self.valid_data())

        assert form.is_valid()
        user = form.save()

        assert user.username == "newuser"
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.email == "new@example.com"
        assert user.check_password("A-secure-password-123!")

    def test_rejects_case_insensitive_duplicate_username(self):
        User.objects.create_user(username="existing")
        form = UniqueUsernameCreationForm(data=self.valid_data(username="EXISTING"))

        assert not form.is_valid()
        assert "already taken" in str(form.errors["username"])

    def test_rejects_mismatched_passwords(self):
        form = UniqueUsernameCreationForm(
            data=self.valid_data(password2="A-different-password-123!")
        )

        assert not form.is_valid()
        assert form.errors["password2"]

    def test_save_commit_false_returns_unsaved_user(self):
        form = UniqueUsernameCreationForm(data=self.valid_data())

        assert form.is_valid()
        user = form.save(commit=False)

        assert user.pk is None
        assert user.username == "newuser"


@pytest.mark.django_db
class TestProfileEditForm:
    def test_updates_profile_and_password(self):
        user = User.objects.create_user(
            username="profile", password="old-password", email="old@example.com"
        )
        form = ProfileEditForm(
            data={
                "first_name": "Updated",
                "last_name": "Person",
                "email": "updated@example.com",
                "password": "new-password-123!",
                "password_confirm": "new-password-123!",
            },
            instance=user,
        )

        assert form.is_valid()
        saved = form.save()

        assert saved.first_name == "Updated"
        assert saved.email == "updated@example.com"
        assert saved.check_password("new-password-123!")

    def test_rejects_mismatched_new_passwords(self):
        user = User.objects.create_user(username="profile")
        form = ProfileEditForm(
            data={
                "first_name": "",
                "last_name": "",
                "email": "profile@example.com",
                "password": "new-password-123!",
                "password_confirm": "different-password-123!",
            },
            instance=user,
        )

        assert not form.is_valid()
        assert "Passwords do not match" in str(form.errors["password_confirm"])

    def test_allows_blank_password_and_commit_false(self):
        user = User.objects.create_user(username="profile", password="old-password")
        form = ProfileEditForm(
            data={
                "first_name": "Name",
                "last_name": "User",
                "email": "profile@example.com",
                "password": "",
                "password_confirm": "",
            },
            instance=user,
        )

        assert form.is_valid()
        saved = form.save(commit=False)

        assert saved.pk == user.pk
        assert saved.check_password("old-password")
