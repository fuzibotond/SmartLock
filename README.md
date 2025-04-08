# Smart Lock System – Overview

## Purpose
A thrustworthy IoT system that enables users to register, manage, and control smart locks through a mobile app interface, while ESP32 devices handle physical lock actions and status reporting.

## System Components

### 1. **Mobile App (Client)**
- Users can:
  - Sign up / Sign in
  - Lock or unlock their smart locks
  - Monitor lock status and availability
  - View issues or faults with the lock

### 2. **API Server (FastAPI + MongoDB)**
- JWT-based user authentication
- MongoDB for persistent storage (users, locks, logs)
- MQTT publishing for lock/unlock commands
- HTTP endpoints for status reporting from ESP32
- Admin capabilities (e.g., lock reassignment)

### 3. **ESP32 Smart Lock Device**
- Connects to WiFi
- Listens for MQTT commands (`smartlock/commands`)
- Posts status updates to FastAPI every 30 seconds via HTTP

## Smart Lock Data Model
Each lock contains:
- `device_id`: unique identifier
- `name`: display name
- `owner`: the username of the user
- `status`: `Locked` / `Unlocked`
- `state`: `Available` / `Unavailable`
- `last_seen`: timestamp of last heartbeat
- `issue`: any error description or diagnostic info

## Command Flow
1. User signs in via mobile app → receives JWT token
2. User sends `/api/lock` or `/api/unlock` to control a lock
3. Server checks authorization and ownership
4. Server publishes the command to the appropriate MQTT topic
5. ESP32 receives the MQTT message, locks/unlocks
6. ESP32 posts status to `/api/esp32/status`
7. Server updates the lock’s state and status

## Security & Access Control
- Only authenticated users can control locks
- Locks are linked to specific user accounts
- All commands are validated for ownership
- Admins can reassign locks using `/locks/{device_id}/reassign`
- API key required for device-side communication (ESP32)

---

This system bridges IoT device control with secure multi-user management and can be extended with dashboards, alerts, or remote diagnostics.
