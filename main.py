# Flask version of your Smart Lock API using Flask-MQTT

from flask_cors import CORS
import os
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from flask import Flask, request, jsonify
from flask_apscheduler import APScheduler
from flask_jwt_extended import (
    JWTManager, create_access_token, get_jwt_identity,
    jwt_required
)
from flask_mqtt import Mqtt
from dotenv import load_dotenv
import pymongo
from bson import ObjectId


# === App Setup ===
app = Flask(__name__)
load_dotenv()
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# === Configuration ===
JWT_SECRET = "supersecretjwtkey"
JWT_ALGORITHM = "HS256"
MQTT_COMMAND_TOPIC = "smartlock/commands"
MQTT_STATUS_TOPIC = "smartlock/status"
MQTT_BROKER = "broker.emqx.io"

app.config['JWT_SECRET_KEY'] = JWT_SECRET
app.config['MQTT_BROKER_URL'] = MQTT_BROKER
app.config['MQTT_BROKER_PORT'] = 1883
app.config['MQTT_USERNAME'] = 'emqx'
app.config['MQTT_PASSWORD'] = 'public'
app.config['MQTT_KEEPALIVE'] = 60
app.config['MQTT_TLS_ENABLED'] = False

jwt_manager = JWTManager(app)
mqtt = Mqtt(app)

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

try:
    client = pymongo.MongoClient(uri)
    db = client.smartlockdb
    users_collection = db.users
    locks_collection = db.locks
    logs_collection = db.logs
except Exception as e:
    logger.error("❌ Failed to connect to MongoDB:", e)


# === MQTT Topics ===
MQTT_COMMAND_TOPIC = "smartlock/commands"
MQTT_STATUS_TOPIC = "smartlock/status"


# === Utilities ===

def serialize_log(log):
    log["_id"] = str(log["_id"])
    log["timestamp"] = log["timestamp"].isoformat() if "timestamp" in log else None
    log["device_id"] = log.get("device_id", "Unknown")
    log["status"] = log.get("status", log.get("action", "Unknown"))  # fallback to action
    log["state"] = log.get("state", "Unknown")  # Always have state, even if missing
    return log

def is_device_online(lock):
    last_seen = lock.get("last_seen", datetime.utcnow() - timedelta(days=1))
    delta = datetime.utcnow() - last_seen
    return delta.total_seconds() < 35

# === MQTT Callbacks ===
@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    mqtt.subscribe(MQTT_STATUS_TOPIC)
    logger.info("✅ MQTT connected and subscribed to status topic")

# === In-memory device tracking ===
device_last_seen = {}
device_last_state = {}

OFFLINE_THRESHOLD_SECONDS = 10

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    try:
        payload = message.payload.decode()
        data = json.loads(payload)
        device = data.get("device")
        status = data.get("status")
        state = data.get("state")
        now = datetime.utcnow()

        lock = locks_collection.find_one({"_id": device})
        if lock:

            last_seen = device_last_seen.get(device)
            last_known_state = device_last_state.get(device, "Unknown")

            if last_seen:
                delta = (now - last_seen).total_seconds()
                if delta > OFFLINE_THRESHOLD_SECONDS:
                    # Device was "offline" for more than threshold
                    logs_collection.insert_one({
                        "timestamp": last_seen + timedelta(seconds=OFFLINE_THRESHOLD_SECONDS),
                        "device_id": device,
                        "status": "Offline",
                        "state": last_known_state
                    })
                    logger.info(f"⚠️ OFFLINE logged for {device} (gap of {delta:.1f} sec)")

            # Update lock's database entry
            locks_collection.update_one(
                {"_id": device},
                {"$set": {"status": status, "state": state, "last_seen": now}}
            )
            logs_collection.insert_one({
                "timestamp": now,
                "device_id": device,
                "status": status,
                "state": state
            })

            # Update in-memory tracker
            device_last_seen[device] = now
            device_last_state[device] = state

            logger.info(f"✅ Status updated for {device}: {status} - {state}")

        else:
            logger.warning(f"Unknown device: {device}")
    except Exception as e:
        logger.error(f"Error parsing MQTT message: {e}")

# === Auth Routes ===
@app.route("/auth/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        print("Incoming registration data:", data)  # ✅ Log request

        if not all(k in data for k in ("email", "username", "password")):
            return jsonify({"error": "Missing required fields"}), 400

        if users_collection.find_one({"username": data["username"]}):
            return jsonify({"error": "Username already exists"}), 400

        users_collection.insert_one({
            "email": data["email"],
            "username": data["username"],
            "password": data["password"],
            "is_admin": False
        })

        return jsonify({"message": "User created successfully"})
    
    except Exception as e:
        print("❌ Error during registration:", str(e))  # ✅ Log the error
        return jsonify({"error": "Internal server error"}), 500

def check_for_offline_devices():
    now = datetime.utcnow()

    for device_id, last_seen_time in device_last_seen.items():
        delta = (now - last_seen_time).total_seconds()

        if delta > OFFLINE_THRESHOLD_SECONDS:
            last_log = logs_collection.find_one(
                {"device_id": device_id},
                sort=[("timestamp", pymongo.DESCENDING)]
            )

            if not last_log or last_log.get("status") != "Offline":
                last_known_state = device_last_state.get(device_id, "Unknown")
                logs_collection.insert_one({
                    "timestamp": last_seen_time + timedelta(seconds=OFFLINE_THRESHOLD_SECONDS),
                    "device_id": device_id,
                    "status": "Offline",
                    "state": last_known_state
                })
                logger.info(f"🚨 OFFLINE log created by checker for {device_id}")


scheduler.add_job(
    id='offline_checker',
    func=check_for_offline_devices,
    trigger='interval',
    seconds=10,
    replace_existing=True
)


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

# === Lock Routes ===
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
        "state": "Unknown",
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

    now = datetime.utcnow()
    last_seen = lock.get("last_seen", now - timedelta(days=1))
    delta = (now - last_seen).total_seconds()

    # If last seen more than threshold ago, mark as unavailable
    is_online = delta < OFFLINE_THRESHOLD_SECONDS
    connection_status = "Available" if is_online else "Unavailable"

    # Optional: If you want to update in DB too
    locks_collection.update_one(
        {"_id": device_id},
        {"$set": {"state": connection_status}}
    )

    return jsonify({
        "device_id": device_id,
        "connection_status": connection_status,  # Available/Unavailable
        "device_status": lock.get("status", "Unknown"),  # Locked/Unlocked/etc
        "device_state": lock.get("state", "Unknown"),  # Optional, if you use another 'state' concept
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
    if not is_device_online(lock):
        return jsonify({"error": "Device is offline, cannot send LOCK command"}), 503

    payload = {"command": "LOCK", "device": device_id}
    mqtt.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one({
        "timestamp": datetime.utcnow(),
        "action": "LOCK",
        "device_id": device_id,
        "user_id": current_user
    })
    return jsonify({"status": f"LOCK command sent to {device_id}"})

@app.route("/api/unlock", methods=["POST"])
@jwt_required()
def unlock_door():
    current_user = get_jwt_identity()
    device_id = request.args.get("device_id")
    lock = locks_collection.find_one({"_id": device_id, "owner": current_user})
    if not lock:
        return jsonify({"error": "Access denied to this lock"}), 403
    if not is_device_online(lock):
        return jsonify({"error": "Device is offline, cannot send UNLOCK command"}), 503

    payload = {"command": "UNLOCK", "device": device_id}
    mqtt.publish(MQTT_COMMAND_TOPIC, json.dumps(payload))
    logs_collection.insert_one({
        "timestamp": datetime.utcnow(),
        "action": "UNLOCK",
        "device_id": device_id,
        "user_id": current_user
    })
    return jsonify({"status": f"UNLOCK command sent to {device_id}"})

@app.route("/api/logs", methods=["GET"])
@jwt_required()
def get_logs():
    current_user = get_jwt_identity()
    logs = list(logs_collection.find({"device_id": {"$exists": True}}))
    serialized_logs = [serialize_log(log) for log in logs]
    return jsonify(serialized_logs)


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

# === Run Flask App ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)








