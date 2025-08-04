import requests
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from threading import Lock
from django.shortcuts import render
from django.http import JsonResponse
from django.core.cache import cache
from inventory.models import Item
from sources.models import SourceBalance
import logging
import uuid

logger = logging.getLogger(__name__)

# Configuration variables
AUTO_REFRESH_INTERVAL = 120  # Auto-refresh interval in seconds (2 minutes)

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

def get_source_balances():
    """Get source balances from database"""
    try:
        balances = {}
        for sb in SourceBalance.objects.all():
            balances[sb.source] = sb.balance
        return balances
    except Exception as e:
        logger.error(f"Error getting source balances: {e}")
        return {}

def is_item_affordable(item, source_balances):
    """Check if an item is affordable based on source balance"""
    if not item.source or item.source.strip() == '':
        return True  # No source means always show
    
    source_key = item.source.lower().strip()
    source_balance = source_balances.get(source_key, 0)
    
    return item.price <= source_balance

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
    
    # Check if this is a fresh server start and no cached data exists
    server_startup_time = cache.get('server_startup_time')
    if not server_startup_time:
        # Mark server as just started
        cache.set('server_startup_time', time.time(), None)  # Never expires
        cache.set('initial_data_loaded', False, None)
    
    return render(request, 'market/index.html', {
        'total_items': len(items),
        'has_items': len(items) > 0,
        'auto_refresh_interval': AUTO_REFRESH_INTERVAL  # Pass auto refresh interval to template
    })

def fetch_market_data(request):
    """AJAX endpoint to start market data fetching or get progress"""
    action = request.GET.get('action', 'start')
    
    if action == 'start':
        # Start new fetch process
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
        
        # Generate unique session ID for this fetch
        session_id = str(uuid.uuid4())
        
        # Initialize progress in cache
        cache.set(f'fetch_progress_{session_id}', {
            'status': 'starting',
            'market_data': [],
            'failed_items': [],
            'total_orders': 0,
            'total_failed': 0,
            'progress': 0,
            'processed_items': 0,
            'total_items': len(items)
        }, 600)  # 10 minutes timeout
        
        # Start background fetch
        thread = threading.Thread(target=fetch_market_data_background, args=(session_id, list(items)))
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'session_id': session_id,
            'status': 'started',
            'total_items': len(items)
        })
    
    elif action == 'progress':
        # Get progress for existing fetch
        session_id = request.GET.get('session_id')
        if not session_id:
            return JsonResponse({'error': 'No session_id provided'}, status=400)
        
        progress_data = cache.get(f'fetch_progress_{session_id}')
        if not progress_data:
            return JsonResponse({'error': 'Session not found or expired'}, status=404)
        
        return JsonResponse(progress_data)
    
    elif action == 'check_server_start':
        # Check if server just started and initial data should be loaded
        server_startup_time = cache.get('server_startup_time')
        initial_data_loaded = cache.get('initial_data_loaded', False)
        
        # If server started recently (within 10 minutes) and no initial data loaded
        if server_startup_time and not initial_data_loaded:
            current_time = time.time()
            time_since_start = current_time - server_startup_time
            
            # If server started within 10 minutes and no initial load happened
            if time_since_start < 600:  # 10 minutes
                return JsonResponse({
                    'should_load_immediately': True,
                    'reason': 'server_startup'
                })
        
        return JsonResponse({
            'should_load_immediately': False,
            'reason': 'normal_operation'
        })
    
    else:
        return JsonResponse({'error': 'Invalid action'}, status=400)

def fetch_market_data_background(session_id, items):
    """Background function to fetch market data with progress updates"""
    
    # Log fetching start
    log_fetch_start(len(items))
    
    # Get source balances at the start
    source_balances = get_source_balances()
    
    rate_limiter = RateLimiter(max_requests=10, time_window=1.0)
    market_data = []
    failed_items = []
    retry_queue = []
    total_items = len(items)
    processed_items = 0
    successful_items = 0  # Track only successful fetches
    
    def update_progress_only(status='fetching'):
        """Update only progress in cache (lightweight)"""
        progress_percent = int((successful_items / total_items) * 100) if total_items > 0 else 100
        
        # Get existing data from cache
        existing_data = cache.get(f'fetch_progress_{session_id}', {})
        
        # Update only progress-related fields
        existing_data.update({
            'status': status,
            'progress': progress_percent,
            'processed_items': processed_items,
            'successful_items': successful_items,
            'total_items': total_items
        })
        
        cache.set(f'fetch_progress_{session_id}', existing_data, 600)
    
    def update_full_data(status='fetching'):
        """Update full data including market_data and failed_items"""
        progress_percent = int((successful_items / total_items) * 100) if total_items > 0 else 100
        # Sort market data by platinum amount (highest first) before updating
        sorted_market_data = sorted(market_data, key=lambda x: x['platinum'], reverse=True)
        
        cache.set(f'fetch_progress_{session_id}', {
            'status': status,
            'market_data': sorted_market_data,
            'failed_items': failed_items.copy(),
            'total_orders': len(market_data),
            'total_failed': len(failed_items),
            'progress': progress_percent,
            'processed_items': processed_items,
            'successful_items': successful_items,
            'total_items': total_items
        }, 600)
    
    # First pass - fetch all items with progress updates
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_item = {
            executor.submit(fetch_item_orders, item.name, rate_limiter): item 
            for item in items
        }
        
        batch_count = 0
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            processed_items += 1
            
            try:
                result = future.result()
                if result['status'] == 'success':
                    successful_items += 1  # Only increment on success
                    # Process successful results
                    is_affordable = is_item_affordable(item, source_balances)
                    for order in result['data']:  # Show all orders per item
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
                            'user_status': order.get('user', {}).get('status', 'unknown'),
                            'is_affordable': is_affordable
                        })
                    
                    # Update progress bar every successful fetch
                    update_progress_only('fetching')
                    
                elif result['status'] == 'rate_limited':
                    retry_queue.append(item.name)
                else:
                    failed_items.append({
                        'item': item.name,
                        'error': result.get('error', 'Unknown error'),
                        'url': f"https://api.warframe.market/v1/items/{clean_item_name(item.name)}/orders"
                    })
            except Exception as e:
                failed_items.append({
                    'item': item.name,
                    'error': str(e),
                    'url': f"https://api.warframe.market/v1/items/{clean_item_name(item.name)}/orders"
                })
            
            batch_count += 1
            # Update full data (table) every 10 items
            if batch_count >= 10:
                update_full_data('fetching')
                batch_count = 0
    
    # Update progress after first pass
    update_full_data('retrying' if retry_queue else 'completing')
    
    # Retry rate-limited items until there are no more to retry
    max_retry_attempts = 10  # Limit to avoid infinite loops
    retry_attempt = 0
    
    while retry_queue and retry_attempt < max_retry_attempts:
        retry_attempt += 1
        next_retry_queue = []  # For items that need another retry
        
        time.sleep(2)  # Wait a bit before retrying
        update_full_data(f'retrying (attempt {retry_attempt})')
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            retry_futures = {
                executor.submit(fetch_item_orders, item_name, rate_limiter): item_name 
                for item_name in retry_queue
            }
            
            for future in as_completed(retry_futures):
                item_name = retry_futures[future]
                try:
                    result = future.result()
                    if result['status'] == 'success':
                        successful_items += 1  # Increment successful count on retry success
                        item = next((i for i in items if i.name == item_name), None)
                        if item:
                            is_affordable = is_item_affordable(item, source_balances)
                            for order in result['data']:  # Show all orders per item
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
                                    'user_status': order.get('user', {}).get('status', 'unknown'),
                                    'is_affordable': is_affordable
                                })
                        
                        # Update progress bar on retry success
                        update_progress_only('retrying')
                    elif result['status'] == 'rate_limited':
                        # Still rate limited - add to next retry queue
                        log_rate_limit(f"{item_name} (retry attempt {retry_attempt})")
                        next_retry_queue.append(item_name)
                    else:
                        # Only add to failed items if it's a real failure (not rate limiting)
                        failed_items.append({
                            'item': item_name,
                            'error': result.get('error', 'Retry failed'),
                            'url': f"https://api.warframe.market/v1/items/{clean_item_name(item_name)}/orders"
                        })
                except Exception as e:
                    failed_items.append({
                        'item': item_name,
                        'error': str(e),
                        'url': f"https://api.warframe.market/v1/items/{clean_item_name(item_name)}/orders"
                    })
        
        # Update retry queue with items that are still rate-limited
        retry_queue = next_retry_queue
        
        # Update progress with current retry status
        if retry_queue:
            update_full_data(f'retrying (remaining: {len(retry_queue)})')
        
        # If there are no more items to retry, break the loop
        if not retry_queue:
            break
    
    # Final update - mark as complete
    update_full_data('complete')
    
    # Mark initial data as loaded if this was the first load after server start
    cache.set('initial_data_loaded', True, None)
    
    # Log completion
    success_count = len(market_data)
    failed_count = len(failed_items)
    log_completion(success_count, failed_count)