# 🔐 Smart Lock System – Overview

## 🎯 Purpose
A trustworthy IoT system that enables users to register, manage, and control smart locks through a mobile app interface. Physical lock actions and real-time status reporting are handled by ESP32 devices, while the backend server ensures secure access, monitoring, and fault detection.

---

## 🧩 System Components

### 1. 📱 Mobile App (Client)
- End users can:
  - Sign up / Sign in
  - Lock or unlock smart locks
  - View lock status (Locked / Unlocked, Online / Offline)
  - Monitor diagnostic issues (e.g., no power)
  - Token-based authenticated interaction with backend
- Built and tested using exported Postman collections

### 2. 🌐 API Server (Flask + MongoDB + MQTT)
- Developed in **Flask**, not FastAPI
- JWT-based authentication for secure access
- MongoDB for persistent data (users, locks, logs)
- MQTT-based command dispatch to ESP32
- Heartbeat monitoring via MQTT (`smartlock/status`)
- Admin functionality:
  - Reassigning lock ownership
  - Reviewing logs for audit trails
- Scheduled tasks (via APScheduler) to detect offline devices every 10 seconds

### 3. 🛠️ ESP32 Smart Lock Device
- Connects to public Wi-Fi and MQTT broker
- Subscribes to `smartlock/commands`
- Executes LOCK/UNLOCK commands via LED indicators
- Publishes heartbeat/status every 9 seconds to `smartlock/status`
- Implements automatic MQTT reconnection
- Written in C++ using Arduino framework

---

## 🧾 Smart Lock Data Model
Each lock entry in MongoDB includes:
- `device_id` – Unique hardware ID
- `name` – Human-readable lock name
- `owner` – Username of the assigned user
- `status` – `Locked`, `Unlocked`, or `Unknown`
- `state` – `Available`, `Unavailable`
- `last_seen` – Timestamp of last heartbeat
- `issue` – Diagnostic info (e.g., “No power”)

---

## 🔄 Command Flow
```text
1. User logs in and receives JWT token
2. User sends `/api/lock` or `/api/unlock` to backend
3. Server checks authentication and ownership
4. Backend publishes command to `smartlock/commands` via MQTT
5. ESP32 receives and executes command (LED response)
6. ESP32 sends a status update to `smartlock/status`
7. Server updates device status in MongoDB
````

---

## 🔐 Security & Access Control

* JWT required for all user actions
* Locks are assigned to users at registration
* Role-based control (e.g., admin-only reassignment)
* Ownership verified before processing commands
* ESP32 status updates handled only via subscribed MQTT topic

---

## 🚀 Deployment

* Backend hosted on [Railway](https://railway.app/) with auto-deploy from GitHub
* Uses Railway free tier for public accessibility
* MongoDB Atlas used as a cloud database
* MQTT broker: `broker.emqx.io` (public broker for development)

---

## 🧪 Testing & Development Tools

* **Wokwi** simulation used for early ESP32 testing
* **Postman** for validating backend API endpoints
* Exported Postman collection shared with mobile development team
* Logs and device states viewable through API or MongoDB queries

---

## 📈 Future Improvements

* Replace public MQTT broker with a private or secured instance
* Add mobile push notifications for state changes
* Add Bluetooth fallback for offline operation
* Integrate dashboard for log visualization and remote diagnostics

