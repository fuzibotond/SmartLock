from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
import requests
from datetime import datetime

app = FastAPI()

ESP32_IP = "http://10.10.0.2"  # Change this to your ESP32's IP
API_KEY = "mysecureapikey"
logs = []


# ✅ Status Model
class StatusUpdate(BaseModel):
    device: str
    status: str


# ✅ Authenticate Requests
def authenticate(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")


# ✅ API for ESP32 to Get Commands
@app.get("/api/esp32/command")
def get_command():
    # This should return either "LOCK" or "UNLOCK"
    return "LOCK"  # Change to "UNLOCK" to test unlocking


# ✅ API to Lock the Door
@app.post("/api/lock")
def lock_door(request: Request):
    authenticate(request.headers.get('Authorization'))

    try:
        response = requests.get(f"{ESP32_IP}/lock")
        logs.append({"timestamp": datetime.now(), "action": "LOCK"})
        return {"status": "Door Locked", "esp_response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ API to Unlock the Door
@app.post("/api/unlock")
def unlock_door(request: Request):
    authenticate(request.headers.get('Authorization'))

    try:
        response = requests.get(f"{ESP32_IP}/unlock")
        logs.append({"timestamp": datetime.now(), "action": "UNLOCK"})
        return {"status": "Door Unlocked", "esp_response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ API to Receive Status from ESP32
@app.post("/api/esp32/status")
def receive_status(status_update: StatusUpdate, request: Request):
    authenticate(request.headers.get('Authorization'))

    logs.append({"timestamp": datetime.now(), "device": status_update.device, "status": status_update.status})
    return {"message": "Status received", "logs": logs}


# ✅ API to Get Logs
@app.get("/api/logs")
def get_logs():

    return {"logs": "csecs"}


import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

