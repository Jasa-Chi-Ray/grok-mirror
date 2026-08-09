import json
import time

from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.accounts.models import User, VisitLog
from app.grok.models import GrokAccount, GrokPool
from app.fields import decrypt_value, encrypt_value
from app.utils import req_gateway


class UnifiedBackupView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        payload = {
            "version": 1,
            "created_at": int(time.time()),
            "users": [
                {
                    "username": user.username,
                    "password": user.password,
                    "is_active": user.is_active,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "remark": user.remark,
                    "isolated_session": user.isolated_session,
                    "grok_pool_list": user.grok_pool_list,
                    "model_limit": user.model_limit,
                    "expired_date": user.expired_date.isoformat() if user.expired_date else None,
                    "daily_quota": user.daily_quota,
                    "monthly_quota": user.monthly_quota,
                }
                for user in User.objects.all()
            ],
            "grok_accounts": [
                {
                    "id": account.id,
                    **{
                        field: getattr(account, field)
                        for field in (
                        "grok_username", "auth_status", "plan_type", "access_token",
                        "session_token", "extra_cookies", "refresh_token", "refresh_client_id",
                        "access_token_valid", "session_token_valid", "proxy_node_id",
                        "last_check_at", "last_error", "remark", "created_time", "updated_time",
                        )
                    },
                }
                for account in GrokAccount.objects.all()
            ],
            "grok_cars": list(
                GrokPool.objects.values(
                    "id", "pool_name", "remark", "grok_account_list", "created_time", "updated_time"
                )
            ),
            "visit_logs": list(
                VisitLog.objects.values(
                    "id", "username", "grok_username", "log_type",
                    "created_at", "ip", "user_agent",
                )
            ),
            "gateway": req_gateway("get", "/api/backup/export"),
        }
        archive = encrypt_value(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        response = Response({"archive": archive})
        response["Content-Disposition"] = (
            f'attachment; filename="grok-mirror-backup-{payload["created_at"]}.json"'
        )
        return response

    def post(self, request):
        if request.data.get("confirm") != "RESTORE":
            raise ValidationError({"confirm": "恢复操作必须明确提交 RESTORE"})
        archive = str(request.data.get("archive") or "")
        try:
            payload = json.loads(decrypt_value(archive))
        except Exception:
            raise ValidationError({"archive": "备份文件无效或加密密钥不匹配"})
        if payload.get("version") != 1:
            raise ValidationError({"archive": "不支持的备份版本"})

        with transaction.atomic():
            for data in payload.get("grok_accounts", []):
                account_id = data.pop("id")
                username = data.pop("grok_username")
                GrokAccount.objects.update_or_create(
                    id=account_id, defaults={"grok_username": username, **data}
                )
            for data in payload.get("grok_cars", []):
                car_id = data.pop("id")
                name = data.pop("pool_name")
                GrokPool.objects.update_or_create(
                    id=car_id, defaults={"pool_name": name, **data}
                )
            for data in payload.get("users", []):
                username = data.pop("username")
                User.objects.update_or_create(username=username, defaults=data)
            for data in payload.get("visit_logs", []):
                log_id = data.pop("id")
                VisitLog.objects.update_or_create(id=log_id, defaults=data)
            req_gateway("post", "/api/backup/restore", json=payload.get("gateway") or {})
        return Response({"message": "统一备份恢复完成；现有会话未恢复，请重新登录"})
