from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from .models import SourceBalance
import json

def index(request):
    """Sources page - display all source balances"""
    sources = SourceBalance.objects.all().order_by('source')
    return render(request, 'sources/index.html', {
        'sources': sources,
        'total_sources': sources.count()
    })

def add_source(request):
    """Add a new source balance"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            source_name = data.get('source', '').strip()
            balance = int(data.get('balance', 0))
            
            if not source_name:
                return JsonResponse({'error': 'Source name is required'}, status=400)
            
            if balance < 0:
                return JsonResponse({'error': 'Balance cannot be negative'}, status=400)
            
            # Check if source already exists
            if SourceBalance.objects.filter(source__iexact=source_name).exists():
                return JsonResponse({'error': 'Source already exists'}, status=400)
            
            # Create new source
            source_balance = SourceBalance.objects.create(
                source=source_name.lower(),
                balance=balance
            )
            
            return JsonResponse({
                'success': True,
                'source': {
                    'id': source_balance.id,
                    'source': source_balance.source,
                    'balance': source_balance.balance
                }
            })
            
        except ValueError:
            return JsonResponse({'error': 'Invalid balance value'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

def edit_source(request, source_id):
    """Edit an existing source balance"""
    if request.method == 'POST':
        try:
            source_balance = get_object_or_404(SourceBalance, id=source_id)
            data = json.loads(request.body)
            
            source_name = data.get('source', '').strip()
            balance = int(data.get('balance', 0))
            
            if not source_name:
                return JsonResponse({'error': 'Source name is required'}, status=400)
            
            if balance < 0:
                return JsonResponse({'error': 'Balance cannot be negative'}, status=400)
            
            # Check if source name already exists (excluding current source)
            if SourceBalance.objects.filter(source__iexact=source_name).exclude(id=source_id).exists():
                return JsonResponse({'error': 'Source already exists'}, status=400)
            
            # Update source
            source_balance.source = source_name.lower()
            source_balance.balance = balance
            source_balance.save()
            
            return JsonResponse({
                'success': True,
                'source': {
                    'id': source_balance.id,
                    'source': source_balance.source,
                    'balance': source_balance.balance
                }
            })
            
        except ValueError:
            return JsonResponse({'error': 'Invalid balance value'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

def delete_source(request, source_id):
    """Delete a source balance"""
    if request.method == 'DELETE':
        try:
            source_balance = get_object_or_404(SourceBalance, id=source_id)
            source_name = source_balance.source
            source_balance.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Source "{source_name}" deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)
