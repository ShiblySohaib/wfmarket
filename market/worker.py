import time
import re
import logging
import requests
from threading import Event, Thread, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

class TokenBucket:
    def __init__(self, tokens_per_second):
        self.tokens_per_second = float(max(tokens_per_second or 1, 1))
        self.capacity = self.tokens_per_second
        self.tokens   = self.tokens_per_second
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def wait_for_token(self):
        while True:
            with self._lock:
                now     = time.monotonic()
                elapsed = now - self.last_refill
                self.last_refill = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.tokens_per_second)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                sleep_time = max((1.0 - self.tokens) / self.tokens_per_second, 0.05)
            time.sleep(sleep_time)


def clean_item_name(name: str) -> str:
    name    = name.lower().replace(" ", "_")
    cleaned = re.sub(r"[^a-z0-9_()]", "", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


# ─────────────────────────────────────────────
#  Worker thread
# ─────────────────────────────────────────────

class FetchWorker(Thread):
    def __init__(self, poll_interval: float = 1.0):
        super().__init__(daemon=True)
        self.poll_interval = poll_interval
        self.stop_event    = Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                from .services import pop_fetch_job
                job = pop_fetch_job()
                if not job:
                    time.sleep(self.poll_interval)
                    continue
                self.process_job(job)
            except Exception:
                logger.exception("FetchWorker top-level error")
                time.sleep(self.poll_interval)

    def stop(self):
        self.stop_event.set()

    # ── helpers ──────────────────────────────

    def _is_aborted(self, session_id: str) -> bool:
        from .services import get_fetch_progress
        prog = get_fetch_progress(session_id)
        return prog is not None and prog.get("status") == "aborted"

    def is_affordable(self, item, source_balances: dict) -> bool:
        source_keys = []
        try:
            for s in item.sources.all():
                source_keys.append(s.source_name.lower())
        except Exception:
            pass

        if not source_keys:
            return True

        item_price = item.price or 0
        if any(source_balances.get(k, 0) >= item_price for k in source_keys):
            return True
        return item_price <= sum(source_balances.get(k, 0) for k in source_keys)

    def get_source_balances_dict(self, job: dict) -> dict:
        balances = {}
        for sb in job.get("source_balances", []):
            name = (sb.get("source_name") or "").lower()
            if name:
                balances[name] = sb.get("balance", 0)
        return balances

    def build_market_entry(self, item, order: dict, is_affordable: bool, source_balances: dict, source_names: list) -> dict:
        user            = order.get("user") or {}
        buyer           = user.get("ingameName") or user.get("ingame_name") or user.get("name") or "Unknown"
        platinum        = order.get("platinum", 0)
        order_quantity  = order.get("quantity", 1)
        user_reputation = user.get("reputation", 0)
        user_status     = user.get("status", "unknown")

        total_source_balance = sum(source_balances.get(n.lower(), 0) for n in source_names) if source_names else 0

        total_source_balance = sum(source_balances.get(n.lower(), 0) for n in source_names) if source_names else 0
        
        # Lists for the "Source" column boxes
        balances_list = [source_balances.get(n.lower(), 0) for n in source_names]

        return {
            "item":            item.name,
            "item_id":         item.id,
            "item_price":      item.price or 0,
            "category":        getattr(item, "category", ""),
            "buyer":           buyer,
            "platinum":        platinum,
            "order_quantity":  order_quantity,
            "rank":            order.get("rank"), # Can be null or 0 for unranked
            "inventory_quantity": getattr(item, "quantity", 0),
            "sources_list":    source_names,
            "balances_list":   balances_list,
            "user_reputation": user_reputation,
            "user_status":     user_status,
            "is_affordable":   is_affordable,
            "source_balance":  total_source_balance,
        }

    # ── main job ─────────────────────────────

    def process_job(self, job: dict):
        from .services import (
            list_items_for_fetch,
            get_fetch_progress,
            set_fetch_progress,
            mark_fetch_complete,
        )

        session_id = job["session_id"]

        # Skip if already finished (e.g. aborted before worker picked it up)
        existing = get_fetch_progress(session_id)
        if existing and existing.get("status") in ("complete", "aborted"):
            return

        items           = list_items_for_fetch(job.get("item_ids"))
        total_items     = len(items)
        rate_limit      = max(int(job.get("rate_limit") or 1), 1)
        bucket          = TokenBucket(rate_limit)
        source_balances = self.get_source_balances_dict(job)
        max_orders      = job.get("max_orders")

        # ── Mutable state dict ────────────────────────────────────────────────
        # Using a dict instead of plain int variables fixes the Python closure
        # rebinding bug: `x += 1` inside a nested function creates a new local
        # binding that other closures can't see. Dict mutation is visible everywhere.
        state = {
            "market_data":      [],
            "failed_items":     [],
            "retry_queue":      [],
            "processed_items":  0,
            "successful_items": 0,
        }
        state_lock = Lock()

        # Write initial running progress
        set_fetch_progress(session_id, {
            "status":           "running",
            "progress":         0,
            "market_data":      [],
            "failed_items":     [],
            "processed_items":  0,
            "total_items":      total_items,
            "successful_items": 0,
            "total_failed":     0,
            "created_by":       job.get("created_by", ""),
        })
        logger.info("[%s] Fetch started — %d items", session_id[:8], total_items)

        def sync(status: str = "running"):
            sorted_data = sorted(state["market_data"], key=lambda x: x.get("platinum", 0), reverse=True)
            pct = int((state["processed_items"] / total_items) * 100) if total_items else 100
            set_fetch_progress(session_id, {
                "status":           status,
                "progress":         pct,
                "market_data":      sorted_data,
                "failed_items":     list(state["failed_items"]),
                "processed_items":  state["processed_items"],
                "successful_items": state["successful_items"],
                "total_items":      total_items,
                "total_failed":     len(state["failed_items"]),
            })

        # ── per-item fetch task ───────────────────────────────────────────────

        def fetch_item_task(item):
            if self._is_aborted(session_id):
                return None

            from market.services import is_labels_sync_active
            while is_labels_sync_active():
                if self._is_aborted(session_id):
                    return None
                time.sleep(1)

            bucket.wait_for_token()
            try:
                # Pre-fetch source names to avoid DB hits in the thread loop
                try:
                    source_names = [s.source_name for s in item.sources.all()]
                except Exception:
                    source_names = []

                url     = f"https://api.warframe.market/v2/orders/item/{item.slug}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 403:
                    time.sleep(1) # Backoff if forbidden (Cloudflare block)
                    return {"item": item, "status": "failed", "error": "HTTP 403 Forbidden"}
                if response.status_code == 429:
                    return {"item": item, "status": "rate_limited"}
                if response.status_code != 200:
                    return {"item": item, "status": "failed", "error": f"HTTP {response.status_code}"}

                data   = response.json()
                # API v2 returns { "data": [ ... ] } where the list contains the orders directly
                orders = data.get("data", []) if isinstance(data, dict) else []
                
                buy_orders = [
                    o for o in orders
                    if o.get("type") == "buy" and o.get("user", {}).get("status") == "ingame"
                ]
                buy_orders.sort(key=lambda x: x.get("platinum", 0), reverse=True)

                if max_orders not in (None, ""):
                    buy_orders = buy_orders[:int(max_orders)]

                is_aff  = self.is_affordable(item, source_balances)
                entries = [self.build_market_entry(item, o, is_aff, source_balances, source_names) for o in buy_orders]
                return {"item": item, "status": "success", "data": entries}

            except Exception as exc:
                logger.error("[%s] Error fetching %s: %s", session_id[:8], item.name, exc)
                return {"item": item, "status": "failed", "error": str(exc)}

        # ── parallel batch runner ─────────────────────────────────────────────

        workers = max(1, rate_limit)

        def run_batch(batch):
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(fetch_item_task, itm): itm for itm in batch}
                for future in as_completed(futures):
                    itm = futures[future]
                    try:
                        result = future.result()
                        if result is None:   # aborted mid-task
                            continue

                        url = f"https://api.warframe.market/v2/orders/item/{itm.slug}"
                        with state_lock:
                            if result["status"] == "success":
                                state["successful_items"] += 1
                                state["market_data"].extend(result["data"])
                                state["processed_items"] += 1 
                            elif result["status"] == "rate_limited":
                                state["retry_queue"].append(result["item"])
                            else:
                                state["failed_items"].append({
                                    "item_id":   itm.id,
                                    "item_name": itm.name,
                                    "error":     result.get("error", "unknown"),
                                    "url":       url,
                                })
                                state["processed_items"] += 1 
                            done = state["processed_items"]

                        # Terminal logging: exact URL and status code
                        status_msg = result["status"]
                        if "error" in result and "HTTP" in result["error"]:
                            status_msg = result["error"]
                        
                        print(f"[{done}/{total_items}] \"GET {url}\" — {status_msg}")

                        # Push live update to memory for every item
                        sync("running")

                    except Exception as exc:
                        with state_lock:
                            state["failed_items"].append({
                                "item_id":   itm.id,
                                "item_name": itm.name,
                                "error":     str(exc),
                            })
                            state["processed_items"] += 1
                        logger.warning("[%s] Future error for %s: %s",
                                       session_id[:8], itm.name, exc)

        # ── main fetch phase ──────────────────────────────────────────────────

        run_batch(items)

        # ── retry phase ───────────────────────────────────────────────────────

        attempt = 1
        while state["retry_queue"] and attempt <= 5:
            if self._is_aborted(session_id):
                break
            retry_count          = len(state["retry_queue"])
            logger.info("[%s] Retry attempt %d — %d rate-limited items",
                        session_id[:8], attempt, retry_count)
            time.sleep(2)
            current_retry        = list(state["retry_queue"])
            state["retry_queue"] = []
            sync(f"retrying ({retry_count} items)")
            run_batch(current_retry)
            attempt += 1

        # Permanently fail anything still in retry_queue after max attempts
        for itm in state["retry_queue"]:
            state["failed_items"].append({
                "item_id":   itm.id,
                "item_name": itm.name,
                "error":     "Max retries exceeded (rate limited)",
            })
            state["processed_items"] += 1

        # ── finalise ─────────────────────────────────────────────────────────

        final_status = "aborted" if self._is_aborted(session_id) else "complete"
        sync(final_status)
        mark_fetch_complete(session_id)
        logger.info("[%s] Fetch %s — %d ok / %d failed",
                    session_id[:8], final_status,
                    state["successful_items"], len(state["failed_items"]))