import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from inventory.models import Item
from sources.models import SourceBalance

from .services import get_market_settings


def _request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


@require_GET
def index(request):
    items = Item.objects.prefetch_related("sources").order_by("name")
    sources = SourceBalance.objects.order_by("source_name")
    settings_obj = get_market_settings()
    return render(request, "market/index.html", {"items": items, "sources": sources, "settings": settings_obj})


@require_GET
def settings_json(request):
    settings_obj = get_market_settings()
    return JsonResponse(
        {
            "auto_refresh_interval": settings_obj.auto_refresh_interval,
            "high_alert_threshold": settings_obj.high_alert_threshold,
            "alert_threshold": settings_obj.alert_threshold,
            "rate_limit": settings_obj.rate_limit,
            "max_orders": settings_obj.max_orders,
        }
    )


@require_POST
def update_settings(request):
    data = _request_data(request)
    settings_obj = get_market_settings()
    try:
        for field in ["auto_refresh_interval", "high_alert_threshold", "alert_threshold", "rate_limit", "max_orders"]:
            value = data.get(field)
            if value == "":
                value = None
            if value is not None:
                setattr(settings_obj, field, int(value))
        settings_obj.save()
        return JsonResponse(
            {
                "auto_refresh_interval": settings_obj.auto_refresh_interval,
                "high_alert_threshold": settings_obj.high_alert_threshold,
                "alert_threshold": settings_obj.alert_threshold,
                "rate_limit": settings_obj.rate_limit,
                "max_orders": settings_obj.max_orders,
            }
        )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_GET
def settings_page(request):
    return render(request, "market/settings.html", {"settings": get_market_settings()})


@require_POST
def toggle_pause_for_labels(request):
    data = _request_data(request)
    pause = data.get("pause", False)
    from .services import set_labels_sync_active
    set_labels_sync_active(pause)
    return JsonResponse({"success": True, "paused": pause})
