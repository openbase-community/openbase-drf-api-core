from django.contrib.auth import get_user_model
from django.db import models, transaction
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from teams.models import Team, TeamMember
from teams.serializers import TeamSerializer


class TeamViewSet(ModelViewSet):
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "slug"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        return (
            Team.objects.filter(models.Q(owner=user) | models.Q(members__user=user))
            .distinct()
            .prefetch_related("members__user")
        )

    def perform_create(self, serializer):
        with transaction.atomic():
            team = serializer.save(owner=self.request.user)
            TeamMember.objects.create(team=team, user=self.request.user)

    @action(detail=True, methods=["post"])
    def invite(self, request, slug=None):
        team = self.get_object()
        if team.owner_id != request.user.id:
            msg = "Only the team owner can invite members."
            raise ValidationError(msg)
        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError({"email": "An email address is required."})
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user is None:
            msg = "No account with that email yet — ask them to sign up, then invite again."
            raise ValidationError({"email": msg})
        if TeamMember.objects.filter(team=team, user=user).exists():
            raise ValidationError({"email": "That person is already a member."})
        TeamMember.objects.create(team=team, user=user)
        return Response({"message": "Teammate added."})

    @action(detail=True, methods=["post"])
    def leave(self, request, slug=None):
        team = self.get_object()
        if team.owner_id == request.user.id:
            msg = "The owner cannot leave the team."
            raise ValidationError(msg)
        TeamMember.objects.filter(team=team, user=request.user).delete()
        return Response({"message": "You left the team."})
