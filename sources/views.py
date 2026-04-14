import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import SourceBalance


def _request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


@require_GET
def index(request):
    sources = SourceBalance.objects.order_by("source_name")
    return render(request, "sources/index.html", {"sources": sources})


@require_POST
def add_source(request):
    data = _request_data(request)
    try:
        source = SourceBalance.objects.create(
            source_name=(data.get("source_name") or data.get("source") or "").strip(),
            balance=int(data.get("balance") or 0),
        )
        return JsonResponse(
            {"id": source.id, "source_name": source.source_name, "balance": source.balance},
            status=200,
        )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
def edit_source(request, source_id):
    data = _request_data(request)
    source = get_object_or_404(SourceBalance, pk=source_id)
    try:
        source.source_name = (data.get("source_name") or data.get("source") or source.source_name).strip()
        source.balance = int(data.get("balance") or source.balance)
        source.save()
        return JsonResponse({"id": source.id, "source_name": source.source_name, "balance": source.balance})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_http_methods(["DELETE"])
def delete_source(request, source_id):
    source = get_object_or_404(SourceBalance, pk=source_id)
    source.delete()
    return JsonResponse({"success": True})
