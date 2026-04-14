import json
import logging
import os
import sys

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import (
    abort_session,
    build_fetch_job,
    clear_pending_fetch,
    clear_queue,
    clear_stale_fetch_guard,
    enqueue_job,
    get_current_fetch_session,
    get_fetch_progress,
    get_fetch_job,
    get_running_job,
    get_pending_job,
    get_next_fetch_at,
    get_last_session_id,
    wait_for_abort,
)
import time


def _request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


def _abort_running_fetch():
    clear_stale_fetch_guard()
    current_session = get_current_fetch_session()
    if current_session:
        abort_session(current_session)
        wait_for_abort(current_session)


@csrf_exempt
@require_POST
def fetch(request):
    data = _request_data(request)
    item_ids = data.get("item_ids")
    if isinstance(item_ids, str):
        item_ids = [i for i in item_ids.split(",") if i]
    max_orders = data.get("max_orders")
    created_by = data.get("created_by") or "manual"

    try:
        _abort_running_fetch()
        clear_pending_fetch()
        clear_queue()

        from .services import trigger_scheduler_reset
        trigger_scheduler_reset()
        job = build_fetch_job(item_ids=item_ids, created_by="foreground")
        fetch_job = enqueue_job(job, pending=False)
        return JsonResponse({"session_id": fetch_job.session_id, "status": fetch_job.status}, status=202)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@require_GET
def fetch_progress(request, session_id):
    progress = get_fetch_progress(session_id)
    if not progress:
        return JsonResponse({"error": "Session not found"}, status=404)
    return JsonResponse(progress, status=200)


@csrf_exempt
@require_POST
def abort_fetch(request, session_id):
    if not get_fetch_job(session_id):
        return JsonResponse({"error": "Session not found"}, status=404)
    abort_session(session_id)
    wait_for_abort(session_id)
    return JsonResponse({"success": True}, status=200)


@require_GET
def fetch_status(request):
    clear_stale_fetch_guard()
    running = get_running_job()
    if running:
        progress = get_fetch_progress(running.session_id)
        return JsonResponse({
            "session_id": running.session_id,
            "status": running.status,
            "created_by": running.created_by,
            "progress": progress,
            "next_fetch_at": get_next_fetch_at(),
            "current_time": time.time(),
        })
    pending = get_pending_job()
    if pending:
        progress = get_fetch_progress(pending.session_id)
        return JsonResponse({
            "session_id": pending.session_id,
            "status": pending.status,
            "created_by": pending.created_by,
            "progress": progress,
            "next_fetch_at": get_next_fetch_at(),
            "current_time": time.time(),
        })
    last_sid = get_last_session_id()
    last_progress = get_fetch_progress(last_sid) if last_sid else None

    return JsonResponse({
        "session_id": None, 
        "status": "idle",
        "progress": last_progress,
        "next_fetch_at": get_next_fetch_at(),
        "current_time": time.time(),
    })


def enqueue_startup_fetch(created_by="foreground"):
    if os.environ.get("WFMARKET_STARTUP_FETCH_READY") == "1":
        return
    os.environ["WFMARKET_STARTUP_FETCH_READY"] = "1"
    
    job = build_fetch_job(created_by=created_by)
    enqueue_job(job, pending=False)