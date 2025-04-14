import paho.mqtt.publish as publish
import json

payload = {
    "device": "device-1",
    "status": "Offline",
    "api_key": "mysecureapikey"
}

publish.single("smartlock/status", json.dumps(payload), hostname="test.mosquitto.org", port=1883)
