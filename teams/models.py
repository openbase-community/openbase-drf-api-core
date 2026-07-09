import re

from django.contrib.auth import get_user_model
from django.db import models
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


class Team(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    owner = models.ForeignKey(
        get_user_model(),
        related_name="owned_teams",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if not self.slug:
            self.slug = name_to_slug(self.name)
            if Team.objects.filter(slug=self.slug).exists():
                msg = f"Team with slug {self.slug} already exists."
                raise ValidationError(msg)
        super().save(force_insert, force_update, using, update_fields)

    @classmethod
    def get_access_user_username(cls, slug):
        return f"team_{slug.replace('-', '_')}"

    @property
    def users(self):
        return get_user_model().objects.filter(
            team_memberships__team=self, is_active=True
        )

    @property
    def billable_users(self):
        return self.users

    def num_billable_users(self):
        """
        Excludes the API access user and any non-active users.
        """
        return self.billable_users.count()

    def get_email(self):
        return self.owner.email if self.owner else None


class TeamMember(models.Model):
    """🤝 A user's membership in a team (the owner is a member too)."""

    team = models.ForeignKey(
        Team,
        related_name="members",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        get_user_model(),
        related_name="team_memberships",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="unique_team_member"),
        ]

    def __str__(self):
        return f"{self.user} in {self.team}"


def name_to_slug(name):
    return re.sub(r"[^a-zA-Z0-9\-]", "", name.lower().replace(" ", "-"))


def get_user_or_team_ownership_mixin(
    related_name, on_delete=models.SET_NULL, relation_type=models.ForeignKey
):
    class UserOrTeamOwnershipMixin(models.Model):
        class Meta:
            abstract = True

        user_owner = relation_type(
            get_user_model(),
            related_name=related_name,
            on_delete=on_delete,
            null=True,
            blank=True,
        )
        team_owner = relation_type(
            "teams.Team",
            related_name=related_name,
            on_delete=on_delete,
            null=True,
            blank=True,
        )

        @property
        def owner(self):
            return self.user_owner or self.team_owner

        def validate_owner(self):
            if self.user_owner and self.team_owner:
                msg = "Cannot have both user_owner and team_owner"
                raise serializers.ValidationError(msg)

    return UserOrTeamOwnershipMixin
