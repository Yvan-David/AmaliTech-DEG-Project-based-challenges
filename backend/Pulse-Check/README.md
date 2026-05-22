# Pulse-Check API (Watchdog Sentinel)

A backend monitoring system that tracks remote devices (such as solar farms and weather stations) using heartbeat signals. If a device fails to send a heartbeat within a configured timeout period, the system automatically triggers an alert.

---

# 📌 Project Overview

This system simulates a **dead man’s switch monitoring service**:

- Devices register themselves with a unique ID and timeout value.
- Each device must periodically send a heartbeat signal.
- The server resets a countdown timer on every heartbeat.
- If the timer reaches zero → the device is marked as DOWN.
- An alert is triggered for support engineers.

---
# 🏗️ Architecture Diagram (Sequence Diagram)

![Pulse Check Architecture Diagram1](assets/sequence-diagram1.png)
![Pulse Check Architecture Diagram2](assets/sequence-diagram2.png)

- 🔗 Live Link: `https://lucid.app/lucidchart/bf38fad2-3468-4840-ae97-09adff426742/edit?viewport_loc=271%2C539%2C1469%2C699%2C0_0&invitationId=inv_9ebd47d9-e2db-4c3e-8c42-a20c363821ad` (LOGIN REQUIRED)


---
# 🧠 Key Concept

This project is based on a **heartbeat failure detection system** commonly used in:

- IoT monitoring systems  
- Distributed infrastructure monitoring  
- Remote sensor networks  
- Cloud service health tracking  

---

# ⚙️ System Design Summary

The system consists of:

- **Device Administrator** → Registers devices to be monitored
- **Monitoring Device** → Sends periodic heartbeat signals
- **Pulse-Check API Server** → Tracks state and timers
- **Support Engineer** → Receives alerts when a device fails

---

# 📡 API Endpoints

## 1. Register Monitor

Creates a new monitoring entry for a device.

[![Coverage Status](https://coveralls.io/repos/github/Yvan-David/AmaliTech-DEG-Project-based-challenges/badge.svg?branch=main)](https://coveralls.io/github/Yvan-David/AmaliTech-DEG-Project-based-challenges?branch=main&flag=Pulse-Check)

```http
POST /monitors

