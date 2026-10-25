import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.urls import reverse

from teams.models import Team, TeamMember


def _verified_user(email):
    user = get_user_model().objects.create_user(
        email=email,
        password="x-12345678",  # noqa: S106
    )
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


@pytest.fixture
def owner(db):
    return _verified_user("owner@example.com")


@pytest.fixture
def teammate(db):
    return _verified_user("mate@example.com")


@pytest.fixture
def team(owner):
    team = Team.objects.create(name="Acme", owner=owner)
    TeamMember.objects.create(team=team, user=owner)
    return team


def _login(client, user):
    client.force_login(user)


def test_create_team_adds_owner_membership(client, owner):
    _login(client, owner)
    response = client.post(reverse("team-list"), {"name": "New Team"}, secure=True)
    assert response.status_code == 201
    team = Team.objects.get(slug=response.json()["id"])
    assert team.owner == owner
    assert TeamMember.objects.filter(team=team, user=owner).exists()


def test_invite_adds_existing_user(client, owner, teammate, team):
    _login(client, owner)
    response = client.post(
        reverse("team-invite", args=[team.slug]),
        {"email": "MATE@example.com"},
        secure=True,
    )
    assert response.status_code == 200
    assert TeamMember.objects.filter(team=team, user=teammate).exists()
    assert list(team.users) == sorted([owner, teammate], key=lambda u: u.pk) or set(
        team.users
    ) == {owner, teammate}


def test_invite_unknown_email_rejected(client, owner, team):
    _login(client, owner)
    response = client.post(
        reverse("team-invite", args=[team.slug]),
        {"email": "ghost@example.com"},
        secure=True,
    )
    assert response.status_code == 400


def test_invite_requires_owner(client, owner, teammate, team):
    TeamMember.objects.create(team=team, user=teammate)
    _login(client, teammate)
    response = client.post(
        reverse("team-invite", args=[team.slug]),
        {"email": "owner@example.com"},
        secure=True,
    )
    assert response.status_code == 400


def test_leave_and_owner_cannot_leave(client, owner, teammate, team):
    TeamMember.objects.create(team=team, user=teammate)
    _login(client, teammate)
    assert (
        client.post(reverse("team-leave", args=[team.slug]), secure=True).status_code
        == 200
    )
    assert not TeamMember.objects.filter(team=team, user=teammate).exists()

    _login(client, owner)
    assert (
        client.post(reverse("team-leave", args=[team.slug]), secure=True).status_code
        == 400
    )


def test_non_member_gets_404(client, teammate, team):
    _login(client, teammate)
    response = client.get(reverse("team-detail", args=[team.slug]), secure=True)
    assert response.status_code == 404
