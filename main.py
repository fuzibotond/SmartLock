# Flask version of your Smart Lock API

import os
import json
import logging
from datetime import datetime
from urllib.parse import quote_plus

from flask import Flask, request, jsonify
from flask_jwt_extended import (
    JWTManager, create_access_token, get_jwt_identity,
    jwt_required
)
from dotenv import load_dotenv
from gmqtt import Client as MQTTClient
import asyncio
import pymongo

# === App Setup ===
app = Flask(__name__)
load_dotenv()

# === Configuration ===
API_KEY = "mysecureapikey"
JWT_SECRET = "supersecretjwtkey"
JWT_ALGORITHM = "HS256"
MQTT_COMMAND_TOPIC = "smartlock/commands"
MQTT_STATUS_TOPIC = "smartlock/status"
MQTT_BROKER = "test.mosquitto.org"

app.config["JWT_SECRET_KEY"] = JWT_SECRET
jwt_manager = JWTManager(app)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# === MongoDB Setup ===
username = quote_plus(os.getenv('MONGODB_URI_USER'))
password = quote_plus(os.getenv('MONGODB_URI_PASSWORD'))
uri = f'mongodb+srv://{username}:{password}@smartlock.pyl9zn8.mongodb.net/?appName=SmartLock'
client = pymongo.MongoClient(uri)
db = client.smartlockdb
users_collection = db.users
locks_collection = db.locks
logs_collection = db.logs

# === MQTT ===
mqtt_client = MQTTClient("smartlock-server")


async def start_mqtt():
    try:
        await mqtt_client.connect(MQTT_BROKER)
        mqtt_client.subscribe(MQTT_STATUS_TOPIC)
        logger.info("✅ MQTT connected and subscribed to status topic")
    except Exception as e:
        logger.error(f"❌ MQTT connection failed: {e}")


mqtt_client.on_message = lambda client, topic, payload, qos, properties: handle_mqtt_message(topic, payload)


def handle_mqtt_message(topic, payload):
    logger.info(f"MQTT Received on {topic}: {payload}")
    try:
        data = json.loads(payload.decode())
        device = data.get("device")
        status = data.get("status")
        key = data.get("api_key")
        if key != API_KEY:
            logger.warning("Invalid API key in MQTT message")
            return

        lock = locks_collection.find_one({"_id": device})
        if lock:
            locks_collection.update_one({"_id": device}, {"$set": {"status": status, "last_seen": datetime.utcnow()}})
            logs_collection.insert_one({"timestamp": datetime.utcnow(), "device_id": device, "status": status})
            logger.info(f"Status updated for {device}: {status}")
        else:
            logger.warning(f"Unknown device: {device}")

    except Exception as e:
        logger.error(f"Error parsing MQTT message: {e}")


# === Auth ===
@app.route("/auth/signup", methods=["POST"])
def signup():
    data = request.get_json()
    if users_collection.find_one({"username": data["username"]}):
        return jsonify({"error": "Username already exists"}), 400
    users_collection.insert_one({"username": data["username"], "password": data["password"], "is_admin": False})
    return jsonify({"message": "User registered"})


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    user = users_collection.find_one({"username": data["username"]})
    if not user or user["password"] != data["password"]:
        return jsonify({"error": "Invalid credentials"}), 401
    token = create_access_token(identity=data["username"])
    return jsonify({"token": token})


# === Locks ===
@app.route("/locks/register", methods=["POST"])
@jwt_required()
def register_lock():
    data = request.get_json()
    current_user = get_jwt_identity()
    if locks_collection.find_one({"_id": data["device_id"]}):
        return jsonify({"error": "Device already registered"}), 400
    locks_collection.insert_one({
        "_id": data["device_id"],
        "name": data["name"],
        "owner": current_user,
        "status": "Unknown",
        "state": "Available",
        "last_seen": datetime.utcnow(),
        "issue": None
    })
    return jsonify({"message": "Lock registered"})


@app.route("/locks", methods=["GET"])
@jwt_required()
def list_locks():
    current_user = get_jwt_identity()
    locks = list(locks_collection.find({"owner": current_user}))
    return jsonify(locks)


@app.route("/locks/<device_id>/status", methods=["GET"])
@jwt_required()
def get_lock_status(device_id):
    current_user = get_jwt_identity()
    lock = locks_collection.find_one({"_id": device_id, "owner": current_user})
    if not lock:
        return jsonify({"error": "Lock not found or not yours"}), 404
    delta = datetime.utcnow() - lock.get("last_seen", datetime.utcnow())
    state = "Available" if delta.total_seconds() < 35 else "Unavailable"
    locks_collection.update_one({"_id": device_id}, {"$set": {"state": state}})
    return jsonify({
        "status": lock["status"],
        "state": state,
        "issue": lock.get("issue")
    })


@app.route("/api/lock", methods=["POST"])
@jwt_required()
def lock_door():
    current_user = get_jwt_identity()
    device_id = request.args.get("device_id")
    lock = locks_collection.find_one({"_id": device_id, "owner": current_user})
    if not lock:
        return jsonify({"error": "Access denied to this lock"}), 403
    payload = {"command": "LOCK", "device": device_id, "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one(
        {"timestamp": datetime.utcnow(), "action": "LOCK", "device_id": device_id, "user_id": current_user})
    return jsonify({"status": f"LOCK command sent to {device_id}"})


@app.route("/api/unlock", methods=["POST"])
@jwt_required()
def unlock_door():
    current_user = get_jwt_identity()
    device_id = request.args.get("device_id")
    lock = locks_collection.find_one({"_id": device_id, "owner": current_user})
    if not lock:
        return jsonify({"error": "Access denied to this lock"}), 403
    payload = {"command": "UNLOCK", "device": device_id, "api_key": API_KEY}
    mqtt_client.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one(
        {"timestamp": datetime.utcnow(), "action": "UNLOCK", "device_id": device_id, "user_id": current_user})
    return jsonify({"status": f"UNLOCK command sent to {device_id}"})


@app.route("/api/logs", methods=["GET"])
@jwt_required()
def get_logs():
    current_user = get_jwt_identity()
    logs = list(logs_collection.find({"user_id": current_user}))
    return jsonify(logs)


@app.route("/locks/<device_id>/reassign", methods=["PUT"])
@jwt_required()
def reassign_lock(device_id):
    current_user = get_jwt_identity()
    new_owner = request.args.get("new_owner")
    user = users_collection.find_one({"username": current_user})
    if not user.get("is_admin"):
        return jsonify({"error": "Admin access required"}), 403
    new_user = users_collection.find_one({"username": new_owner})
    if not new_user:
        return jsonify({"error": "New owner not found"}), 404
    result = locks_collection.update_one({"_id": device_id}, {"$set": {"owner": new_owner}})
    if result.modified_count == 0:
        return jsonify({"error": "Lock not found"}), 404
    return jsonify({"message": f"Lock {device_id} reassigned to {new_owner}"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    asyncio.run(start_mqtt())
    app.run(host="0.0.0.0", port=port)
