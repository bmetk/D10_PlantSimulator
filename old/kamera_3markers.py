import asyncio
import subprocess
import cv2
import numpy as np
from aiohttp import web

HTML_OLDAL = """
<!DOCTYPE html>
<html lang="hu">
<head>
    <meta charset="UTF-8">
    <title>Siemens Plant Simulator</title>
    <style>
        body { background-color: #121212; color: white; text-align: center; font-family: sans-serif; padding: 20px; }
        h2 { color: #00ffcc; }
        img { width: 100%; max-width: 1000px; border: 2px solid #555; border-radius: 10px; background-color: #000; }
        .status { margin-top: 15px; color: #aaaaaa; }
    </style>
</head>
<body>
    <h2>Siemens Plant Simulator</h2>
    <img id="kep" alt="Kamera betöltése...">
    <p class="status" id="status-text">Csatlakozás folyamatban...</p>
    
    <script>
        const img = document.getElementById('kep');
        const statusText = document.getElementById('status-text');
        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        ws.binaryType = 'blob';
        let currentObjectUrl = null;
        
        ws.onopen = function() {
            statusText.innerText = 'Kamera üzemel';
            statusText.style.color = '#00ffcc';
        };
        
        ws.onmessage = function(event) {
            if (currentObjectUrl) {
                URL.revokeObjectURL(currentObjectUrl);
            }
            currentObjectUrl = URL.createObjectURL(event.data);
            img.src = currentObjectUrl;
        };
        
        ws.onerror = function() {
            statusText.innerText = 'Hiba a kapcsolatban!';
            statusText.style.color = 'red';
        };
    </script>
</body>
</html>
"""

async def index(request):
    return web.Response(text=HTML_OLDAL, content_type='text/html')

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    parancs = [
        "rpicam-vid", "-t", "0", "--codec", "mjpeg", 
        "--width", "1280", "--height", "960", "--framerate", "30", 
        "--nopreview", "-o", "-"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *parancs,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    
    try:
        aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_ARUCO_ORIGINAL)
        parameters = cv2.aruco.DetectorParameters_create()
        detector = None
    except AttributeError:
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_ORIGINAL)
        parameters = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)
    
    last_rect = None
    missing_frames = 0
    MAX_MISSING_FRAMES = 12
    
    try:
        buffer = b''
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            buffer += chunk
            
            while True:
                start = buffer.find(b'\xff\xd8')
                end = buffer.find(b'\xff\xd9')
                
                if start != -1 and end != -1 and end > start:
                    frame_bytes = buffer[start:end+2]
                    buffer = buffer[end+2:]
                    
                    np_arr = np.frombuffer(frame_bytes, np.uint8)
                    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    
                    if img is not None:
                        if detector is None:
                            corners, ids, rejected = cv2.aruco.detectMarkers(img, aruco_dict, parameters=parameters)
                        else:
                            corners, ids, rejected = detector.detectMarkers(img)
                            
                        rect_to_use = None
                        
                        if ids is not None and len(ids) >= 3:
                            # KIKAPCSOLVA: Ne rajzoljon zöld keretet és kék szöveget az ArUco-kra, mert belezavar a dominókba!
                            # cv2.aruco.drawDetectedMarkers(img, corners, ids)
                            
                            num_markers = min(4, len(ids))
                            pts = np.array([corners[i][0].mean(axis=0) for i in range(num_markers)], dtype="float32")
                            
                            if len(pts) == 3:
                                d01, d12, d02 = np.linalg.norm(pts[0]-pts[1]), np.linalg.norm(pts[1]-pts[2]), np.linalg.norm(pts[0]-pts[2])
                                if d01 >= d12 and d01 >= d02: A, C, B = pts[0], pts[1], pts[2]
                                elif d12 >= d01 and d12 >= d02: A, C, B = pts[1], pts[2], pts[0]
                                else: A, C, B = pts[0], pts[2], pts[1]
                                pts = np.vstack((pts, A + C - B))
                            
                            if len(pts) == 4:
                                rect = np.zeros((4, 2), dtype="float32")
                                s, diff = pts.sum(axis=1), np.diff(pts, axis=1)
                                rect[0], rect[2] = pts[np.argmin(s)], pts[np.argmax(s)]
                                rect[1], rect[3] = pts[np.argmin(diff)], pts[np.argmax(diff)]
                                rect_to_use = last_rect = rect
                                missing_frames = 0 
                                
                        elif last_rect is not None and missing_frames < MAX_MISSING_FRAMES:
                            rect_to_use = last_rect
                            missing_frames += 1
                        else:
                            last_rect = None
                            missing_frames = 0
                            
                        if rect_to_use is not None:
                            tl, tr, br, bl = rect_to_use
                            maxWidth = max(int(np.linalg.norm(br - bl)), int(np.linalg.norm(tr - tl)))
                            maxHeight = int(maxWidth * 1.1)
                            
                            if maxWidth > 50 and maxHeight > 50:
                                dst = np.array([
                                    [0, 0], [maxWidth - 1, 0],
                                    [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]
                                ], dtype="float32")
                                
                                M = cv2.getPerspectiveTransform(rect_to_use, dst)
                                img = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
                                
                                # ==========================================
                                # DOMINÓ FELISMERÉS
                                # ==========================================
                                try:
                                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                                    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                                    
                                    # 1. Dominó testek megtalálása
                                    _, thresh = cv2.threshold(blurred, 120, 255, cv2.THRESH_BINARY)
                                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                                    
                                    for cnt in contours:
                                        area = cv2.contourArea(cnt)
                                        
                                        if 800 < area < 50000: 
                                            x, y, w, h = cv2.boundingRect(cnt)
                                            
                                            # --- ÚJ: SZÉL-SZŰRÉS ---
                                            # Ha a doboz a kép szélétől 30 pixelen belül van, az szinte biztosan
                                            # egy levágott QR kód sarka. Hagyjuk figyelmen kívül!
                                            margin = 30
                                            if x < margin or y < margin or (x + w) > maxWidth - margin or (y + h) > maxHeight - margin:
                                                continue
                                            # -----------------------
                                                
                                            aspect_ratio = float(w) / h
                                            if 0.7 <= aspect_ratio <= 1.3:
                                                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
                                                
                                                roi_gray = gray[y:y+h, x:x+w]
                                                
                                                # --- ÚJ: OKOS KÜSZÖB A PÖTTYÖKHÖZ ---
                                                # Kiszámoljuk a dominó átlagos fényességét
                                                roi_mean = np.mean(roi_gray)
                                                
                                                # A pöttyök azok a területek, amik legalább 35-tel sötétebbek az átlagnál
                                                _, roi_thresh = cv2.threshold(roi_gray, roi_mean - 35, 255, cv2.THRESH_BINARY_INV)
                                                # ------------------------------------
                                                
                                                dot_contours, _ = cv2.findContours(roi_thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
                                                
                                                dot_count = 0
                                                for dot_cnt in dot_contours:
                                                    dot_area = cv2.contourArea(dot_cnt)
                                                    
                                                    # A pötty mérete kb jónak kell legyen
                                                    if 15 < dot_area < 400:
                                                        perimeter = cv2.arcLength(dot_cnt, True)
                                                        circularity = 4 * np.pi * (dot_area / (perimeter * perimeter + 1e-6))
                                                        
                                                        # Megfelelően kerek formák elfogadása
                                                        if circularity > 0.5:
                                                            dot_count += 1
                                                            (dx, dy), radius = cv2.minEnclosingCircle(dot_cnt)
                                                            cv2.circle(img, (int(x+dx), int(y+dy)), int(radius), (0, 0, 255), 2)
                                                
                                                cv2.putText(img, f"Ertek: {dot_count}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                except Exception as e:
                                    print(f"Hiba a CV feldolgozasban: {e}")
                                # ==========================================
                                # DOMINÓ FELISMERÉS VÉGE
                                # ==========================================

                        ret, encoded_img = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 65])
                        if ret:
                            await ws.send_bytes(encoded_img.tobytes())
                else:
                    if start == -1 and len(buffer) > 2:
                        buffer = buffer[-2:]
                    break
    except Exception:
        pass
    finally:
        try:
            process.terminate()
        except Exception:
            pass
        await ws.close()
        
    return ws

if __name__ == '__main__':
    app = web.Application()
    app.add_routes([
        web.get('/', index),
        web.get('/ws', websocket_handler)
    ])
    web.run_app(app, host='0.0.0.0', port=5002)
