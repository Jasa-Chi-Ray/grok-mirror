from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from app.grok.models import GrokPool
from app.grok.serializers import ShowGrokPoolSerializer, AddGrokPoolModelSerializer, DeleteGrokPoolSerializer
from app.page import DefaultPageNumberPagination


class GrokPoolEnum(APIView):
    permission_classes = (IsAuthenticated, IsAdminUser)

    def get(self, request):
        result = GrokPool.objects.order_by("-id").values("id", "pool_name").all()
        return Response({"data": result})


class GrokPoolView(generics.ListCreateAPIView):
    permission_classes = (IsAuthenticated, IsAdminUser)
    queryset = GrokPool.objects.order_by("-id").all()
    serializer_class = ShowGrokPoolSerializer
    pagination_class = DefaultPageNumberPagination

    def post(self, request, *args, **kwargs):
        obj = GrokPool.objects.filter(id=request.data.get("id")).first()
        serializer = AddGrokPoolModelSerializer(instance=obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, *args, **kwargs):
        serializer = DeleteGrokPoolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        GrokPool.objects.filter(id__in=serializer.data["ids"]).delete()
        return Response({"message": "删除成功"})
