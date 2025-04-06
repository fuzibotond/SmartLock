import asyncio
import json
import os
from datetime import datetime, timedelta

import jwt
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from gmqtt import Client as MQTTClient
from pydantic import BaseModel
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

app = FastAPI()


# Create a new client and connect to the server
client = MongoClient(os.getenv("MONGO_URI"), server_api=ServerApi('1'))

# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
db = client.smartlockdb
users_collection = db.users
locks_collection = db.locks
logs_collection = db.logs

# === Configuration ===
API_KEY = "mysecureapikey"
JWT_SECRET = "supersecretjwtkey"
JWT_ALGORITHM = "HS256"
MQTT_COMMAND_TOPIC = "smartlock/commands"
MQTT_STATUS_TOPIC = "smartlock/status"
MQTT_BROKER = "test.mosquitto.org"

mqtt_client = MQTTClient(MQTT_BROKER)


# === Models ===
class UserCredentials(BaseModel):
    username: str
    password: str


class LockRegistration(BaseModel):
    device_id: str
    name: str

# Status Model
class StatusUpdate(BaseModel):
    device: str
    status: str


# ✅ Authenticate Requests
def authenticate(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")


# === Authentication Helpers ===
def create_token(username: str):
    payload = {"sub": username, "exp": datetime.utcnow() + timedelta(days=1)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except jwt:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing or invalid")
    token = auth_header.split(" ")[1]
    return decode_token(token)


# === MQTT Handling ===
def on_message(client, topic, payload, qos, properties):
    try:
        data = json.loads(payload.decode())
        device = data.get("device")
        status = data.get("status")
        lock = locks_collection.find_one({"_id": device})
        if lock:
            locks_collection.update_one({"_id": device}, {"$set": {"status": status, "last_seen": datetime.utcnow()}})
            logs_collection.insert_one({"timestamp": datetime.utcnow(), "device_id": device, "status": status})
            print(f"✅ Status update from {device}: {status}")
        else:
            print(f"⚠️ Unknown device status received: {device}")
    except Exception as e:
        print(f"❌ Error in MQTT message: {e}")


mqtt_client.on_message = on_message


@app.on_event("startup")
async def connect_mqtt():
    connected = False
    retries = 0
    while not connected and retries < 5:
        try:
            await mqtt_client.connect(MQTT_BROKER)
            mqtt_client.subscribe(MQTT_STATUS_TOPIC)
            connected = True
        except Exception as e:
            print(f"❌ MQTT connection failed: {e}")
            retries += 1
            await asyncio.sleep(5)


## === API Endpoints ===
@app.post("/auth/signup")
def signup(credentials: UserCredentials):
    if users_collection.find_one({"username": credentials.username}):
        raise HTTPException(status_code=400, detail="Username already exists")
    users_collection.insert_one({"username": credentials.username, "password": credentials.password, "is_admin": False})
    return {"message": "User registered"}


@app.post("/auth/login")
def login(credentials: UserCredentials):
    user = users_collection.find_one({"username": credentials.username})
    if not user or user["password"] != credentials.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(credentials.username)
    return {"token": token}


@app.post("/locks/register")
def register_lock(data: LockRegistration, user: str = Depends(get_current_user)):
    if locks_collection.find_one({"_id": data.device_id}):
        raise HTTPException(status_code=400, detail="Device already registered")
    locks_collection.insert_one({
        "_id": data.device_id,
        "name": data.name,
        "owner": user,
        "status": "Unknown",
        "state": "Available",
        "last_seen": datetime.utcnow(),
        "issue": None
    })
    return {"message": f"Lock {data.name} registered"}


@app.get("/locks")
def list_locks(user: str = Depends(get_current_user)):
    return list(locks_collection.find({"owner": user}))


@app.get("/locks/{device_id}/status")
def get_lock_status(device_id: str, user: str = Depends(get_current_user)):
    lock = locks_collection.find_one({"_id": device_id, "owner": user})
    if not lock:
        raise HTTPException(status_code=404, detail="Lock not found or not yours")
    delta = datetime.utcnow() - lock.get("last_seen", datetime.utcnow())
    state = "Available" if delta.total_seconds() < 35 else "Unavailable"
    locks_collection.update_one({"_id": device_id}, {"$set": {"state": state}})
    return {
        "status": lock["status"],
        "state": state,
        "issue": lock.get("issue")
    }


@app.post("/api/lock")
def lock_door(request: Request):
    user = get_current_user(request)
    device_id = request.query_params.get("device_id")
    lock = locks_collection.find_one({"_id": device_id, "owner": user})
    if not lock:
        raise HTTPException(status_code=403, detail="Access denied to this lock")
    payload = {"command": "LOCK", "device": device_id, "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one(
        {"timestamp": datetime.utcnow(), "action": "LOCK", "device_id": device_id, "user_id": user})
    return {"status": f"LOCK command sent to {device_id}"}


@app.post("/api/unlock")
def unlock_door(request: Request):
    user = get_current_user(request)
    device_id = request.query_params.get("device_id")
    lock = locks_collection.find_one({"_id": device_id, "owner": user})
    if not lock:
        raise HTTPException(status_code=403, detail="Access denied to this lock")
    payload = {"command": "UNLOCK", "device": device_id, "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one(
        {"timestamp": datetime.utcnow(), "action": "UNLOCK", "device_id": device_id, "user_id": user})
    return {"status": f"UNLOCK command sent to {device_id}"}


@app.post("/api/esp32/status")
def receive_status(status_update: StatusUpdate):
    if not locks_collection.find_one({"_id": status_update.device}):
        raise HTTPException(status_code=404, detail="Device not registered")
    locks_collection.update_one(
        {"_id": status_update.device},
        {"$set": {"status": status_update.status, "last_seen": datetime.utcnow()}}
    )
    logs_collection.insert_one(
        {"timestamp": datetime.utcnow(), "device_id": status_update.device, "status": status_update.status})
    return {"message": "Status received"}


@app.get("/api/logs")
def get_logs(user: str = Depends(get_current_user)):
    return list(logs_collection.find({"user_id": user}))


@app.put("/locks/{device_id}/reassign")
def reassign_lock(device_id: str, new_owner: str, user: str = Depends(get_current_user)):
    me = users_collection.find_one({"username": user})
    if not me or not me.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    new_user = users_collection.find_one({"username": new_owner})
    if not new_user:
        raise HTTPException(status_code=404, detail="New owner not found")
    result = locks_collection.update_one({"_id": device_id}, {"$set": {"owner": new_owner}})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Lock not found")
    return {"message": f"Lock {device_id} reassigned to {new_owner}"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
