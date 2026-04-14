import time
import uuid
import datetime
from threading import Lock

from inventory.models import Item
from sources.models import SourceBalance

from .models import MarketSettings

FETCH_GUARD_TTL = 300

# IN-MEMORY STORE FOR QUEUE & PROGRESS
import threading

_state_lock = Lock()
_fetch_queue = []
_running_job = None
_progress_store = {}
_next_fetch_at = 0
_last_session_id = None
_scheduler_interrupt = threading.Event()
_labels_sync_active = False


def get_market_settings():
    settings_obj, _created = MarketSettings.objects.get_or_create(pk=1)
    return settings_obj


def generate_session_id():
    return str(uuid.uuid4())


def list_items_for_fetch(item_ids=None):
    queryset = Item.objects.prefetch_related("sources").order_by("name")
    if item_ids:
        queryset = queryset.filter(id__in=item_ids)
    return list(queryset)


def list_sources():
    return list(SourceBalance.objects.order_by("source_name"))


def serialize_sources(sources):
    return [{"id": source.id, "source_name": source.source_name, "balance": source.balance} for source in sources]


def build_fetch_job(item_ids=None, max_orders=None, created_by="system", session_id=None):
    settings_obj = get_market_settings()
    items = list_items_for_fetch(item_ids)
    sources = list_sources()
    return {
        "session_id": session_id or generate_session_id(),
        "item_ids": [item.id for item in items],
        "source_balances": serialize_sources(sources),
        "rate_limit": settings_obj.rate_limit,
        "max_orders": max_orders if max_orders not in (None, "") else settings_obj.max_orders,
        "created_by": created_by,
        "status": "queued",
        "created_at": time.time(),
        "updated_at": time.time()
    }


def initial_progress(job, status="queued"):
    return {
        "session_id": job["session_id"],
        "status": status,
        "progress": 0,
        "market_data": [],
        "failed_items": [],
        "processed_items": 0,
        "total_items": len(job.get("item_ids") or []),
        "successful_items": 0,
        "total_failed": 0,
        "created_by": job.get("created_by") or "",
        "started_at": datetime.datetime.now().isoformat(),
        "scheduled_at": datetime.datetime.now().isoformat(),
    }


def set_fetch_progress(session_id, payload):
    with _state_lock:
        if session_id not in _progress_store:
            _progress_store[session_id] = {}
        _progress_store[session_id].update(payload)
        
        # update running job status if matched
        global _running_job
        if _running_job and _running_job["session_id"] == session_id:
            s = payload.get("status")
            if s:
                _running_job["status"] = s
                _running_job["updated_at"] = time.time()


def get_fetch_progress(session_id):
    with _state_lock:
        return _progress_store.get(session_id)


def clear_pending_fetch():
    with _state_lock:
        for job in _fetch_queue:
            sid = job["session_id"]
            if sid in _progress_store:
                _progress_store[sid]["status"] = "aborted"
        _fetch_queue.clear()


def clear_queue():
    clear_pending_fetch()


def mark_fetch_complete(session_id):
    with _state_lock:
        global _running_job
        if _running_job and _running_job["session_id"] == session_id:
            _running_job["status"] = "complete"
            _running_job["updated_at"] = time.time()


def clear_stale_fetch_guard(max_age=FETCH_GUARD_TTL):
    with _state_lock:
        global _running_job
        if _running_job and _running_job["status"] == "running":
            if time.time() - _running_job["updated_at"] > max_age:
                sid = _running_job["session_id"]
                _running_job["status"] = "aborted"
                if sid in _progress_store:
                    _progress_store[sid]["status"] = "aborted"


def abort_session(session_id):
    with _state_lock:
        # Check running
        global _running_job
        if _running_job and _running_job["session_id"] == session_id:
            _running_job["status"] = "aborted"
            _running_job["updated_at"] = time.time()
            if session_id in _progress_store:
                _progress_store[session_id]["status"] = "aborted"
        
        # Check queue
        for job in _fetch_queue:
            if job["session_id"] == session_id:
                job["status"] = "aborted"
                if session_id in _progress_store:
                    _progress_store[session_id]["status"] = "aborted"


def wait_for_abort(session_id, timeout_seconds=5):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with _state_lock:
            # Check if running job is aborted
            if _running_job and _running_job["session_id"] == session_id:
                if _running_job["status"] == "aborted":
                    return True
            else:
                p = _progress_store.get(session_id)
                if p and p.get("status") == "aborted":
                    return True
                if not p:
                    return True
        time.sleep(0.25)
    return False


def enqueue_job(job, pending=False):
    status = "queued"
    job["status"] = status
    with _state_lock:
        global _last_session_id
        _last_session_id = job["session_id"]
        _fetch_queue.append(job)
        _progress_store[job["session_id"]] = initial_progress(job, status=status)
    return type('JobRet', (object,), {"session_id": job["session_id"], "status": status})()


def pop_fetch_job():
    with _state_lock:
        global _running_job
        if _fetch_queue:
            # Pop the first job that is not aborted
            while _fetch_queue:
                job = _fetch_queue.pop(0)
                if job["status"] != "aborted":
                    job["status"] = "running"
                    job["updated_at"] = time.time()
                    _running_job = job
                    
                    if job["session_id"] in _progress_store:
                        _progress_store[job["session_id"]]["status"] = "running"
                        _progress_store[job["session_id"]]["started_at"] = datetime.datetime.now().isoformat()
                    return job
        return None


def get_fetch_job(session_id):
    with _state_lock:
        global _running_job
        if _running_job and _running_job["session_id"] == session_id:
            return type('JobRet', (object,), {"status": _running_job["status"], "session_id": session_id})()
        for job in _fetch_queue:
            if job["session_id"] == session_id:
                return type('JobRet', (object,), {"status": job["status"], "session_id": session_id})()
        return None


def get_running_job():
    with _state_lock:
        global _running_job
        if _running_job and _running_job["status"] in ("running", "starting"):
            return type('JobRet', (object,), {
                "session_id": _running_job["session_id"],
                "status": _running_job["status"],
                "created_by": _running_job.get("created_by", "")
            })()
        return None


def get_pending_job():
    with _state_lock:
        for job in _fetch_queue:
            if job["status"] == "queued":
                return type('JobRet', (object,), {
                    "session_id": job["session_id"],
                    "status": job["status"],
                    "created_by": job.get("created_by", "")
                })()
        return None


def has_running_fetch():
    return get_running_job() is not None


def get_current_fetch_session():
    job = get_running_job()
    return job.session_id if job else None


def get_pending_fetch_session():
    job = get_pending_job()
    return job.session_id if job else None


def set_next_fetch_at(ts):
    global _next_fetch_at
    _next_fetch_at = ts


def get_next_fetch_at():
    return _next_fetch_at


def trigger_scheduler_reset():
    _scheduler_interrupt.set()


def get_last_session_id():
    with _state_lock:
        return _last_session_id


def set_labels_sync_active(active: bool):
    global _labels_sync_active
    with _state_lock:
        _labels_sync_active = active


def is_labels_sync_active():
    with _state_lock:
        return _labels_sync_active
