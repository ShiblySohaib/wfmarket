import json
import requests

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from market.models import MarketSettings
from sources.models import SourceBalance
from .models import Item


def _request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


def _sync_sources(item, source_ids):
    if source_ids is None:
        return
    if not isinstance(source_ids, list):
        source_ids = [source_ids]
    cleaned = [source_id for source_id in source_ids if source_id not in ("", None)]
    item.sources.set(SourceBalance.objects.filter(id__in=cleaned))


@require_GET
def index(request):
    items = Item.objects.prefetch_related("sources").order_by("name")
    sources = SourceBalance.objects.order_by("source_name")
    
    # Fetch global rate limit from market settings
    mk_settings = MarketSettings.objects.first() or MarketSettings()
    
    context = {
        "items":      items, 
        "sources":    sources,
        "rate_limit": mk_settings.rate_limit or 1
    }
    return render(request, "inventory/index.html", context)


@require_POST
def add_item(request):
    data = _request_data(request)
    try:
        item = Item.objects.create(
            name=(data.get("name") or "").strip(),
            category=(data.get("category") or "").strip(),
            quantity=int(data.get("quantity") or 1),
            price=int(data["price"]) if data.get("price") not in ("", None) else None,
        )
        _sync_sources(item, data.get("source_ids") or request.POST.getlist("source_ids"))
        return JsonResponse({"success": True, "id": item.id})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@require_POST
def edit_item(request, item_id):
    data = _request_data(request)
    item = get_object_or_404(Item, pk=item_id)
    try:
        item.name = (data.get("name") or item.name).strip()
        item.category = (data.get("category") or item.category).strip()
        item.quantity = int(data.get("quantity") or item.quantity)
        item.price = int(data["price"]) if data.get("price") not in ("", None) else None
        item.save()
        source_ids = data.get("source_ids")
        if source_ids is None and hasattr(request.POST, "getlist"):
            source_ids = request.POST.getlist("source_ids") or None
        _sync_sources(item, source_ids)
        return JsonResponse({"success": True})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@require_POST
def sync_item_label(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    if not item.slug:
        return JsonResponse({"success": False, "error": "Item has no slug."}, status=400)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        # Use the slug and v2 API as requested
        url = f"https://api.warframe.market/v2/item/{item.slug}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Extract i18n name
            new_name = data.get("data", {}).get("i18n", {}).get("en", {}).get("name")
            if new_name:
                old_name = item.name
                if new_name != old_name:
                    item.name = new_name
                    item.save()
                    return JsonResponse({
                        "success": True, 
                        "updated": True, 
                        "old_name": old_name, 
                        "new_name": new_name
                    })
                return JsonResponse({"success": True, "updated": False})
        return JsonResponse({"success": False, "error": f"API returned {resp.status_code}"}, status=resp.status_code)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_POST
def delete_item(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    try:
        item.delete()
        return JsonResponse({"success": True})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
