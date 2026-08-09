import time
from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from django.middleware.csrf import get_token, rotate_token
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from app.accounts.models import User, VisitLog
from app.accounts.serializers import ShowVisitLogModelSerializer, AddUserAccountSerializer, UserBindGrokSerializer, \
    ShowUserAccountModelSerializer, BatchModelLimitSerializer, BatchUserActionSerializer, ChangePasswordSerializer
from app.accounts.authentication import set_auth_cookie
from rest_framework.authtoken.models import Token
from app.grok.models import GrokAccount
from app.page import DefaultPageNumberPagination
from app.settings import ADMIN_USERNAME
from app.utils import get_request_subject, req_gateway
from app.accounts.views.login import issue_user_token


def revoke_user_sessions(user):
    Token.objects.filter(user=user).delete()
    try:
        req_gateway("post", "/api/logout", json={"user_name": user.username})
    except ValidationError:
        pass


def quota_snapshot(user):
    now = timezone.now()
    day_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    month_start = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    daily_used = VisitLog.objects.filter(
        username=user.username, log_type="proxy", created_at__gte=day_start
    ).count()
    monthly_used = VisitLog.objects.filter(
        username=user.username, log_type="proxy", created_at__gte=month_start
    ).count()
    try:
        remote = req_gateway("post", "/api/get-user-quota-usage", json={
            "user_name": get_request_subject_from_user(user),
            "day_start": day_start,
            "month_start": month_start,
        })
        daily_used = int(remote.get("daily_used", daily_used))
        monthly_used = int(remote.get("monthly_used", monthly_used))
    except ValidationError:
        pass
    return {
        "daily": {"limit": user.daily_quota, "used": daily_used},
        "monthly": {"limit": user.monthly_quota, "used": monthly_used},
    }


def get_request_subject_from_user(user):
    return user.username


def normalized_model_limits(user):
    return [item for item in (user.model_limit or []) if isinstance(item, str)]


class GetMirrorToken(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user = request.user

        user_grok_list = GrokAccount.get_by_grok_pool_list(user.grok_pool_list)
        grok_accounts = []
        for account in user_grok_list:
            login_mode = None
            if account.access_token_valid and account.access_token:
                login_mode = "api"
            elif account.session_token_valid and (account.session_token or account.has_sso):
                login_mode = "web"
            if not account.auth_status or not login_mode:
                continue
            grok_accounts.append({
                "grok_username": account.grok_username,
                "access_token": account.access_token or "",
                "session_token": account.session_token,
                "extra_cookies": account.extra_cookies or [],
                "login_mode": login_mode,
                "proxy_node_id": account.proxy_node_id,
            })
        res = req_gateway("post", "/api/get-mirror-token", json={
            "isolated_session": user.isolated_session,
            "limits": normalized_model_limits(user),
            "grok_accounts": grok_accounts,
            "user_name": get_request_subject(request),
            "daily_quota": user.daily_quota,
            "monthly_quota": user.monthly_quota,
        })
        for line in res:
            obj = GrokAccount.objects.filter(grok_username=line["grok_username"]).first()
            if obj:
                line["auth_status"] = obj.auth_status
                line["plan_type"] = obj.plan_type
        return Response(res)


class UserGrokAccountList(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        results = []
        user_grok_list = GrokAccount.get_by_grok_pool_list(request.user.grok_pool_list)
        for account in user_grok_list:
            try:
                account.refresh_auth_diagnostics()
            except Exception:
                pass
        grok_list = [i.grok_username for i in user_grok_list]

        try:
            use_count_dict = req_gateway("post", "/api/get-grok-use-count", json={"grok_list": grok_list})
        except:
            use_count_dict = {}

        auth_user_grok_list = [i for i in user_grok_list if i.auth_status]
        current_minute = datetime.now().minute

        for line in auth_user_grok_list or user_grok_list:
            grok_use_count_dict = use_count_dict.get(line.grok_username, {}).get("grok-4.5", {})
            last_3h_use_count = (grok_use_count_dict.get("last_1h", 0) +
                          grok_use_count_dict.get("last_2h", 0) + grok_use_count_dict.get("last_3h", 0) +
                          grok_use_count_dict.get("last_4h", 0) * (1 - current_minute / 60))
            supported_login_modes = []
            if line.access_token_valid:
                supported_login_modes.append("api")
            if line.session_token_valid or line.has_sso:
                supported_login_modes.append("web")
            results.append({
                "id": line.id,
                "use_count": last_3h_use_count,
                "grok_flag": "{:03}{}".format(line.id, line.grok_username[:3]),
                "plan_type": line.plan_type,
                "auth_status": line.auth_status,
                "access_token_valid": line.access_token_valid,
                "session_token_valid": line.session_token_valid,
                "supported_login_modes": supported_login_modes,
                "default_login_mode": "web",
            })

        return Response({"results": results})


class BatchModelLimit(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def post(self, request):
        serializer = BatchModelLimitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        User.objects.filter(id__in=serializer.data["user_id_list"]).update(model_limit=serializer.data["model_limit"])
        return Response({"message": "更新成功"})


class MirrorProxyConfigView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        return Response(req_gateway("get", "/api/mirror-proxy-config"))

    def post(self, request):
        enabled = request.data.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        return Response(req_gateway("post", "/api/mirror-proxy-config", json={
            "enabled": bool(enabled),
            "proxy_url": request.data.get("proxy_url"),
            "username": request.data.get("username"),
            "password": request.data.get("password"),
            "nodes": request.data.get("nodes") or [],
        }))


class MirrorProxyTestView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def post(self, request):
        enabled = request.data.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        return Response(req_gateway("post", "/api/test-mirror-proxy-config", json={
            "enabled": bool(enabled),
            "proxy_url": request.data.get("proxy_url"),
            "username": request.data.get("username"),
            "password": request.data.get("password"),
            "nodes": request.data.get("nodes") or [],
        }))


class CustomScriptConfigView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        return Response(req_gateway("get", "/api/custom-scripts"))

    def post(self, request):
        return Response(req_gateway("post", "/api/custom-scripts", json={
            "scripts": request.data.get("scripts") or [],
        }))


class UserRelateGrokPoolView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def post(self, request, *args, **kwargs):
        serializer = UserBindGrokSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for user_id in serializer.data["user_id_list"]:
            user = User.objects.filter(id=user_id).first()
            user.grok_pool_list = serializer.data["grok_pool_id_list"]
            user.save()

        return Response({"message": "绑定成功"})


class UserAccountView(generics.ListCreateAPIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request, *args, **kwargs):
        queryset = User.objects.order_by("-id").all()
        query = str(request.query_params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(Q(username__icontains=query) | Q(remark__icontains=query))
        status = request.query_params.get("status")
        if status in ("active", "inactive"):
            queryset = queryset.filter(is_active=status == "active")
        pg = DefaultPageNumberPagination()
        pg.page_size_query_param = "page_size"
        page_accounts = pg.paginate_queryset(queryset, request=request)
        username_list = [i.username for i in page_accounts]
        try:
            use_count_dict = req_gateway("post", "/api/get-user-use-count", json={"username_list": username_list})
        except:
            use_count_dict = {}
        serializer = ShowUserAccountModelSerializer(instance=page_accounts, use_count_dict=use_count_dict, many=True)
        return pg.get_paginated_response(serializer.data)

    def post(self, request, *args, **kwargs):
        # 添加或更新用户
        serializer = AddUserAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.data["username"] == ADMIN_USERNAME:
            raise ValidationError({"message": "管理员账号不能操作"})

        user = User.objects.filter(username=serializer.data["username"]).first()
        created = user is None
        if created:
            if not serializer.data.get("password"):
                raise ValidationError({"password": "新增用户必须设置密码"})
            user = User(username=serializer.data["username"])

        if serializer.data.get("password"):
            user.set_password(serializer.data["password"])

        if "expired_date" in serializer.data.keys():
            user.expired_date = serializer.data["expired_date"]

        user.grok_pool_list = serializer.data["grok_pool_list"]
        user.is_active = serializer.data["is_active"]
        user.model_limit = serializer.data["model_limit"]
        user.isolated_session = serializer.data["isolated_session"]
        user.remark = serializer.data["remark"]
        user.daily_quota = serializer.data.get("daily_quota", 0)
        user.monthly_quota = serializer.data.get("monthly_quota", 0)
        user.save()

        credentials_changed = bool(serializer.data.get("password"))
        access_revoked = not user.is_active or (
            user.expired_date and user.expired_date <= timezone.localdate()
        )
        if credentials_changed or access_revoked:
            revoke_user_sessions(user)

        return Response({"message": "添加成功"})

    def delete(self, request, *args, **kwargs):
        username = request.data.get("username")
        if username == ADMIN_USERNAME:
            raise ValidationError({"message": "不能删除管理员账号"})
        User.objects.filter(username=username).delete()
        return Response({"message": "删除成功"})


class VisitLogView(generics.ListAPIView):
    permission_classes = (IsAuthenticated, IsAdminUser)
    queryset = VisitLog.objects.order_by("-id").all()
    serializer_class = ShowVisitLogModelSerializer
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        query = str(self.request.query_params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) | Q(grok_username__icontains=query)
            )
        log_type = self.request.query_params.get("log_type")
        if log_type:
            queryset = queryset.filter(log_type=log_type)
        return queryset

    def delete(self, request, *args, **kwargs):
        protected_logs = VisitLog.objects.filter(
            username=ADMIN_USERNAME,
            log_type="login",
        )
        protected_count = protected_logs.count()
        deleted_count, _ = VisitLog.objects.exclude(
            username=ADMIN_USERNAME,
            log_type="login",
        ).delete()
        return Response({
            "message": "日志已清除",
            "deleted_count": deleted_count,
            "protected_count": protected_count,
        })


class BatchUserActionView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def post(self, request):
        serializer = BatchUserActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        queryset = User.objects.filter(id__in=serializer.validated_data["user_id_list"]).exclude(
            username=ADMIN_USERNAME
        )
        action = serializer.validated_data["action"]
        users = list(queryset)
        if action == "delete":
            for user in users:
                revoke_user_sessions(user)
            changed, _ = queryset.delete()
        else:
            active = action == "activate"
            changed = queryset.update(is_active=active)
            if not active:
                for user in users:
                    revoke_user_sessions(user)
        return Response({"message": "批量操作完成", "changed": changed})


class CurrentUserView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response({
            "authenticated": True,
            "username": request.user.username,
            "is_admin": bool(request.user.is_staff or request.user.is_superuser),
            "quota": quota_snapshot(request.user),
            "csrf_token": get_token(request),
        })


class ChangePasswordView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["current_password"]):
            raise ValidationError({"current_password": "当前密码不正确"})
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        revoke_user_sessions(request.user)
        token = issue_user_token(request.user, rotate=True)
        rotate_token(request)
        response = Response({
            "message": "密码修改成功，其他会话已退出",
            "csrf_token": get_token(request),
        })
        set_auth_cookie(response, token)
        return response


class QuotaView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(quota_snapshot(request.user))


class OperationsOverviewView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        today_start = int(
            timezone.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        accounts = GrokAccount.objects.all()
        try:
            gateway_metrics = req_gateway(
                "post", "/api/operations-overview", json={"day_start": today_start}
            )
        except ValidationError:
            gateway_metrics = {}
        return Response({
            "users": {
                "total": User.objects.count(),
                "active": User.objects.filter(is_active=True).count(),
                "expired": User.objects.filter(expired_date__lte=timezone.localdate()).count(),
            },
            "upstream": {
                "total": accounts.count(),
                "healthy": accounts.filter(auth_status=True).count(),
                "unhealthy": accounts.filter(auth_status=False).count(),
            },
            "activity": {
                "today_logins": VisitLog.objects.filter(
                    log_type="login", created_at__gte=today_start
                ).count(),
                "today_requests": VisitLog.objects.filter(
                    log_type="proxy", created_at__gte=today_start
                ).count() or int(gateway_metrics.get("today_requests", 0)),
                "active_sessions": int(gateway_metrics.get("active_sessions", 0)),
            },
            "generated_at": int(time.time()),
        })
