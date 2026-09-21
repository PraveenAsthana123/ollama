import threading
import time

import scripts.gpu_scheduler as gpu_scheduler


def _client():
    client = gpu_scheduler._client()
    client.delete(gpu_scheduler.LOCK_KEY)
    client.delete(gpu_scheduler.QUEUE_KEY)
    return client


def test_single_job_acquires_and_releases_cleanly():
    client = _client()
    with gpu_scheduler.acquire(0, job_id="solo", client=client) as lease:
        assert lease["wait_ms"] >= 0
        assert client.get(gpu_scheduler.LOCK_KEY).decode() == "solo"
    assert client.get(gpu_scheduler.LOCK_KEY) is None
    assert gpu_scheduler.queue_depth(client) == 0


def test_two_concurrent_jobs_never_hold_the_lease_simultaneously():
    client = _client()
    overlap_detected = threading.Event()
    holder = {"current": None}
    lock = threading.Lock()

    def worker(job_id, priority, hold_seconds):
        with gpu_scheduler.acquire(priority, job_id=job_id, client=gpu_scheduler._client()) as _:
            with lock:
                if holder["current"] is not None:
                    overlap_detected.set()
                holder["current"] = job_id
            time.sleep(hold_seconds)
            with lock:
                holder["current"] = None

    threads = [
        threading.Thread(target=worker, args=("a", 0, 0.15)),
        threading.Thread(target=worker, args=("b", 0, 0.15)),
        threading.Thread(target=worker, args=("c", 0, 0.15)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not overlap_detected.is_set()
    assert gpu_scheduler.queue_depth(client) == 0


def test_higher_priority_job_served_before_lower_priority_even_if_queued_later():
    client = _client()
    order = []
    order_lock = threading.Lock()
    started = threading.Event()

    def hog():
        with gpu_scheduler.acquire(5, job_id="hog", client=gpu_scheduler._client()):
            started.set()
            time.sleep(0.3)

    hog_thread = threading.Thread(target=hog)
    hog_thread.start()
    started.wait(timeout=2)
    time.sleep(0.02)  # ensure the hog is confirmed holding the lease first

    def contender(job_id, priority, delay):
        time.sleep(delay)
        with gpu_scheduler.acquire(priority, job_id=job_id, client=gpu_scheduler._client()):
            with order_lock:
                order.append(job_id)

    # "batch" queues first but is low priority; "interactive" queues slightly
    # later but must still be served first once the hog releases.
    batch_thread = threading.Thread(target=contender, args=("batch_job", 5, 0.05))
    interactive_thread = threading.Thread(target=contender, args=("interactive_job", 0, 0.08))
    batch_thread.start()
    interactive_thread.start()

    hog_thread.join(timeout=5)
    batch_thread.join(timeout=5)
    interactive_thread.join(timeout=5)

    assert order == ["interactive_job", "batch_job"]


def test_timeout_raises_and_does_not_leave_a_stuck_queue_entry():
    client = _client()
    started = threading.Event()

    def hog():
        with gpu_scheduler.acquire(0, job_id="long_hog", client=gpu_scheduler._client()):
            started.set()
            time.sleep(0.5)

    hog_thread = threading.Thread(target=hog)
    hog_thread.start()
    started.wait(timeout=2)

    raised = False
    try:
        with gpu_scheduler.acquire(0, job_id="impatient", timeout=0.1, client=gpu_scheduler._client()):
            pass
    except TimeoutError:
        raised = True

    hog_thread.join(timeout=5)
    assert raised
    assert "impatient" not in [e["job_id"] for e in gpu_scheduler.queue_snapshot(client)]
