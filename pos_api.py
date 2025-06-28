from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from pos_config import POSConfig
from pos_messages import parse_response, dispatch_response, build_transaction
import logging
from pos_tcp_client import POSTcpClient

app = FastAPI()
config = POSConfig()
tcp_client = POSTcpClient(config.get("esocket_host"), config.get("esocket_port"))

class PaymentRequest(BaseModel):
    amount: float
    method: str

class PaymentStatusResponse(BaseModel):
    status: str
    detail: Optional[str] = None

payments = {}

@app.post("/payment/start", response_model=PaymentStatusResponse)
def start_payment(req: PaymentRequest):
    if req.method not in config.get("accepted_payments"):
        raise HTTPException(status_code=400, detail="Unsupported payment method")
    payment_id = f"pay_{len(payments)+1}"
    payments[payment_id] = {"status": "pending", "amount": req.amount, "method": req.method}
    logging.info(f"Payment started: {payment_id}")

    # Build and send transaction message over TCP
    message = build_transaction(req.amount, config.get("esocket_terminal_id"), payment_id, config.get("currency")[0])
    tcp_client.send_message(message)
    response = tcp_client.receive_message()
    parsed = parse_response(response)
    dispatch_response(parsed)
    return PaymentStatusResponse(status="pending", detail=f"Payment started with id {payment_id}")

@app.get("/payment/status/{payment_id}", response_model=PaymentStatusResponse)
def payment_status(payment_id: str):
    payment = payments.get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return PaymentStatusResponse(status=payment["status"])

@app.post("/payment/complete/{payment_id}", response_model=PaymentStatusResponse)
def complete_payment(payment_id: str):
    payment = payments.get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment["status"] = "completed"
    logging.info(f"Payment completed: {payment_id}")
    return PaymentStatusResponse(status="completed", detail="Payment completed successfully")
