import json
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
import requests
from datetime import datetime
from gmqtt import Client as MQTTClient


app = FastAPI()

API_KEY = "mysecureapikey"
logs = []
current_status = "Unknown"
MQTT_COMMAND_TOPIC = "smartlock/commands"
MQTT_STATUS_TOPIC = "smartlock/status"
MQTT_BROKER = "broker.hivemq.com"  # or your own MQTT broker

mqtt_client = MQTTClient("fastapi-server")



# ✅ Status Model
class StatusUpdate(BaseModel):
    device: str
    status: str


# ✅ Authenticate Requests
def authenticate(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")


def on_message(client, topic, payload, qos, properties):
    global current_status
    try:
        data = json.loads(payload.decode())
        if data.get("api_key") != API_KEY:
            print("❌ Invalid API Key in MQTT message")
            return
        status = data.get("status")
        device = data.get("device", "ESP32")
        logs.append({"timestamp": datetime.now(), "device": device, "status": status})
        current_status = status
        print(f"✅ Status update from {device}: {status}")
    except Exception as e:
        print(f"Error handling MQTT message: {e}")

mqtt_client.on_message = on_message

@app.on_event("startup")
async def connect_mqtt():
    mqtt_client.set_auth_credentials("","")  # optional username/password
    await mqtt_client.connect(MQTT_BROKER)
    mqtt_client.subscribe(MQTT_STATUS_TOPIC)


# ✅ API to Lock the Door
@app.post("/api/lock")
def lock_door(request: Request):
    authenticate(request.headers.get("Authorization"))
    payload = {"command": "LOCK", "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs.append({"timestamp": datetime.now(), "action": "LOCK"})
    return {"status": "LOCK command sent"}


# ✅ API to Unlock the Door
@app.post("/api/unlock")
def unlock_door(request: Request):
    authenticate(request.headers.get("Authorization"))
    payload = {"command": "UNLOCK", "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs.append({"timestamp": datetime.now(), "action": "UNLOCK"})
    return {"status": "UNLOCK command sent"}


# ✅ API to Receive Status from ESP32
@app.get("/api/status")
def get_status(request: Request):
    authenticate(request.headers.get("Authorization"))
    return {"status": current_status}


# ✅ API to Get Logs
@app.get("/api/logs")
def get_logs(request: Request):
    authenticate(request.headers.get("Authorization"))
    return {"logs": logs}


import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

