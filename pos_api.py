from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from pos_config import POSConfig
import logging

app = FastAPI()
config = POSConfig()

serial_bridge = None

class PaymentRequest(BaseModel):
    amount: float
    method: str

class PaymentStatusResponse(BaseModel):
    status: str
    detail: Optional[str] = None

class VMCMessage(BaseModel):
    raw: str

payments = {}

@app.post("/payment/start", response_model=PaymentStatusResponse)
def start_payment(req: PaymentRequest):
    if req.method not in config.get("accepted_payments"):
        raise HTTPException(status_code=400, detail="Unsupported payment method")
    payment_id = f"pay_{len(payments)+1}"
    payments[payment_id] = {"status": "pending", "amount": req.amount, "method": req.method}
    logging.info(f"Payment started: {payment_id}")
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

@app.post("/pos/response")
async def pos_response(request: Request):
    data = await request.body()
    if serial_bridge:
        serial_bridge.send_to_vmc(data)
        logging.info("POS response forwarded to VMC")
    return {"status": "forwarded"}

@app.post("/vmc/message")
def vmc_message(msg: VMCMessage):
    logging.info(f"Received from VMC (via SerialBridge): {msg.raw}")
    return {"status": "received"}
@app.post("/vmc/message")
def vmc_message(msg: VMCMessage):
    # This endpoint receives messages from VMC via SerialBridge
    # Here you can parse, log, and forward to POS or update session/payment status
    logging.info(f"Received from VMC (via SerialBridge): {msg.raw}")
    # Example: update payment status or notify POS
    return {"status": "received"}
