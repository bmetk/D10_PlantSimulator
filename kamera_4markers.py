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
            statusText.innerText = '✅ Kamera üzemel';
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
            statusText.innerText = '❌ Hiba a kapcsolatban!';
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
    
    # 4:3-as felbontás (1280x960), hogy a teljes szenzort használja (szélesebb látószög)
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
    
    # Memória a villogás megelőzésére (ha egy pillanatra elveszíti a markert)
    last_rect = None
    missing_frames = 0
    MAX_MISSING_FRAMES = 12  # Ennyi képkockáig tartja meg a vágást, ha eltűnne a marker
    
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
                        
                        if ids is not None and len(ids) >= 4:
                            cv2.aruco.drawDetectedMarkers(img, corners, ids)
                            
                            # 4 marker pontjainak kinyerése és sorba rendezése
                            pts = np.array([corners[i][0].mean(axis=0) for i in range(min(4, len(ids)))], dtype="float32")
                            if len(pts) >= 4:
                                rect = np.zeros((4, 2), dtype="float32")
                                s = pts.sum(axis=1)
                                rect[0] = pts[np.argmin(s)]  # Bal-Felső
                                rect[2] = pts[np.argmax(s)]  # Jobb-Alsó
                                diff = np.diff(pts, axis=1)
                                rect[1] = pts[np.argmin(diff)]  # Jobb-Felső
                                rect[3] = pts[np.argmax(diff)]  # Bal-Alsó
                                
                                rect_to_use = rect
                                last_rect = rect
                                missing_frames = 0 # Újra 0-ázzuk a számlálót, mert látja mind a 4-et
                                
                        elif last_rect is not None and missing_frames < MAX_MISSING_FRAMES:
                            # Ha nem látta mind a 4-et, de még kereten belül vagyunk, használjuk az előzőt!
                            rect_to_use = last_rect
                            missing_frames += 1
                        else:
                            # Ha túl sokáig nincs meg, elengedjük a memóriát
                            last_rect = None
                            missing_frames = 0
                            
                        # Ha van érvényes koordinátánk (akár friss, akár az emlékezetből), kivágjuk!
                        if rect_to_use is not None:
                            (tl, tr, br, bl) = rect_to_use
                            widthA = np.linalg.norm(br - bl)
                            widthB = np.linalg.norm(tr - tl)
                            maxWidth = max(int(widthA), int(widthB))
                            
                            heightA = np.linalg.norm(tr - br)
                            heightB = np.linalg.norm(tl - bl)
                            maxHeight = max(int(heightA), int(heightB))
                            
                            if maxWidth > 50 and maxHeight > 50:
                                dst = np.array([
                                    [0, 0],
                                    [maxWidth - 1, 0],
                                    [maxWidth - 1, maxHeight - 1],
                                    [0, maxHeight - 1]
                                ], dtype="float32")
                                
                                M = cv2.getPerspectiveTransform(rect_to_use, dst)
                                img = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
                                
                        ret, encoded_img = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                        if ret:
                            await ws.send_bytes(encoded_img.tobytes())
                else:
                    if start == -1 and len(buffer) > 2:
                        buffer = buffer[-2:]
                    break
    except Exception as e:
        pass
    finally:
        try:
            process.terminate()
        except:
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
