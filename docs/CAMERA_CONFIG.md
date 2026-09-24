# `kamera_siemens.py` konfigurációs magyarázata

Ez a dokumentum a [`kamera_siemens.py`] beállítható értékeit
és a Siemens felé küldött adatok működését foglalja össze.

## Futtatási környezet

A program Raspberry Pi kameráról olvas MJPEG videófolyamot, OpenCV-vel
ArUco markereket és a markerek által kijelölt területen gépeket keres, majd
egy böngészős kezelőfelületen megjeleníti a képet. A Siemens PLC TCP-kapcsolaton
keresztül kapja meg a gépek aktuális állapotát.

Szükséges főbb összetevők:

- Python 3
- `opencv-python` (`cv2`)
- `numpy`
- `aiohttp`
- Raspberry Pi kamera és a `rpicam-vid` parancs
- hálózati kapcsolat a Siemens PLC felé

## Python-konstansok

A fájl elején található konfigurációs értékek:

```python
SIEMENS_MAX_X, SIEMENS_MAX_Y = 600, 600
TCP_SZERVER_PORT = 27015
MAX_MISSING_FRAMES = 12
```

### `SIEMENS_MAX_X` és `SIEMENS_MAX_Y`

Az észlelt gép képpozícióját a program erre a Siemens-koordinátatartományra
képezi le:

- `SIEMENS_MAX_X`: maximális X-koordináta
- `SIEMENS_MAX_Y`: maximális Y-koordináta

Az értékek nem a kamera felbontását jelentik. A kamera képén mért koordináták
arányosan, 0 és a megadott maximum között kerülnek elküldésre. Ha a PLC-ben
más munkaterületet használunk, ezt a két értéket kell a PLC elvárt
koordinátatartományához igazítani.

### `TCP_SZERVER_PORT`

```python
TCP_SZERVER_PORT = 27015
```

Ezen a TCP-porton várja a program a Siemens PLC csatlakozását. A portot a
tűzfalon és a hálózati konfigurációban is engedélyezni kell. Ha módosítjuk,
a PLC oldali kliens portbeállítását is módosítani kell.

### `MAX_MISSING_FRAMES`

```python
MAX_MISSING_FRAMES = 12
```

Ha a kamera néhány képkockán keresztül nem látja megfelelően a kijelölő
markereket, a program ennyi képkockáig megtartja az utolsó érvényes
perspektívát. Ez csökkenti a kép villogását rövid felismerési hibák esetén.
Túl magas értéknél a kivágás túl sokáig maradhat érvényben, túl alacsony
értéknél pedig a kép gyakrabban visszaválthat eredeti nézetre.

## Kamera beállításai

A kamera háttérfeladat az alábbi `rpicam-vid` parancsot indítja:

```text
rpicam-vid -t 0 --codec mjpeg --width 1280 --height 960
           --framerate 15 --nopreview -o -
```

Az értékek jelentése:

- `-t 0`: folyamatos rögzítés
- `--codec mjpeg`: MJPEG képkockák előállítása
- `--width 1280`, `--height 960`: 4:3 képfelbontás
- `--framerate 15`: 15 képkocka másodpercenként
- `--nopreview`: ne induljon helyi előnézeti ablak
- `-o -`: a képek szabványos kimenetre kerülnek, ahonnan a Python beolvassa

Teljesítményprobléma esetén elsősorban a felbontás és a képkockasebesség
csökkenthető. A képarányt érdemes 4:3-ban megtartani, ha a teljes
kameraérzékelő használata szükséges.

## ArUco markerek és kivágás

Az OpenCV `DICT_ARUCO_ORIGINAL` szótárát használja a program. A kijelölő
kerethez legalább három marker szükséges:

- három markerből a program kiszámítja a negyedik pontot;
- négy vagy több marker esetén az első négy észlelt marker pontjaiból dolgozik;
- a pontokat bal felső, jobb felső, jobb alsó, bal alsó sorrendbe rendezi;
- a perspektivikus transzformáció után a kijelölt területet elemzi.

Az adatküldés indítására a **42-es ArUco marker** szolgál. Ha ez a marker
látható, és még nincs aktív küldés, a program automatikusan elindít egy
1,5 másodperces küldési sorozatot.

## Gépazonosítás és forgatás

A kijelölt területen a program kör alakú pontokat keres. A pontok száma adja
a gép azonosítóját:

- `0`: robotkar
- `1`: Gép1
- `2`: Gép2
- `3`: Gép3
- `4`: Gép4
- `5`: Gép5

Ezért egy gép azonosításához a hozzá tartozó jelölésnek 0 és 5 közötti számú
felismerhető pontot kell tartalmaznia. Az ennél nagyobb pontszámú vagy hibásan
felismert objektumot a program nem küldi el.

A forgatási érték a pontok tömegközéppontjának a kivágott terület közepéhez
viszonyított helyzete:

- `1`: alapirány / felfelé
- `2`: jobbra
- `3`: lefelé
- `4`: balra

Az aktuális állapotot a program az alábbi szerkezetben tárolja:

```python
aktualis_gepek[gép_id] = {
    "rot": forgatás,
    "x": x_koordináta,
    "y": y_koordináta,
}
```

Induláskor mind a hat gép alapértéke `rot=1`, `x=0`, `y=0`.

## Siemens TCP-adatformátum

A PLC felé küldött sor egy fejlécből, majd a hat gép három értékéből áll:

```text
1,rot0,x0,y0,rot1,x1,y1,rot2,x2,y2,rot3,x3,y3,rot4,x4,y4,rot5,x5,y5
```

Példa:

```text
1,1,120,80,2,240,80,3,360,80,4,120,220,1,240,220,2,360,220
```

Az értékek sorrendje mindig:

1. fejléc: `1`
2. robotkar (`aktualis_gepek[0]`): forgatás, X, Y
3. Gép1 (`aktualis_gepek[1]`): forgatás, X, Y
4. Gép2 (`aktualis_gepek[2]`): forgatás, X, Y
5. Gép3 (`aktualis_gepek[3]`): forgatás, X, Y
6. Gép4 (`aktualis_gepek[4]`): forgatás, X, Y
7. Gép5 (`aktualis_gepek[5]`): forgatás, X, Y

Minden sor újsor karakterrel (`\n`) zárul. Az adatok csak aktív küldési
sorozat alatt mennek ki, körülbelül 100 ms-os időközzel.

## Webes felület és HTTP-port

A webes felület a következő címen érhető el:

```text
http://<172.22.30.2:5002>/
```

A `5002`-es portot a fájl alján található `web.run_app(..., port=5002)`
határozza meg. A webes felület funkciói:

- `/`: kamera- és állapotoldal
- `/ws`: WebSocket, amelyen a JPEG képkockák érkeznek
- `/api/dominoes`: az aktuális gépadatok vesszővel elválasztva
- `/api/trigger_send`: HTTP POST-tal kézi küldési sorozat indítása

A felület Siemens hostként jelenleg a `172.22.30.1` címet írja ki. Ez
tájékoztató szöveg a HTML-ben; a Python TCP-szervere minden hálózati
interfészen (`0.0.0.0`) figyel, ezért a tényleges elérhetőséget a PLC és a
Raspberry Pi hálózati beállítása határozza meg.

## Módosítási útmutató

Tipikus módosítások:

| Cél                                    | Módosítandó érték                                     |
| ---------------------------------------| ----------------------------------------------------- |
| Siemens koordinátatartomány módosítása | `SIEMENS_MAX_X`, `SIEMENS_MAX_Y`                      |
| PLC TCP-port módosítása                | `TCP_SZERVER_PORT` és a PLC kliensbeállítása          |
| Marker eltűnésének tolerálása          | `MAX_MISSING_FRAMES`                                  |
| Kamera felbontása vagy sebessége       | `kamera_hatterszal()` `rpicam-vid` parancsa           |
| Webes felület portja                   | `web.run_app(..., port=5002)`                         |
| Küldés indító markerének módosítása    | `kamera_hatterszal()` `42 in ids.flatten()` feltétele |

Módosítás után indítsuk újra a programot, ellenőrizzük a webes felületet,
majd a `/api/dominoes` végponton és a PLC oldali TCP-kapcsolaton is
ellenőrizzük a ténylegesen küldött értékeket.
