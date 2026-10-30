import secrets
import threading
import time

SESSION_TIMEOUT = 3600
SESSION_LOCK = threading.RLock()
SESSIONS = {}


def create_session():
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = time.monotonic()
    return token


def validate_session(token):
    if not token:
        return False

    now = time.monotonic()

    with SESSION_LOCK:
        last_activity = SESSIONS.get(token)
        if last_activity is None:
            return False

        if now - last_activity >= SESSION_TIMEOUT:
            SESSIONS.pop(token, None)
            return False

        SESSIONS[token] = now
        return True


def destroy_session(token):
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


def destroy_all_sessions():
    with SESSION_LOCK:
        SESSIONS.clear()

LOGIN_WINDOW = 900
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURES = {}


def login_allowed(ip):
    now = time.monotonic()
    with SESSION_LOCK:
        failures = [
            t for t in LOGIN_FAILURES.get(ip, [])
            if now - t < LOGIN_WINDOW
        ]
        if failures:
            LOGIN_FAILURES[ip] = failures
        else:
            LOGIN_FAILURES.pop(ip, None)
        return len(failures) < LOGIN_MAX_FAILURES


def record_login_failure(ip):
    now = time.monotonic()
    with SESSION_LOCK:
        failures = [
            t for t in LOGIN_FAILURES.get(ip, [])
            if now - t < LOGIN_WINDOW
        ]
        failures.append(now)
        LOGIN_FAILURES[ip] = failures


def clear_login_failures(ip):
    with SESSION_LOCK:
        LOGIN_FAILURES.pop(ip, None)
