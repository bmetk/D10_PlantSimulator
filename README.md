# Siemens Plant Camera & Simulator

A Raspberry Pi 4 based computer vision and simulation bridge. It tracks physical workpieces (dominos) in real-time using OpenCV and streams their coordinates to a Siemens PLC/system while providing an ultra-low latency web dashboard.

## Key Features
* **Real-time Object Tracking:** Identifies position, rotation, and ID of physical workpieces.
* **Auto-Calibration:** Uses ArUco markers to flatten and deskew the camera feed automatically.
* **Web Dashboard:** Built-in asynchronous web server providing a live camera feed (MJPEG over WebSocket) and system status.
* **Siemens TCP Bridge:** Bursts coordinate data to a Siemens host (Port 27015) upon hardware trigger (ArUco ID 42) or UI interaction.

## Documentation
For detailed information, please refer to the following documents:
* **[User Guide (PDF)](link-to-your-pdf-file.pdf):** Step-by-step instructions for physical setup and everyday usage.
* **[Architecture & Logic (camera_config.md)](CAMERA_CONFIG.md):** Deep dive into the Python source code and CV pipeline.

## Development Workflow (For Future Students)

This software is already installed and runs automatically as a background service (`siemens.service`) on the lab's specific Raspberry Pi. You **do not** need to install it from scratch.

If you need to improve or fix the code, follow this workflow:

1. Clone this repository to your **own computer** (using VS Code, Zed, etc.).
2. Make your modifications locally, then commit and push to GitHub.
3. Open a terminal on the **Raspberry Pi** and pull your latest changes:
   ```bash
   cd /home/tk/Desktop/siemens_projekt
   git pull
