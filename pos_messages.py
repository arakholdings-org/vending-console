import json
import logging
import threading
import queue
import shelve  # For simple persistent storage
import time

# High-level POS message builders using JSON (Ruby eSocket style)

def build_init(terminal_id):
    return json.dumps({
        "type": "init",
        "terminal_id": terminal_id
    })

def build_close(terminal_id):
    return json.dumps({
        "type": "close",
        "terminal_id": terminal_id
    })

def build_transaction(amount, terminal_id, transaction_id, currency="USD"):
    return json.dumps({
        "type": "transaction",
        "amount": amount,
        "terminal_id": terminal_id,
        "transaction_id": transaction_id,
        "currency": currency
    })

def build_reversal(transaction_id, terminal_id):
    return json.dumps({
        "type": "reversal",
        "transaction_id": transaction_id,
        "terminal_id": terminal_id
    })

def build_callback(event_id, terminal_id, event_data=""):
    return json.dumps({
        "type": "callback",
        "event_id": event_id,
        "terminal_id": terminal_id,
        "event_data": event_data
    })

def parse_response(data: str):
    try:
        response = json.loads(data)
        logging.info(f"Parsed POS response: {response}")
        return response
    except Exception as e:
        logging.error(f"Failed to parse POS response: {e}")
        return None

# Message queue and persistent session management
message_queue = queue.Queue()
SESSION_DB = "session_store.db"

def session_update(transaction_id, status, details=None):
    """Persist session data using shelve (simple file-based DB)."""
    with shelve.open(SESSION_DB) as db:
        db[transaction_id] = {
            "status": status,
            "details": details,
            "updated_at": time.time()
        }
    logging.info(f"Session updated (persistent): {transaction_id} -> {status}")

def get_session(transaction_id):
    """Retrieve session data from persistent store."""
    with shelve.open(SESSION_DB) as db:
        return db.get(transaction_id)

def enqueue_message(message):
    message_queue.put(message)
    logging.info("Message enqueued.")

def dequeue_message(timeout=1):
    try:
        return message_queue.get(timeout=timeout)
    except queue.Empty:
        return None

# Example: notify_user can be expanded to push to a UI/websocket
def notify_user(message, user_id=None):
    logging.info(f"User notification: {message}")
    # Example: If using FastAPI WebSockets, broadcast here
    # from fastapi_websocket_pubsub import PubSubEndpoint
    # endpoint = PubSubEndpoint()
    # endpoint.publish(["user", user_id or "all"], {"msg": message})

def advanced_dispatch(response: dict):
    resp_type = response.get("type")
    status = response.get("status")
    transaction_id = response.get("transaction_id")

    if resp_type == "transaction":
        if status == "success":
            session_update(transaction_id, "success", response)
            notify_user("Transaction successful.")
        elif status == "failed":
            session_update(transaction_id, "failed", response)
            notify_user("Transaction failed.")
    elif resp_type == "init" and status == "ok":
        logging.info("Terminal initialized.")
    elif resp_type == "reversal" and status == "success":
        session_update(transaction_id, "reversed", response)
        notify_user("Reversal successful.")
    elif resp_type == "callback":
        logging.info(f"Callback event: {response.get('event_id')}")
    elif resp_type == "close" and status == "ok":
        logging.info("Terminal closed.")
    else:
        logging.info(f"Unhandled POS response: {response}")

def message_worker(tcp_client):
    while True:
        message = dequeue_message()
        if message:
            try:
                tcp_client.send_message(message)
                response = tcp_client.receive_message()
                parsed = parse_response(response)
                if parsed:
                    advanced_dispatch(parsed)
            except Exception as e:
                logging.error(f"Error in message_worker: {e}")

def start_message_worker(tcp_client):
    thread = threading.Thread(target=message_worker, args=(tcp_client,), daemon=True)
    thread.start()
    logging.info("Message worker thread started.")
