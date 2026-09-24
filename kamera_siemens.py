import asyncio
import cv2
import numpy as np
from aiohttp import web
import sys

# ==========================================
# KONFIGURÁCIÓ ÉS GLOBÁLIS VÁLTOZÓK
# ==========================================
SIEMENS_MAX_X, SIEMENS_MAX_Y = 600, 600
TCP_SZERVER_PORT = 27015
MAX_MISSING_FRAMES = 12

# Fix sorrendű szótár a 6 gépnek. 
# Indexek: 0 = Robotkar, 1 = Gép1, 2 = Gép2, 3 = Gép3, 4 = Gép4, 5 = Gép5
aktualis_gepek = {i: {"rot": 1, "x": 0, "y": 0} for i in range(6)}

kuldes_keres = False
latest_frame = b'' # Itt tároljuk a háttérben futó kamera legfrissebb képét

# ==========================================
# HTML OLDAL (Átrendezett hálózati adatokkal)
# ==========================================
HTML_OLDAL = """
<!DOCTYPE html>
<html lang="hu">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Siemens Plant Simulator</title>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0f172a; --panel: #1e293b; --text: #f8fafc; --muted: #94a3b8; --accent: #0ea5e9; --success: #10b981; --danger: #ef4444; }
        body { font-family: 'Roboto', sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; padding: 20px; margin: 0; }
        .card { background: var(--panel); padding: 20px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); width: 100%; max-width: 640px; text-align: center; }
        h1 { margin: 0 0 15px 0; font-size: 1.8rem; color: var(--accent); }
        .video-wrapper { position: relative; width: 100%; background: #000; border-radius: 8px; overflow: hidden; margin-bottom: 15px; }
        img { width: 100%; display: block; }
        .status-bar { display: flex; justify-content: center; align-items: center; font-size: 0.95rem; margin-bottom: 15px; padding: 12px 15px; background: rgba(0,0,0,0.2); border-radius: 8px; }
        .indicator { display: flex; align-items: center; gap: 8px; font-weight: bold; }
        .dot { width: 12px; height: 12px; border-radius: 50%; background: var(--muted); transition: all 0.3s ease; }
        .dot.online { background: var(--success); box-shadow: 0 0 8px var(--success); }
        .dot.offline { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
        .network-details { background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 0.9rem; text-align: left; line-height: 1.6; }
        .network-title { color: var(--accent); font-weight: bold; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; font-size: 1rem; }
        .hint { font-size: 0.85rem; color: var(--muted); text-align: center; background: rgba(14, 165, 233, 0.1); border-left: 3px solid var(--accent); padding: 10px; border-radius: 0 6px 6px 0; margin-bottom: 15px; }
        .btn { background: var(--success); color: #fff; border: none; width: 100%; padding: 15px; border-radius: 8px; font-size: 1.1rem; font-weight: bold; cursor: pointer; transition: transform 0.2s, background 0.2s; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.2); }
        .btn:hover { transform: translateY(-2px); filter: brightness(1.1); }
        .links { margin-top: 15px; font-size: 0.85rem; }
        .links a { color: var(--muted); text-decoration: none; transition: color 0.2s; }
        .links a:hover { color: var(--accent); }
    </style>
</head>
<body>
    <div class="card">
        <h1>Siemens Plant Simulator</h1>
        
        <div class="video-wrapper">
            <img id="kep" alt="Kamera folyam betöltése...">
        </div>
        
        <div class="status-bar">
            <div class="indicator">
                <div class="dot" id="status-dot"></div>
                <span id="status-text">Csatlakozás...</span>
            </div>
        </div>

        <div class="network-details">
            <div class="network-title">Hálózati paraméterek</div>
            <div>• Kamera IP: <b id="pi-ip">...</b></div>
            <div>• Siemens Host: <b>172.22.30.1</b></div>
            <div>• TCP Port: <b>27015</b></div>
        </div>

        <div class="hint">
            Tipp: Mutasd fel a <b>42-es</b> sorszámú ArUco markert az adatok küldéséhez!
        </div>
        
        <button class="btn" id="send-btn" onclick="sendDataToSiemens()">POZÍCIÓK ELKÜLDÉSE</button>
        
        <div class="links">
            <a href="/api/dominoes" target="_blank">Nyers hálózati adatfolyam megtekintése</a>
        </div>
    </div>
    
    <script>
        document.getElementById('pi-ip').innerText = window.location.hostname;

        const img = document.getElementById('kep');
        const statusText = document.getElementById('status-text');
        const statusDot = document.getElementById('status-dot');
        let ws;

        function csatlakozasWebSocket() {
            statusText.innerText = 'Csatlakozás...';
            statusDot.className = 'dot';
            
            ws = new WebSocket('ws://' + window.location.host + '/ws');
            ws.binaryType = 'blob';
            
            ws.onopen = () => { 
                statusText.innerText = 'Kamera üzemel'; 
                statusText.style.color = 'var(--success)';
                statusDot.className = 'dot online';
            };
            ws.onclose = () => { 
                statusText.innerText = 'Újracsatlakozás...'; 
                statusText.style.color = 'var(--danger)'; 
                statusDot.className = 'dot offline';
                setTimeout(csatlakozasWebSocket, 1000);
            };
            ws.onerror = () => { 
                statusText.innerText = 'Hiba!'; 
                statusText.style.color = 'var(--danger)'; 
                statusDot.className = 'dot offline';
            };
            
            let currentObjectUrl = null;
            ws.onmessage = (event) => {
                if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
                img.src = currentObjectUrl = URL.createObjectURL(event.data);
            };
        }

        csatlakozasWebSocket();
        
        function sendDataToSiemens() {
            const btn = document.getElementById('send-btn');
            btn.innerHTML = "KÜLDÉS FOLYAMATBAN...";
            btn.style.backgroundColor = "#eab308";
            
            fetch('/api/trigger_send', { method: 'POST' }).then(res => {
                if(res.ok) {
                    btn.innerHTML = "SIKERES KÜLDÉS!";
                    btn.style.backgroundColor = "var(--primary)";
                } else {
                    btn.innerHTML = "KÜLDÉSI HIBA!";
                    btn.style.backgroundColor = "var(--danger)";
                }
                setTimeout(() => { btn.innerHTML = "POZÍCIÓK ELKÜLDÉSE"; btn.style.backgroundColor = "var(--success)"; }, 2000);
            }).catch(err => {
                btn.innerHTML = "HÁLÓZATI HIBA!";
                btn.style.backgroundColor = "var(--danger)";
                setTimeout(() => { btn.innerHTML = "POZÍCIÓK ELKÜLDÉSE"; btn.style.backgroundColor = "var(--success)"; }, 2000);
            });
        }
    </script>
</body>
</html>
"""

async def index(request):
    return web.Response(text=HTML_OLDAL, content_type='text/html')

async def api_dominoes(request):
    adat_lista = ["1"]
    for i in range(6):
        d = aktualis_gepek[i]
        adat_lista.extend([str(d['rot']), str(d['x']), str(d['y'])])
    return web.Response(text=",".join(adat_lista), content_type='text/plain')

async def activate_burst_send():
    global kuldes_keres
    if kuldes_keres: return
    print("Adatfolyam indítása (1.5 mp-es sorozatlövés)...")
    kuldes_keres = True
    await asyncio.sleep(1.5)
    kuldes_keres = False
    print("Adatfolyam leállítva.")

async def api_trigger_send(request):
    try:
        await activate_burst_send()
        return web.Response(text="OK")
    except Exception as e:
        return web.Response(text=str(e), status=500)

# ==========================================
# TCP SZERVER LOGIKA (A SIEMENS FELÉ)
# ==========================================
async def siemens_kliens_kezelese(reader, writer):
    global kuldes_keres
    cimszo = writer.get_extra_info('peername')
    print(f"Új Siemens kapcsolat érkezett innen: {cimszo}")
    try:
        while True:
            await asyncio.sleep(0.1) 
            
            if kuldes_keres:
                adat_lista = ["1"]
                for i in range(6):
                    d = aktualis_gepek[i]
                    adat_lista.extend([str(d['rot']), str(d['x']), str(d['y'])])
                    
                adat_szoveg = ",".join(adat_lista) + "\n"
                
                writer.write(adat_szoveg.encode('utf-8'))
                await writer.drain()
    except ConnectionResetError:
        print(f"A Siemens megszakította a kapcsolatot ({cimszo}).")
    except Exception as e:
        print(f"Hiba a hálózati küldéskor: {e}")
    finally:
        print("Várakozás új csatlakozásra...")
        writer.close()
        await writer.wait_closed()

async def indit_tcp_szerver(app):
    app['tcp_server'] = await asyncio.start_server(siemens_kliens_kezelese, '0.0.0.0', TCP_SZERVER_PORT)
    print(f"TCP Szerver elindult! Várom a Siemenst a(z) {TCP_SZERVER_PORT}-es porton...")

async def leallit_tcp_szerver(app):
    app['tcp_server'].close()
    await app['tcp_server'].wait_closed()

# ==========================================
# FÜGGETLEN KAMERA HÁTTÉRSZÁL
# ==========================================
async def kamera_hatterszal(app):
    global aktualis_gepek, kuldes_keres, latest_frame
    
    parancs = ["rpicam-vid", "-t", "0", "--codec", "mjpeg", "--width", "1280", "--height", "960", "--framerate", "15", "--nopreview", "-o", "-"]
    process = await asyncio.create_subprocess_exec(*parancs, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    
    try:
        aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_ARUCO_ORIGINAL)
        parameters = cv2.aruco.DetectorParameters_create()
        detector = None
    except AttributeError:
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_ORIGINAL)
        parameters = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)
    
    last_rect, missing_frames, buffer = None, 0, b''
    
    try:
        while chunk := await process.stdout.read(8192):
            buffer += chunk
            
            utolso_kocka_bajtok = None
            
            while (start := buffer.find(b'\xff\xd8')) != -1 and (end := buffer.find(b'\xff\xd9')) != -1 and end > start:
                utolso_kocka_bajtok = buffer[start:end+2]
                buffer = buffer[end+2:]
                
            if utolso_kocka_bajtok is not None:
                img = cv2.imdecode(np.frombuffer(utolso_kocka_bajtok, np.uint8), cv2.IMREAD_COLOR)
                if img is None: continue

                corners, ids, _ = cv2.aruco.detectMarkers(img, aruco_dict, parameters=parameters) if detector is None else detector.detectMarkers(img)
                
                if ids is not None and 42 in ids.flatten():
                    if not kuldes_keres:
                        asyncio.create_task(activate_burst_send())
                
                if kuldes_keres:
                    cv2.putText(img, "KULDES AKTIV!", (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

                rect_to_use = None
                if ids is not None and len(ids) >= 3:
                    pts = np.array([corners[i][0].mean(axis=0) for i in range(min(4, len(ids)))], dtype="float32")
                    if len(pts) == 3:
                        dist = [np.linalg.norm(pts[0]-pts[1]), np.linalg.norm(pts[1]-pts[2]), np.linalg.norm(pts[0]-pts[2])]
                        max_idx = np.argmax(dist)
                        A, C, B = (pts[0], pts[1], pts[2]) if max_idx == 0 else (pts[1], pts[2], pts[0]) if max_idx == 1 else (pts[0], pts[2], pts[1])
                        pts = np.vstack((pts, A + C - B))
                    
                    if len(pts) == 4:
                        s, diff = pts.sum(axis=1), np.diff(pts, axis=1)
                        rect_to_use = last_rect = np.array([pts[np.argmin(s)], pts[np.argmin(diff)], pts[np.argmax(s)], pts[np.argmax(diff)]], dtype="float32")
                        missing_frames = 0 
                elif last_rect is not None and missing_frames < MAX_MISSING_FRAMES:
                    rect_to_use = last_rect
                    missing_frames += 1
                else:
                    last_rect, missing_frames = None, 0
                    
                if rect_to_use is not None:
                    tl, tr, br, bl = rect_to_use
                    maxW = max(int(np.linalg.norm(br - bl)), int(np.linalg.norm(tr - tl)))
                    maxH = int(maxW * 1.1)
                    
                    if maxW > 50 and maxH > 50:
                        dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]], dtype="float32")
                        img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(rect_to_use, dst), (maxW, maxH))
                        
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        _, thresh = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 120, 255, cv2.THRESH_BINARY)
                        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        
                        for cnt in contours:
                            if not (800 < cv2.contourArea(cnt) < 50000): continue
                            
                            x, y, w, h = cv2.boundingRect(cnt)
                            if x < 30 or y < 30 or (x + w) > maxW - 30 or (y + h) > maxH - 30: continue
                            if not (0.7 <= float(w) / h <= 1.3): continue
                            
                            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
                            roi_gray = gray[y:y+h, x:x+w]
                            _, roi_thresh = cv2.threshold(roi_gray, np.mean(roi_gray) - 35, 255, cv2.THRESH_BINARY_INV)
                            dot_contours, _ = cv2.findContours(roi_thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
                            
                            dot_count = 0
                            dot_centers_x = []
                            dot_centers_y = []
                            
                            for dc in dot_contours:
                                if 15 < cv2.contourArea(dc) < 400 and (peri := cv2.arcLength(dc, True)) > 0:
                                    if (4 * np.pi * cv2.contourArea(dc) / (peri * peri)) > 0.5:
                                        dot_count += 1
                                        (dx, dy), radius = cv2.minEnclosingCircle(dc)
                                        cv2.circle(img, (int(x+dx), int(y+dy)), int(radius), (0, 0, 255), 2)
                                        
                                        dot_centers_x.append(dx)
                                        dot_centers_y.append(dy)
                            
                            gep_id = dot_count
                            rotation = 1
                            if dot_count > 0:
                                cx, cy = w / 2.0, h / 2.0 
                                mean_dx = sum(dot_centers_x) / dot_count 
                                mean_dy = sum(dot_centers_y) / dot_count 
                                
                                diff_x = mean_dx - cx
                                diff_y = mean_dy - cy
                                
                                if abs(diff_x) > abs(diff_y):
                                    rotation = 2 if diff_x > 0 else 4 
                                else:
                                    rotation = 3 if diff_y > 0 else 1 
                            
                            if 0 <= gep_id <= 5:
                                sim_x = int(((x + (w / 2)) / maxW) * SIEMENS_MAX_X)
                                sim_y = int(((y + (h / 2)) / maxH) * SIEMENS_MAX_Y)
                                
                                cv2.putText(img, f"ID:{gep_id} Rot:{rotation} ({sim_x},{sim_y})", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                aktualis_gepek[gep_id] = {"rot": rotation, "x": sim_x, "y": sim_y}

                ret, encoded_img = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if ret: 
                    latest_frame = encoded_img.tobytes()
                    
                await asyncio.sleep(0.005)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Hiba a kamera háttérszálban: {e}")
    finally:
        try: process.terminate()
        except: pass

async def indit_kamera_hatterszal(app):
    app['kamera_task'] = asyncio.create_task(kamera_hatterszal(app))

async def leallit_kamera_hatterszal(app):
    app['kamera_task'].cancel()
    try: await app['kamera_task']
    except asyncio.CancelledError: pass

# ==========================================
# BIZTONSÁGOS WEBSOCKET OLVASÓ
# ==========================================
async def websocket_handler(request):
    global latest_frame
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    last_sent = None
    try:
        while not ws.closed:
            frame = latest_frame
            if frame and frame != last_sent:
                try:
                    await ws.send_bytes(frame)
                    last_sent = frame
                except (ConnectionResetError, RuntimeError):
                    break
            
            await asyncio.sleep(0.033)
    except Exception:
        pass
    finally:
        try: await ws.close()
        except: pass
        
    return ws

if __name__ == '__main__':
    app = web.Application()
    
    app.on_startup.append(indit_kamera_hatterszal)
    app.on_startup.append(indit_tcp_szerver)
    app.on_cleanup.append(leallit_kamera_hatterszal)
    app.on_cleanup.append(leallit_tcp_szerver)
    
    app.add_routes([
        web.get('/', index),
        web.get('/ws', websocket_handler),
        web.get('/api/dominoes', api_dominoes),
        web.post('/api/trigger_send', api_trigger_send)
    ])
    
    web.run_app(app, host='0.0.0.0', port=5002)