import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from threading import Lock
from django.shortcuts import render
from django.http import JsonResponse
from inventory.models import Item
import logging

logger = logging.getLogger(__name__)

# ANSI color codes for colored terminal output
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    ORANGE = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'  # End color
    BOLD = '\033[1m'

def colored_print(message, color):
    """Print colored message to console"""
    print(f"{color}{message}{Colors.ENDC}")

def log_fetch_start(total_items):
    """Log when fetching starts"""
    colored_print(f"🚀 Starting market data fetch for {total_items} items...", Colors.BLUE)

def log_rate_limit(item_name):
    """Log when an item hits rate limit (429)"""
    colored_print(f"⚠️  Rate limited: {item_name} (will retry)", Colors.ORANGE)

def log_permanent_failure(item_name, error):
    """Log when an item fails permanently"""
    colored_print(f"❌ Failed permanently: {item_name} - {error}", Colors.RED)

def log_completion(success_count, failed_count):
    """Log when fetching is completed"""
    colored_print(f"✅ Market data fetch completed! {success_count} successful, {failed_count} failed", Colors.GREEN)

class RateLimiter:
    def __init__(self, max_requests=10, time_window=1.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            # Remove requests older than time_window
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # If we're at the limit, wait
            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Clean up again after sleeping
                    now = time.time()
                    while self.requests and self.requests[0] <= now - self.time_window:
                        self.requests.popleft()
            
            # Add current request
            self.requests.append(now)

import re

def clean_item_name(name):
    """Clean item name for API usage"""
    # Convert to lowercase
    name = name.lower()
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Remove all other non-alphanumeric characters except underscores
    cleaned = re.sub(r"[^a-z0-9_]", "", name)
    # Remove multiple consecutive underscores
    cleaned = re.sub(r"_+", "_", cleaned)
    # Remove leading/trailing underscores
    cleaned = cleaned.strip("_")
    return cleaned


def fetch_item_orders(item_name, rate_limiter):
    """Fetch buy orders for a specific item"""
    clean_name = clean_item_name(item_name)
    url = f"https://api.warframe.market/v1/items/{clean_name}/orders"
    
    rate_limiter.wait_if_needed()
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            # Rate limited, return for retry queue
            log_rate_limit(item_name)
            return {'item': item_name, 'status': 'rate_limited', 'data': None}
        elif response.status_code != 200:
            # Permanent failure
            error_msg = f"HTTP {response.status_code}"
            log_permanent_failure(item_name, error_msg)
            logger.error(f"Failed to fetch orders for {item_name}: {error_msg}")
            return {'item': item_name, 'status': 'failed', 'data': None, 'error': error_msg}
        
        data = response.json()
        orders = data.get('payload', {}).get('orders', [])
        
        # Filter for buy orders from ingame users
        buy_orders = [
            order for order in orders
            if order.get('order_type') == 'buy' and 
               order.get('user', {}).get('status') == 'ingame'
        ]
        
        # Sort by platinum amount (highest first)
        buy_orders.sort(key=lambda x: x.get('platinum', 0), reverse=True)
        
        return {'item': item_name, 'status': 'success', 'data': buy_orders}
        
    except requests.RequestException as e:
        error_msg = str(e)
        log_permanent_failure(item_name, error_msg)
        logger.error(f"Request failed for {item_name}: {error_msg}")
        return {'item': item_name, 'status': 'failed', 'data': None, 'error': error_msg}

def index(request):
    """Market page - loads immediately, data fetched via AJAX"""
    items = Item.objects.all()
    
    return render(request, 'market/index.html', {
        'total_items': len(items),
        'has_items': len(items) > 0
    })

def fetch_market_data(request):
    """AJAX endpoint to fetch market data progressively"""
    items = Item.objects.all()
    
    if not items:
        return JsonResponse({
            'status': 'complete',
            'market_data': [],
            'failed_items': [],
            'total_orders': 0,
            'total_failed': 0,
            'progress': 100
        })
    
    # Log fetching start
    log_fetch_start(len(items))
    
    rate_limiter = RateLimiter(max_requests=10, time_window=1.0)
    market_data = []
    failed_items = []
    retry_queue = []
    total_items = len(items)
    processed_items = 0
    
    # First pass - fetch all items
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_item = {
            executor.submit(fetch_item_orders, item.name, rate_limiter): item 
            for item in items
        }
        
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            processed_items += 1
            
            try:
                result = future.result()
                if result['status'] == 'success':
                    # Process successful results
                    for order in result['data'][:5]:  # Limit to top 5 orders per item
                        market_data.append({
                            'item': item.name,
                            'item_id': item.id,
                            'category': item.category,
                            'source': item.source or 'Unknown',
                            'inventory_quantity': item.quantity,
                            'buyer': order.get('user', {}).get('ingame_name', 'Unknown'),
                            'platinum': order.get('platinum', 0),
                            'order_quantity': order.get('quantity', 1),
                            'rank': order.get('mod_rank', 0),
                            'user_reputation': order.get('user', {}).get('reputation', 0),
                            'user_status': order.get('user', {}).get('status', 'unknown')
                        })
                elif result['status'] == 'rate_limited':
                    retry_queue.append(item.name)
                else:
                    failed_items.append({
                        'item': item.name,
                        'error': result.get('error', 'Unknown error')
                    })
            except Exception as e:
                failed_items.append({
                    'item': item.name,
                    'error': str(e)
                })
    
    # Retry rate-limited items
    if retry_queue:
        time.sleep(2)  # Wait a bit before retrying
        with ThreadPoolExecutor(max_workers=3) as executor:
            retry_futures = {
                executor.submit(fetch_item_orders, item_name, rate_limiter): item_name 
                for item_name in retry_queue
            }
            
            for future in as_completed(retry_futures):
                item_name = retry_futures[future]
                try:
                    result = future.result()
                    if result['status'] == 'success':
                        item = items.get(name=item_name)
                        for order in result['data'][:5]:
                            market_data.append({
                                'item': item.name,
                                'item_id': item.id,
                                'category': item.category,
                                'source': item.source or 'Unknown',
                                'inventory_quantity': item.quantity,
                                'buyer': order.get('user', {}).get('ingame_name', 'Unknown'),
                                'platinum': order.get('platinum', 0),
                                'order_quantity': order.get('quantity', 1),
                                'rank': order.get('mod_rank', 0),
                                'user_reputation': order.get('user', {}).get('reputation', 0),
                                'user_status': order.get('user', {}).get('status', 'unknown')
                            })
                    else:
                        failed_items.append({
                            'item': item_name,
                            'error': result.get('error', 'Rate limit retry failed')
                        })
                except Exception as e:
                    failed_items.append({
                        'item': item_name,
                        'error': str(e)
                    })
    
    # Sort market data by platinum amount (highest first)
    market_data.sort(key=lambda x: x['platinum'], reverse=True)
    
    # Log completion
    success_count = len(market_data)
    failed_count = len(failed_items)
    log_completion(success_count, failed_count)
    
    return JsonResponse({
        'status': 'complete',
        'market_data': market_data,
        'failed_items': failed_items,
        'total_orders': len(market_data),
        'total_failed': len(failed_items),
        'progress': 100
    })
