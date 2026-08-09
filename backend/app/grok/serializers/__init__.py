from rest_framework import serializers

from app.grok.models import GrokAccount, GrokPool, parse_sso_input
from app.utils import clean_int_list
import time

class ShowGrokPoolSerializer(serializers.ModelSerializer):
    grok_account_name_list = serializers.SerializerMethodField()

    def get_grok_account_name_list(self, obj):
        grok_account_list = clean_int_list(obj.grok_account_list)
        resutls = GrokAccount.objects.filter(id__in=grok_account_list).values_list("grok_username")
        return [i[0] for i in resutls]

    class Meta:
        model = GrokPool
        fields = "__all__"

class AddGrokPoolModelSerializer(serializers.ModelSerializer):

    def validate_empty_values(self, data):
        if not self.instance:
            data["created_time"] = int(time.time())

        data["updated_time"] = int(time.time())
        return (False, data)

    class Meta:
        model = GrokPool
        fields = "__all__"

class DeleteGrokPoolSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField())


class ShowGrokTokenSerializer(serializers.ModelSerializer):
    sso_exp = serializers.SerializerMethodField()
    use_count = serializers.SerializerMethodField()
    supported_login_modes = serializers.SerializerMethodField()
    has_sso = serializers.SerializerMethodField()

    def __init__(self, *args, use_count_dict=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_count_dict = use_count_dict or {}

    def get_use_count(self, obj):
        return self.use_count_dict.get(obj.grok_username, 0)

    def get_sso_exp(self, obj):
        return obj.sso_expires_at

    def get_supported_login_modes(self, obj):
        modes = []
        if obj.session_token_valid:
            modes.append("web")
        return modes

    def get_has_sso(self, obj):
        return obj.has_sso

    class Meta:
        model = GrokAccount
        fields = (
            "id",
            "grok_username",
            "auth_status",
            "plan_type",
            "session_token_valid",
            "proxy_node_id",
            "last_check_at",
            "last_error",
            "remark",
            "created_time",
            "updated_time",
            "sso_exp",
            "use_count",
            "supported_login_modes",
            "has_sso",
        )


class AddGrokTokenSerializer(serializers.Serializer):
    sso = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        try:
            attrs["sso"], attrs["sso_expires"] = parse_sso_input(attrs.get("sso"))
        except ValueError as error:
            raise serializers.ValidationError({"sso": str(error)}) from error
        return attrs

class CheckGrokTokenExpirySerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=False)

class DeleteGrokAccountSerializer(serializers.Serializer):
    grok_username = serializers.CharField()

class UpdateGrokInfoSerializer(serializers.Serializer):
    grok_username = serializers.CharField()
    remark = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    proxy_node_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    sso = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        if attrs.get("sso"):
            try:
                attrs["sso"], attrs["sso_expires"] = parse_sso_input(attrs["sso"])
            except ValueError as error:
                raise serializers.ValidationError({"sso": str(error)}) from error
        return attrs


class GrokLoginSerializer(serializers.Serializer):
    grok_id = serializers.IntegerField(required=False, allow_null=True)
    login_mode = serializers.ChoiceField(choices=["web"], default="web", required=False)
