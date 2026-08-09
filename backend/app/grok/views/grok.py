import time

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from app.grok.models import GrokAccount, GrokPool, build_sso_cookie, parse_sso_expiry
from app.grok.serializers import ShowGrokTokenSerializer, AddGrokTokenSerializer, GrokLoginSerializer, \
    UpdateGrokInfoSerializer, DeleteGrokAccountSerializer, CheckGrokTokenExpirySerializer
from app.page import DefaultPageNumberPagination
from app.settings import GROK_GATEWAY_URL
from app.utils import get_request_subject, save_visit_log, req_gateway
from app.accounts.models import User
from rest_framework.exceptions import ValidationError

def build_token_expiry_result(account, now=None, error=""):
    now = now or int(time.time())
    exp = account.sso_expires_at

    remaining_seconds = None
    expired = None
    if isinstance(exp, int):
        remaining_seconds = exp - now
        expired = remaining_seconds <= 0

    return {
        "id": account.id,
        "grok_username": account.grok_username,
        "sso_exp": exp,
        "remaining_seconds": remaining_seconds,
        "expired": expired,
        "session_token_valid": account.session_token_valid,
        "last_check_at": account.last_check_at,
        "last_error": account.last_error or error,
        "has_sso": account.has_sso,
    }


class GrokAccountEnum(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        result = GrokAccount.objects.filter(auth_status=True).order_by("-id").values(
            "id", "grok_username", "plan_type").all()
        return Response({"data": result})


class GrokAccountView(generics.ListCreateAPIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request, *args, **kwargs):
        queryset = GrokAccount.objects.order_by("-id").all()
        query = str(request.query_params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(grok_username__icontains=query)
        status = request.query_params.get("status")
        if status in ("healthy", "unhealthy"):
            queryset = queryset.filter(auth_status=status == "healthy")
        pg = DefaultPageNumberPagination()
        pg.page_size_query_param = "page_size"
        page_accounts = pg.paginate_queryset(queryset, request=request)
        for account in page_accounts:
            try:
                account.refresh_auth_diagnostics()
            except Exception:
                pass
        grok_list = [i.grok_username for i in page_accounts]

        try:
            use_count_dict = req_gateway("post", "/api/get-grok-use-count", json={"grok_list": grok_list})
        except:
            use_count_dict = {}
        serializer = ShowGrokTokenSerializer(instance=page_accounts, use_count_dict=use_count_dict, many=True)
        return pg.get_paginated_response(serializer.data)

    def post(self, request, *args, **kwargs):
        serializer = AddGrokTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sso_cookie = build_sso_cookie(data["sso"], expires=data.get("sso_expires"))
        diagnostics = req_gateway("post", "/api/diagnose-grok-auth", json={
            "access_token": "",
            "session_token": None,
            "extra_cookies": [sso_cookie],
            "proxy_node_id": None,
        })
        user_info = diagnostics.get("user_info") or {}
        grok_username = str(user_info.get("email") or "").strip()
        if not diagnostics.get("sso_valid") or not grok_username:
            raise ValidationError({
                "sso": diagnostics.get("last_error") or "SSO Cookie 无效或无法识别账号",
            })

        now = int(time.time())
        account, created = GrokAccount.objects.get_or_create(
                grok_username=grok_username,
                defaults={
                    "plan_type": str(user_info.get("plan_type") or "Grok SSO"),
                    "access_token": "",
                    "auth_status": True,
                    "access_token_valid": False,
                    "session_token_valid": True,
                    "created_time": now,
                    "updated_time": now,
                },
        )
        detected_expiry = parse_sso_expiry(diagnostics.get("sso_expires_at"))
        account.set_sso(
            data["sso"],
            expires=detected_expiry or data.get("sso_expires"),
        )
        account.auth_status = True
        account.access_token_valid = False
        account.session_token_valid = True
        account.last_check_at = diagnostics.get("last_check_at") or now
        account.last_error = diagnostics.get("last_error") or ""
        account.updated_time = now
        account.plan_type = str(user_info.get("plan_type") or account.plan_type or "Grok SSO")
        account.save()
        return Response({
            "message": "SSO 账号录入成功",
            "created": created,
            "grok_username": account.grok_username,
        })

    def put(self, request):
        serializer = UpdateGrokInfoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = GrokAccount.objects.filter(grok_username=data["grok_username"]).first()
        if not account:
            raise ValidationError("账号不存在")
        account.remark = data.get("remark") or ""
        account.proxy_node_id = data.get("proxy_node_id")
        if data.get("sso"):
            account.set_sso(data["sso"], expires=data.get("sso_expires"))
            account.auth_status = False
            account.session_token_valid = False
            account.last_check_at = None
            account.last_error = ""
        account.updated_time = int(time.time())
        account.save()
        return Response({"message": "更新 Grok 信息成功"})

    def delete(self, request):
        serializer = DeleteGrokAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grok_obj = GrokAccount.objects.filter(grok_username=serializer.data["grok_username"]).first()
        if grok_obj:
            car_obj = GrokPool.objects.filter(grok_account_list=[grok_obj.id], pool_name__contains="reg_").first()
            if car_obj:
                User.objects.filter(grok_pool_list=[car_obj.id]).delete()
                car_obj.delete()
            grok_obj.delete()

        return Response({"message": "删除成功"})


class GrokTokenExpiryView(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def post(self, request):
        serializer = CheckGrokTokenExpirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        queryset = GrokAccount.objects.order_by("-id").all()
        ids = serializer.data.get("ids") or []
        if ids:
            queryset = queryset.filter(id__in=ids)

        now = int(time.time())
        results = []
        for account in queryset:
            error = ""

            try:
                account.refresh_auth_diagnostics(force=True)
            except Exception as exc:
                if not error:
                    error = str(exc)

            results.append(build_token_expiry_result(account, now=now, error=error))

        return Response({"results": results})


class GrokLoginView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = GrokLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_grok_list = GrokAccount.get_by_grok_pool_list(request.user.grok_pool_list)
        user_grok_id_list = [i.id for i in user_grok_list]

        login_mode = serializer.data.get("login_mode", "web")
        grok_id = serializer.validated_data.get("grok_id")
        if grok_id is not None and grok_id not in user_grok_id_list:
            raise ValidationError("该账号不属于当前用户")

        if grok_id is None:
            candidates = [
                item for item in user_grok_list
                if item.auth_status and item.session_token_valid
            ]
            if not candidates:
                raise ValidationError("账号池中没有可用上游账号")
            use_counts = req_gateway("post", "/api/get-grok-use-count", json={
                "grok_list": [item.grok_username for item in candidates],
            })
            def usage_score(item):
                hourly = use_counts.get(item.grok_username, {}).get("grok-4.5", {})
                return sum(int(hourly.get(key, 0)) for key in (
                    "last_1h", "last_2h", "last_3h", "last_4h"
                ))
            grok = min(candidates, key=usage_score)
        else:
            grok = GrokAccount.get_by_id(grok_id)

        if login_mode == "web" and not grok.session_token_valid:
            raise ValidationError("该账号当前不支持 Web 模式，请联系管理员更新 SSO Cookie")

        user_name = get_request_subject(request)
        payload = {
            "user_name": user_name,
            "grok_username": grok.grok_username,
            "access_token": grok.access_token,
            "session_token": grok.session_token,
            "extra_cookies": grok.extra_cookies,
            "login_mode": login_mode,
            "isolated_session": request.user.isolated_session,
            "limits": [
                item for item in (request.user.model_limit or []) if isinstance(item, str)
            ],
            "proxy_node_id": grok.proxy_node_id,
            "daily_quota": request.user.daily_quota,
            "monthly_quota": request.user.monthly_quota,
        }
        # print(payload)
        res_json = req_gateway("post", "/api/login", json=payload)

        save_visit_log(request, "choose-grok", grok.grok_username)

        return Response(res_json)
