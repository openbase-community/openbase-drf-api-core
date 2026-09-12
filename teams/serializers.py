from rest_framework import serializers

from teams.models import Team, TeamMember


class TeamMemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    joined_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TeamMember
        fields = ["email", "first_name", "joined_at"]


class TeamSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="slug", read_only=True)
    member_count = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    members = TeamMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Team
        fields = ["id", "name", "member_count", "is_owner", "members"]
        read_only_fields = ["id", "member_count", "is_owner", "members"]

    def get_member_count(self, team):
        return team.members.count()

    def get_is_owner(self, team):
        request = self.context.get("request")
        return bool(request and team.owner_id == request.user.id)
