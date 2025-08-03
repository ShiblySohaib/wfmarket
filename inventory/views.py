from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from .models import Item


def index(request):
    """Display the inventory index page"""
    items = Item.objects.all()
    context = {
        'items': items,
        'total_items': items.count(),
    }
    return render(request, 'inventory/index.html', context)


@require_POST
def add_item(request):
    """Add a new item via AJAX"""
    try:
        item = Item(
            name=request.POST.get('name'),
            quantity=int(request.POST.get('quantity')),
            category=request.POST.get('category'),
            source=request.POST.get('source', ''),
            price=int(request.POST.get('price', 0))
        )
        
        item.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@require_POST
def edit_item(request, item_id):
    """Edit an item via AJAX"""
    try:
        item = get_object_or_404(Item, id=item_id)
        
        item.name = request.POST.get('name')
        item.quantity = int(request.POST.get('quantity'))
        item.category = request.POST.get('category')
        item.source = request.POST.get('source')
        item.price = int(request.POST.get('price'))
        
        item.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@require_POST
def delete_item(request, item_id):
    """Delete an item via AJAX"""
    try:
        item = get_object_or_404(Item, id=item_id)
        item.delete()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
