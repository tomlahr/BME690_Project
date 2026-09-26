# PicoBME690 Wetterstation – MicroPython-Code

Innenraum-Klimastation mit **Waveshare Pico-LCD-0.96** und **BME690-Breakout** auf einem **Raspberry Pi Pico 2 W**.
Misst Temperatur, Luftfeuchte, Luftdruck und Gaswiderstand, zeigt die Werte auf dem kleinen LCD
und liefert ein Web-Dashboard im Heimnetz.

Stand: 26.09.2026 (Paket 2)

## Inhalt

- [Hardware und Firmware](#hardware-und-firmware)
- [Funktionen](#funktionen)
- [Installation](#installation)
- [secrets.py (Vorlage)](#secretspy-vorlage)
- [Bedienung](#bedienung)
- [Kalibrierung](#kalibrierung)
- [Dateien](#dateien)
- [Quellcode](#quellcode)

## Hardware und Firmware

- Raspberry Pi Pico 2 W (RP2350)
- Waveshare Pico-LCD-0.96 (ST7735S, 160×80, Joystick und Tasten)
- BME690-Breakout per I²C
- Firmware: Pimoroni MicroPython mit `breakout_bme69x`

## Funktionen

- Fünf LCD-Seiten (Klima, Gas/IAQ, Min/Max, WLAN, System), Bildschirmschoner mit gedimmtem Backlight
- Web-Dashboard mit Live-Werten (alle 5 s) und 3-h-Verläufen als SVG, Umlaute und °C
- Wettertrend aus dem Luftdruck (Ausgleichsgerade über 3 h)
- Relative Luftqualität mit Baseline im Flash (`iaq_baseline.txt`), 20 min Aufwärmphase nach dem Start
- Feuchte: Magnus-Umrechnung auf die kalibrierte Temperatur plus Sensor-Trim
- WLAN mit automatischer Wiederverbindung, Statusmeldung und Schnittstellen-Reset nach Fehlversuchen

## Installation

1. Pimoroni-MicroPython für den Pico 2 W flashen.
2. `secrets.py` nach der Vorlage unten anlegen.
3. Alle `.py`-Dateien aus diesem Dokument plus `secrets.py` ins Stammverzeichnis des Pico kopieren (z. B. mit Thonny).
4. Neu starten, WLAN mit **CTRL** einschalten. Die IP erscheint auf der WLAN-Seite und in der REPL.

Soll das WLAN beim Start automatisch angehen, in `config.py` die Zeile `# WIFI_AUTOSTART = True` einkommentieren.

## secrets.py (Vorlage)

`secrets.py` gehört **nicht** ins Repository (in `.gitignore` eintragen).

```python
# secrets.py
WIFI_SSID = "DeinNetz"
WIFI_PASSWORD = "DeinPasswort"
WIFI_COUNTRY = "DE"   # optional, sonst gilt config.WIFI_COUNTRY_DEFAULT
```

Der Hostname steht in `config.py` (`WIFI_HOSTNAME`).

## Bedienung

| Taste | Funktion |
|---|---|
| A / Joystick rechts | nächste Seite |
| B / Joystick links | vorige Seite |
| Joystick hoch / runter | Helligkeit |
| CTRL (Joystick drücken) | WLAN und Webserver an/aus |

Status auf der System-Seite: `ONLINE`, `LINK?` (verbindet), `OFFLINE` oder ein Fehlergrund:
`NOAP` Netz nicht gefunden, `AUTH` falsches Passwort, `FAIL` abgelehnt, `NOIP` keine IP per DHCP.

## Kalibrierung

Die Offsets gelten nur für eine bestimmte Aufstellung, Taktung und bei bestehender WLAN-Verbindung.

| Wert | Stand | Bedeutung |
|---|---|---|
| `TEMP_OFFSET` | -3.2 | wird zum Rohwert addiert (Eigenwärme von Pico, WLAN, Display, Heizer) |
| `HUMIDITY_TRIM` | 7.0 | Prozentpunkte nach der Magnus-Umrechnung (Sensor misst zu niedrig) |
| `PRESSURE_OFFSET` | 1.0 | hPa, Abgleich mit DWD |

Hinweise aus den Vergleichsmessungen (SwitchBot-Referenz):
- Ohne WLAN-Verbindung liest die Station gut 1 °C zu niedrig (Funkchip wärmt weniger).
- Direkte Sonne und warme Unterlagen (z. B. Metallmatten) verfälschen jede Messung.
- Seit Paket 2 läuft der Sensor im 3-s-Takt: Offset am endgültigen Standort neu abgleichen.
- Ob der Feuchte-Trim als Betrag oder Faktor besser passt, zeigt erst trockene Heizungsluft (35–45 %).

## Dateien

| Datei | Aufgabe |
|---|---|
| [`main.py`](#mainpy) | Initialisierung, Tastenabfrage (Flankenerkennung), Hauptschleife |
| [`config.py`](#configpy) | Zentrale Einstellungen: Pins, Takte, Kalibrierwerte, IAQ, WLAN |
| [`state.py`](#statepy) | Gemeinsamer Zustand aller Module |
| [`sensors.py`](#sensorspy) | BME690 lesen, Kalibrierung, Selbsttest, Status- und Trendtexte |
| [`iaq.py`](#iaqpy) | Relative Luftqualität aus dem Gaswiderstand (identisch im Enviro+-Projekt) |
| [`history.py`](#historypy) | 3-h-Verlauf, Deltas, Ausgleichsgerade, Laufzeit |
| [`display.py`](#displaypy) | LCD-Treiber (ST7735S, 160×80) und Bildschirmseiten |
| [`colors.py`](#colorspy) | Farbkonstanten (BGR565) |
| [`web.py`](#webpy) | HTML-Dashboard mit SVG-Verläufen, JSON-Endpoint /data |
| [`wifi.py`](#wifipy) | WLAN-Zustandsautomat mit Wiederverbindung und Webserver-Polling |

Nicht im Repository: `secrets.py`, `iaq_baseline.txt` (legt die Station selbst an).

## Quellcode

### `main.py`

Initialisierung, Tastenabfrage (Flankenerkennung), Hauptschleife (171 Zeilen)

```python
# main.py
# Bindet alle Module zusammen. Nur noch Tastenabfrage, Initialisierung und
# die Hauptschleife - die eigentliche Logik steckt in den anderen Dateien.

from machine import Pin
from pimoroni_i2c import PimoroniI2C
import gc
import time

import config
import state
import history
import sensors
import display
import wifi
import iaq

# ── Tasten ─────────────────────────────────────────────────────
# Paket 1 (2026-09-23): Flankenerkennung statt Warteschleife. Die alte
# pressed()-Funktion wartete, solange eine Taste gehalten wurde - in der
# Zeit standen Sensor, Display und Webserver. Jetzt: genau ein Ereignis
# pro Druck, kein Warten.
class Key:
    def __init__(self, pin, debounce_ms=25):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self.debounce_ms = debounce_ms
        self._down = False
        self._t = 0

    def pressed(self):
        """True genau einmal pro Druck (fallende Flanke, entprellt)."""
        now = time.ticks_ms()
        down = not self.pin.value()  # Pull-up: gedrueckt = 0
        if down != self._down and \
           time.ticks_diff(now, self._t) >= self.debounce_ms:
            self._down = down
            self._t = now
            return down
        return False


KEY_UP = Key(2)
KEY_DOWN = Key(18)
KEY_LEFT = Key(16)
KEY_RIGHT = Key(20)
KEY_CTRL = Key(3)
KEY_A = Key(15)
KEY_B = Key(17)


# ── Initialisierung ─────────────────────────────────────────────
display.init()

i2c = PimoroniI2C(sda=config.I2C_SDA, scl=config.I2C_SCL)
sensors.init(i2c)
state.iaq = iaq.IAQ()   # laedt die Baseline vom Flash, falls vorhanden

state.boot_time = time.ticks_ms()
state.min_mem_free = gc.mem_free()

# Starthelligkeit: 600
display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

last_sensor = time.ticks_add(state.boot_time, -config.SENSOR_INTERVAL_MS)
last_display = time.ticks_add(state.boot_time, -config.DISPLAY_INTERVAL_MS)
last_history = time.ticks_add(state.boot_time, -config.HISTORY_INTERVAL_MS)
last_iaq_save = state.boot_time

# Frueher sammeln statt erst im Notfall
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

state.last_activity = state.boot_time

# Optional: WLAN direkt einschalten (config.WIFI_AUTOSTART, standardmaessig aus)
if getattr(config, "WIFI_AUTOSTART", False):
    wifi.toggle_wifi()

# ── Hauptschleife ───────────────────────────────────────────────
while True:
    # Alle Tasten JEDE Runde abfragen - sonst verpasst eine Taste, die durch
    # "or"-Kurzschluss uebersprungen wird, ihre Flanke.
    k_a, k_right = KEY_A.pressed(), KEY_RIGHT.pressed()
    k_b, k_left = KEY_B.pressed(), KEY_LEFT.pressed()
    k_up, k_down = KEY_UP.pressed(), KEY_DOWN.pressed()
    k_ctrl = KEY_CTRL.pressed()

    any_key = False

    if k_a or k_right:
        any_key = True
        if not state.screensaver_active:
            state.mode = (state.mode + 1) % len(config.MODE_NAMES)
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    elif k_b or k_left:
        any_key = True
        if not state.screensaver_active:
            state.mode = (state.mode - 1) % len(config.MODE_NAMES)
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    elif k_up:
        any_key = True
        if not state.screensaver_active:
            state.brightness_idx = min(
                state.brightness_idx + 1,
                len(config.BRIGHTNESS_LEVELS) - 1
            )
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

    elif k_down:
        any_key = True
        if not state.screensaver_active:
            state.brightness_idx = max(state.brightness_idx - 1, 0)
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

    elif k_ctrl:
        any_key = True
        if not state.screensaver_active:
            wifi.toggle_wifi()
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    if any_key:
        state.last_activity = time.ticks_ms()
        if state.screensaver_active:
            state.screensaver_active = False
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    wifi.poll()          # Verbindungsaufbau / Wiederverbindung
    wifi.poll_server()

    now = time.ticks_ms()

    free = gc.mem_free()
    if free < state.min_mem_free:
        state.min_mem_free = free

    if time.ticks_diff(now, last_sensor) >= config.SENSOR_INTERVAL_MS:
        last_sensor = now
        sensors.update_sensor()
        sensors.update_selftest()

    if time.ticks_diff(now, last_history) >= config.HISTORY_INTERVAL_MS:
        last_history = now
        history.record_history()

    if time.ticks_diff(now, last_iaq_save) >= config.IAQ_SAVE_INTERVAL_MS:
        last_iaq_save = now
        state.iaq.save()

    if not state.screensaver_active and time.ticks_diff(now, state.last_activity) >= config.SCREENSAVER_IDLE_MS:
        state.screensaver_active = True
        state.screensaver_x = 0
        state.screensaver_dir = 1
        display.lcd.backlight(config.SCREENSAVER_BRIGHTNESS)

    if state.screensaver_active:
        if time.ticks_diff(now, last_display) >= config.SCREENSAVER_STEP_MS:
            last_display = now
            state.screensaver_x += state.screensaver_dir * config.SCREENSAVER_STEP_PX
            if state.screensaver_x >= display.lcd.width - config.SCREENSAVER_BAR_W or state.screensaver_x <= 0:
                state.screensaver_dir = -state.screensaver_dir
            display.draw_screensaver()
    else:
        if time.ticks_diff(now, last_display) >= config.DISPLAY_INTERVAL_MS:
            last_display = now
            display.draw()

    time.sleep_ms(config.LOOP_SLEEP_MS)

# EOF 2026-09-26
```

### `config.py`

Zentrale Einstellungen: Pins, Takte, Kalibrierwerte, IAQ, WLAN (127 Zeilen)

```python
# config.py
# Zentrale Konfiguration - Pins, Intervalle, Kalibrierwerte, Selbsttest-Grenzen.

# ── Display (SPI) ──────────────────────────────────────────
DISP_CS, DISP_RST, DISP_BL = 9, 12, 13
DISP_SCK, DISP_MOSI, DISP_DC = 10, 11, 8

# ── Sensor (I2C) ───────────────────────────────────────────
I2C_SDA, I2C_SCL = 4, 5
BME_ADDRESS = 0x76  # bestaetigt korrekt - der 0x77-Scan war vermutlich ein
                     # Artefakt der Verbindungsstoerung, die kurz danach zum
                     # kompletten Verbindungsabbruch fuehrte, keine echte
                     # Adressaenderung am Sensor

# ── Kalibrierung ───────────────────────────────────────────
# Kalibrierpaket 2026-09-24, Abgleich gegen SwitchBot (5 cm daneben) und
# Wandsensor: 23.09. 17:22 und 20:37, 24.09. vormittags.
# TEMP_OFFSET wird zum Rohwert ADDIERT (Eigenwaerme -> Sensor liest zu hoch).
# Der BME690 lag mit dem alten Wert -3.4 konstant +0.3..+0.4 C zu hoch.
# Nachkontrolle 24.09. 16:38 und 21:34 mit -3.8: beide Male -0.6 C unter
# SwitchBot/Wandsensor -> Wert auf -3.2 korrigiert (Ursache der Differenz
# zu den Vortagspunkten ungeklaert).
TEMP_OFFSET = -3.2
# Feuchte: erst physikalisch per Magnus auf die korrigierte Temperatur
# umrechnen (gleiche Wasserdampfmenge, kuehlere Luft -> hoehere rel. Feuchte),
# dann HUMIDITY_TRIM in %-Punkten addieren. Der Trim gleicht einen eigenen
# Fehler des Feuchtesensors aus: nach Magnus fehlten +7.2/+7.2/+6.8 Punkte.
# Vorlaeufig additiv; ob Faktor oder Betrag besser passt, zeigt sich erst
# bei deutlich anderer Feuchte (Heizperiode, 35-45 %).
# Ersetzt das fruehere HUMIDITY_OFFSET = 18 (additiv, ohne Magnus).
HUMIDITY_TRIM = 7.0
# DWD-Vergleich (2026-09-xx): BME690 zeigte 1012 hPa bei 1013 hPa Referenz -> zu niedrig.
PRESSURE_OFFSET = 1.0

# ── Heizerprofil ───────────────────────────────────────────
HEATER_TEMP = 320
HEATER_DURATION_MS = 150

# ── Selbsttest-Naeherung ───────────────────────────────────
# Boschs eigener Selbsttest prueft u.a. den internen Heizstrom-Regelwert
# (idac) - der ist ueber diese Bibliothek nicht zugaenglich (bestaetigt per
# REPL: bme.read() liefert keine idac-Werte). Stattdessen: Heizerstabilitaet,
# Gaswert-Gueltigkeit, und Plausibilitaetsspannen fuer alle vier Messgroessen -
# nach dem Vorbild von Boschs eigenem analyze_sensor_data() in bme69x.c.
#
# WICHTIG: TEMP_MIN_C/TEMP_MAX_C/PRES_MIN_HPA/... sind GROSSZUEGIGE, selbst
# gewaehlte Plausibilitaetsgrenzen (z.B. "Zimmertemperatur, kein Vakuum") -
# NICHT Boschs exakte interne Konstanten (BME69X_MIN_TEMPERATURE etc.), die
# in bme69x_defs.h stehen und mir nicht vorliegen. Ziel ist "Sensor komplett
# kaputt/getrennt erkennen", nicht Boschs Werksgrenzen 1:1 nachzubilden.
SELFTEST_WINDOW = 5
GAS_MIN_KOHM = 0.5
GAS_MAX_KOHM = 5000.0
TEMP_MIN_C = -10.0
TEMP_MAX_C = 60.0
PRES_MIN_HPA = 900.0
PRES_MAX_HPA = 1100.0
HUM_MIN_PCT = 0.0
HUM_MAX_PCT = 100.0

# Haupttrend: echte 3-Stunden-Drucktendenz (Standard-Meteorologie, z.B. bei
# METAR/SYNOP-Meldungen so verwendet), nicht mehr nur 30 Minuten. 180 Minuten
# = die volle Ringpuffer-Laenge (siehe HISTORY_SIZE), der Trend braucht also
# ca. 3h Laufzeit, bis er zum ersten Mal verfuegbar ist.
#
# Schwellenwert-Recherche (2026-09-xx): Quellen reichen von ~0.8 hPa/3h
# (Home-Assistant-DIY-Anleitung fuer Hobby-Sensoren, mit dem Hinweis "Startwert,
# keine Naturkonstante") bis ~3 hPa/3h (verbreiteter Seefahrt-/Flugwetter-
# Schwellenwert fuer "Sturmwarnung/Frontdurchgang"). PRESSURE_TREND_THRESHOLD
# ist bewusst dazwischen angesetzt - strenger als der twitchy DIY-Wert (unser
# Sensor hat durchs 1x-Oversampling zusaetzliches Rauschen), aber weit unter
# der Sturmwarnschwelle. Wie immer: Startwert, kein hergeleiteter Fixwert.
PRESSURE_TREND_WINDOW_MIN = 180
PRESSURE_TREND_THRESHOLD = 1.5  # hPa Aenderung ueber das volle Fenster

# "Anklopfen": vergleicht die Steigung der juengsten 10 Minuten gegen die
# davor liegenden 20 Minuten (Luftdruck), um einen Umschwung frueher zu
# erkennen als im 3-Stunden-Gesamttrend. SWING_MINUTES_NEW/OLD und die
# Schwelle sind selbst gewaehlte Startwerte - noch nicht in der Praxis
# gegen echte Wetterwechsel kalibriert.
PRESSURE_SWING_MINUTES_NEW = 10
PRESSURE_SWING_MINUTES_OLD = 20
PRESSURE_SWING_THRESHOLD = 0.05  # hPa/Minute Unterschied, ab dem "auf"/"ab" gilt

# ── Relative IAQ (gemeinsames Modul iaq.py, identisch beim Enviro+) ──
IAQ_HALFLIFE_H = 6.0          # Huellkurven vergessen alte Extremwerte mit dieser Halbwertszeit
IAQ_MIN_RATIO = 2.0           # Mindestspanne hi/lo; gleichbleibende Luft zeigt "gut"
IAQ_WARMUP_S = 1200           # 20 min nach Start: Heizer kalt -> "aufwaermen..."
IAQ_BASELINE_FILE = "iaq_baseline.txt"
IAQ_SAVE_INTERVAL_MS = 300000 # Baseline alle 5 min auf Flash sichern

# ── Takt ───────────────────────────────────────────────────
SENSOR_INTERVAL_MS = 3000   # Paket 2: 3 s statt 1 s -> weniger Heizerwaerme, ruhigere Feuchte
DISPLAY_INTERVAL_MS = 500
HISTORY_INTERVAL_MS = 60_000
HISTORY_SIZE = 181
LOOP_SLEEP_MS = 10

# ── Anzeige ────────────────────────────────────────────────
BRIGHTNESS_LEVELS = (300, 600, 1000)
MODE_NAMES = ("Klima", "Gas / IAQ", "Min / Max", "WLAN", "System")

# ── Bildschirmschoner ──────────────────────────────────────
SCREENSAVER_IDLE_MS = 5 * 60 * 1000   # 5 Minuten Inaktivitaet
SCREENSAVER_BRIGHTNESS = 200           # ~20% von 1000
SCREENSAVER_STEP_MS = 150              # Zeit pro Schritt
SCREENSAVER_STEP_PX = 3                # Pixel pro Schritt (+50% gegenueber vorher)
SCREENSAVER_BAR_W = 14                 # Breite des KITT-Scanner-Segments

# ── WLAN ───────────────────────────────────────────────────
WIFI_HOSTNAME = "PicoBME690Sensor"
WIFI_PM = 0xa11140  # Powersave aus, stabiler als Server
# Wiederverbindung (Paket 1, 2026-09-23): wifi.poll() prueft den Link
# hoechstens alle WIFI_CHECK_MS und startet nach WIFI_RETRY_MS ohne
# Verbindung einen neuen Connect-Versuch - nicht blockierend.
WIFI_CHECK_MS = 1000
WIFI_RETRY_MS = 15000
# Nach so vielen erfolglosen Versuchen Schnittstelle komplett zuruecksetzen.
WIFI_RESET_AFTER = 3
# Laendercode steht in secrets.py (WIFI_COUNTRY); fehlt er dort, gilt dieser.
WIFI_COUNTRY_DEFAULT = "DE"
# WLAN beim Start automatisch einschalten (z. B. im geschlossenen Balkon-
# Gehaeuse, damit das Geraet nach einem Stromausfall ohne Tastendruck
# wieder online kommt). Auskommentiert = WLAN startet aus, CTRL schaltet ein.
# WIFI_AUTOSTART = True

# EOF 2026-09-26
```

### `state.py`

Gemeinsamer Zustand aller Module (42 Zeilen)

```python
# state.py
# Gemeinsamer, veraenderlicher Zustand ueber alle Module hinweg.
# Andere Module schreiben direkt state.last_temp = ... statt "global" zu
# nutzen - "global" wirkt nur innerhalb einer Datei, nicht ueber mehrere.

last_temp = None
last_pres = None
last_hum = None
last_gas = None
last_gas_reliable = False

min_temp = max_temp = None
min_hum = max_hum = None
min_pres = max_pres = None
min_gas = max_gas = None   # echte Extremwerte seit Start (wie Temp/Feuchte)
iaq = None                 # iaq.IAQ-Objekt, in main.py angelegt

history_temp = []
history_hum = []
history_pres = []
history_gas = []

selftest_results = []

wifi_active = False
wlan = None
server = None
ip = None
# Kurzer WLAN-Statustext fuer die System-Seite (z. B. "NOAP", "AUTH").
wifi_note = ""

mode = 0
brightness_idx = 1
boot_time = 0
min_mem_free = 0

screensaver_active = False
screensaver_x = 0
screensaver_dir = 1
last_activity = 0

# EOF 2026-09-26
```

### `sensors.py`

BME690 lesen, Kalibrierung, Selbsttest, Status- und Trendtexte (213 Zeilen)

```python
# sensors.py
# Sensor-Lesen, IAQ-Bewertung, Selbsttest-Naeherung, Statustexte.

import math
import breakout_bme69x as bme69x
from machine import ADC

import config
import state
import colors
import history

bme = None


def _svp(t):
    """Saettigungsdampfdruck nach Magnus in hPa (ueber Wasser)."""
    return 6.112 * math.exp(17.62 * t / (243.12 + t))


def init(i2c):
    """Sensor anlegen und konfigurieren. Einmal beim Start aus main.py rufen."""
    global bme
    bme = bme69x.BreakoutBME69X(i2c, address=config.BME_ADDRESS)
    bme.configure(
        bme69x.FILTER_COEFF_3,
        bme69x.STANDBY_TIME_1000_MS,
        bme69x.OVERSAMPLING_1X,   # Druck
        bme69x.OVERSAMPLING_2X,   # Temperatur
        bme69x.OVERSAMPLING_16X   # Feuchte
    )
    bme.read(heater_temp=config.HEATER_TEMP, heater_duration=config.HEATER_DURATION_MS)


def update_sensor():
    try:
        temp, pressure, humidity, gas, status, _, _ = bme.read(
            heater_temp=config.HEATER_TEMP,
            heater_duration=config.HEATER_DURATION_MS
        )

        t_raw = temp
        temp = t_raw + config.TEMP_OFFSET
        # Magnus: Rohfeuchte gilt fuer die (zu warme) Sensortemperatur,
        # umrechnen auf die korrigierte Temperatur, dann Sensor-Trim.
        humidity = humidity * _svp(t_raw) / _svp(temp) + config.HUMIDITY_TRIM
        humidity = max(0, min(100, humidity))
        pressure = pressure / 100 + config.PRESSURE_OFFSET
        gas = gas / 1000

        state.last_temp = temp
        state.last_pres = pressure
        state.last_hum = humidity
        state.last_gas = gas

        state.min_temp = temp if state.min_temp is None or temp < state.min_temp else state.min_temp
        state.max_temp = temp if state.max_temp is None or temp > state.max_temp else state.max_temp

        state.min_hum = humidity if state.min_hum is None or humidity < state.min_hum else state.min_hum
        state.max_hum = humidity if state.max_hum is None or humidity > state.max_hum else state.max_hum

        state.min_pres = pressure if state.min_pres is None or pressure < state.min_pres else state.min_pres
        state.max_pres = pressure if state.max_pres is None or pressure > state.max_pres else state.max_pres

        state.last_gas_reliable = (
            (status & bme69x.STATUS_GAS_VALID) != 0
            and (status & bme69x.STATUS_HEATER_STABLE) != 0
        )

        if state.last_gas_reliable:
            state.min_gas = gas if state.min_gas is None or gas < state.min_gas else state.min_gas
            state.max_gas = gas if state.max_gas is None or gas > state.max_gas else state.max_gas
        if state.iaq is not None:
            state.iaq.update(gas, state.last_gas_reliable)

    except Exception as error:
        print("Sensorfehler:", error)


def update_selftest():
    """Naeherung an Boschs Selbsttest ueber mehrere Zyklen: Heizer stabil,
    Gaswert gueltig, und jetzt zusaetzlich T/P/H in einer plausiblen Spanne -
    nach dem Vorbild von Boschs eigenem analyze_sensor_data()."""
    if state.last_gas is None:
        return

    gas_ok = config.GAS_MIN_KOHM <= state.last_gas <= config.GAS_MAX_KOHM
    temp_ok = config.TEMP_MIN_C <= state.last_temp <= config.TEMP_MAX_C
    pres_ok = config.PRES_MIN_HPA <= state.last_pres <= config.PRES_MAX_HPA
    hum_ok = config.HUM_MIN_PCT <= state.last_hum <= config.HUM_MAX_PCT

    ok = state.last_gas_reliable and gas_ok and temp_ok and pres_ok and hum_ok

    state.selftest_results.append(ok)
    if len(state.selftest_results) > config.SELFTEST_WINDOW:
        state.selftest_results.pop(0)


def selftest_text():
    """(label, color) - solange das Fenster noch nicht voll ist: 'pruefe...'."""
    if len(state.selftest_results) < config.SELFTEST_WINDOW:
        return "pruefe...", colors.WHITE

    if all(state.selftest_results):
        return "OK", colors.GREEN

    return "Fehler", colors.RED


def internal_temp():
    volt = ADC(4).read_u16() * 3.3 / 65535.0
    return 27.0 - (volt - 0.706) / 0.001721


def iaq_relative(gas):
    """(Prozent 0..100 oder None, Label, Farbe). Paket 2: Score aus iaq.IAQ."""
    score = state.iaq.score(gas) if state.iaq is not None else None
    if score is None:
        return None, "aufwaermen...", colors.GREY

    pct = score * 100

    if pct > 75:
        return pct, "gut", colors.GREEN
    if pct > 45:
        return pct, "maessig", colors.YELLOW
    if pct > 20:
        return pct, "schlecht", colors.RED

    return pct, "sehr schlecht", colors.RED


def comfort_text():
    if state.last_temp is None:
        return "--"

    if 20 <= state.last_temp <= 24 and 40 <= state.last_hum <= 60:
        return "komfortabel"

    if state.last_hum < 40:
        return "eher trocken"

    if state.last_hum > 60:
        return "eher feucht"

    if state.last_temp < 20:
        return "eher kuehl"

    return "eher warm"


def gas_status_text():
    if state.last_gas is None:
        return "warte auf Messung"

    if state.last_gas_reliable:
        return "Gaswert gueltig, Heizer stabil"

    return "Gaswert noch nicht freigegeben"


def pressure_trend():
    change = history.linreg_change(state.history_pres, config.PRESSURE_TREND_WINDOW_MIN)

    if change is None:
        return "warte auf Trenddaten"

    if change > config.PRESSURE_TREND_THRESHOLD:
        return "steigend"

    if change < -config.PRESSURE_TREND_THRESHOLD:
        return "fallend"

    return "stabil"


def weather_trend():
    change = history.linreg_change(state.history_pres, config.PRESSURE_TREND_WINDOW_MIN)

    if change is None:
        return "⏳", "Wettertrend wird berechnet"

    if change > config.PRESSURE_TREND_THRESHOLD:
        return "🌤️", "Wettertrend: freundlich"

    if change < -config.PRESSURE_TREND_THRESHOLD:
        return "🌧️", "Wettertrend: wechselhaft"

    return "☁️", "Wettertrend: stabil"


def pressure_swing():
    """'Anklopfen': 'auf'/'ab'/'neutral', oder None ohne genug Historie -
    siehe history.trend_acceleration() und den Kommentar bei
    config.PRESSURE_SWING_THRESHOLD."""
    diff = history.trend_acceleration(
        state.history_pres,
        config.PRESSURE_SWING_MINUTES_NEW,
        config.PRESSURE_SWING_MINUTES_OLD,
    )

    if diff is None:
        return None

    if diff > config.PRESSURE_SWING_THRESHOLD:
        return "auf"

    if diff < -config.PRESSURE_SWING_THRESHOLD:
        return "ab"

    return "neutral"

# EOF 2026-09-26
```

### `iaq.py`

Relative Luftqualität aus dem Gaswiderstand (identisch im Enviro+-Projekt) (112 Zeilen)

```python
# iaq.py
# Relative Luftqualitaet aus dem Gaswiderstand (BME688/BME690).
# Paket 2 (2026-09-26): gemeinsames Modul fuer Enviro+ und BME690 - beide
# Projekte enthalten diese Datei identisch.
#
# Prinzip: Zwei Huellkurven ueber den Gaswiderstand.
#   hi = "saubere Luft"   (hoechster Wert der juengeren Vergangenheit)
#   lo = "belastete Luft" (niedrigster Wert der juengeren Vergangenheit)
# Score = Lage des aktuellen Werts zwischen lo und hi, logarithmisch
# (Gaswiderstand faellt bei Belastung etwa exponentiell), 0.0 .. 1.0.
#
# Unterschiede zur alten Logik:
#   - Zerfall nach ZEIT (Halbwertszeit in Stunden), nicht pro Messung -
#     der Messtakt spielt keine Rolle mehr.
#   - Mindestspanne als Verhaeltnis hi/lo >= IAQ_MIN_RATIO. Reicht die
#     beobachtete Spanne nicht, wird lo abgesenkt, hi bleibt: gleichbleibend
#     gute Luft zeigt "gut" statt "kalibriert...".
#   - Sperrfrist nach dem Start (IAQ_WARMUP_S): der kalte Heizer liefert
#     anfangs zu niedrige Werte, die frueher die Baseline verdarben.
#   - Baseline auf Flash (IAQ_BASELINE_FILE, Format "lo,hi"), kompatibel
#     mit der bisherigen iaq_baseline.txt des Enviro+.

import math
import time

import config

_MAX_DT_S = 60      # Luecken (z. B. Sensorfehler) zaehlen hoechstens so lange


class IAQ:
    def __init__(self):
        self.ratio = config.IAQ_MIN_RATIO
        self.halflife_s = config.IAQ_HALFLIFE_H * 3600
        self.warmup_ms = config.IAQ_WARMUP_S * 1000
        self.file = config.IAQ_BASELINE_FILE
        self.lo = None
        self.hi = None
        self._t_start = time.ticks_ms()
        self._t_last = None
        self._load()

    # --- Flash --------------------------------------------------------------

    def _load(self):
        try:
            with open(self.file) as f:
                lo, hi = f.read().split(",")
            lo, hi = float(lo), float(hi)
            if 0 < lo < hi:
                self.lo, self.hi = lo, hi
                self._enforce_ratio()
        except Exception:
            self.lo = self.hi = None

    def save(self):
        if self.lo is None:
            return
        try:
            with open(self.file, "w") as f:
                f.write("{:.1f},{:.1f}".format(self.lo, self.hi))
        except Exception:
            pass

    # --- Lernen -------------------------------------------------------------

    def _enforce_ratio(self):
        if self.hi / self.lo < self.ratio:
            self.lo = self.hi / self.ratio

    @property
    def warming_up(self):
        return time.ticks_diff(time.ticks_ms(), self._t_start) < self.warmup_ms

    def update(self, gas_kohm, valid):
        """Nach jeder Messung aufrufen. valid: Gaswert gueltig und Heizer
        stabil (beide Statusbits)."""
        now = time.ticks_ms()
        last, self._t_last = self._t_last, now
        if self.warming_up or not valid or gas_kohm is None or gas_kohm <= 0:
            return
        if self.lo is None:
            self.hi = gas_kohm
            self.lo = gas_kohm / self.ratio
            return
        dt = _MAX_DT_S if last is None else min(time.ticks_diff(now, last) / 1000, _MAX_DT_S)
        keep = math.exp(-0.6931 * dt / self.halflife_s)   # 0.5 ** (dt / T_half)
        # Huellkurven: neuer Extremwert sofort, sonst langsam zum Messwert hin.
        if gas_kohm >= self.hi:
            self.hi = gas_kohm
        else:
            self.hi = gas_kohm + (self.hi - gas_kohm) * keep
        if gas_kohm <= self.lo:
            self.lo = gas_kohm
        else:
            self.lo = gas_kohm + (self.lo - gas_kohm) * keep
        self._enforce_ratio()

    # --- Auswerten ----------------------------------------------------------

    @property
    def ready(self):
        return self.lo is not None and not self.warming_up

    def score(self, gas_kohm):
        """0.0 (belastet) .. 1.0 (sauber) oder None (Aufwaermphase/ohne Daten)."""
        if not self.ready or gas_kohm is None or gas_kohm <= 0:
            return None
        s = math.log(gas_kohm / self.lo) / math.log(self.hi / self.lo)
        return 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)

# EOF 2026-09-26
```

### `history.py`

3-h-Verlauf, Deltas, Ausgleichsgerade, Laufzeit (114 Zeilen)

```python
# history.py
# Verlaufsaufzeichnung und daraus abgeleitete Werte (Deltas, Laufzeit).

import time

import config
import state


def record_history():
    if state.last_temp is None:
        return

    state.history_temp.append(state.last_temp)
    state.history_hum.append(state.last_hum)
    state.history_pres.append(state.last_pres)
    state.history_gas.append(state.last_gas)

    if len(state.history_temp) > config.HISTORY_SIZE:
        state.history_temp.pop(0)
        state.history_hum.pop(0)
        state.history_pres.pop(0)
        state.history_gas.pop(0)


def delta_from_history(values, minutes):
    if len(values) <= minutes:
        return None

    return values[-1] - values[-1 - minutes]


def _linreg_slope(values):
    """Rohe Kleinste-Quadrate-Steigung pro Schritt (hier: pro Minute).
    Eigene Funktion, weil eine reine Rate - anders als eine auf die
    Fensterlaenge hochgerechnete Aenderung - zwischen unterschiedlich
    langen Fenstern direkt vergleichbar bleibt (siehe trend_acceleration)."""
    n = len(values)
    if n < 2:
        return None

    sum_x = n * (n - 1) / 2
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6
    sum_y = 0.0
    sum_xy = 0.0
    for i, y in enumerate(values):
        sum_y += y
        sum_xy += i * y

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return None

    return (n * sum_xy - sum_x * sum_y) / denom


def linreg_change(values, minutes):
    """Kleinste-Quadrate-Ausgleichsgerade ueber die letzten `minutes` Schritte,
    als robustere Alternative zu delta_from_history: alle Punkte im Fenster
    fliessen ein, nicht nur die beiden Randwerte - ein einzelner verrauschter
    Messwert (z.B. durch das reduzierte Druck-Oversampling) kippt damit nicht
    mehr die ganze Trendaussage. Rueckgabe ist die Steigung, hochgerechnet auf
    die volle Fensterlaenge - direkt vergleichbar mit delta_from_history."""
    if len(values) <= minutes:
        return None

    window = values[-(minutes + 1):]
    slope = _linreg_slope(window)
    if slope is None:
        return None

    return slope * (len(window) - 1)


def trend_acceleration(values, new_minutes, old_minutes):
    """Das 'Anklopfen': vergleicht die Steigung (Einheit/Minute) im
    juengsten Fenster gegen das davor liegende, aeltere Fenster - deutet
    sich ein Umschwung an, bevor er im langen Gesamttrend sichtbar wird?
    Rueckgabe ist die Differenz der beiden Steigungen (neu minus alt) in
    Einheit/Minute, oder None ohne genug Historie."""
    total = new_minutes + old_minutes
    if len(values) <= total:
        return None

    new_window = values[-(new_minutes + 1):]
    old_window = values[-(total + 1):-new_minutes]

    new_slope = _linreg_slope(new_window)
    old_slope = _linreg_slope(old_window)

    if new_slope is None or old_slope is None:
        return None

    return new_slope - old_slope


def signed_value(value, decimals=1, unit=""):
    if value is None:
        return "--"

    prefix = "+" if value > 0 else ""
    return (("%s%%.%df" % (prefix, decimals)) % value) + unit


def uptime():
    seconds = time.ticks_diff(time.ticks_ms(), state.boot_time) // 1000

    return "%02d:%02d:%02d" % (
        seconds // 3600,
        seconds % 3600 // 60,
        seconds % 60
    )

# EOF 2026-09-23
```

### `display.py`

LCD-Treiber (ST7735S, 160×80) und Bildschirmseiten (244 Zeilen)

```python
# display.py
# LCD-Treiber (ST7735-artig, 160x80) und der Bildschirmaufbau fuer alle
# fuenf Modi (Klima, Gas/IAQ, Min/Max, WLAN, System).

from machine import Pin, SPI, PWM
import framebuf
import time

import config
import state
import colors
import sensors
import history

lcd = None


class LCD_0inch96(framebuf.FrameBuffer):
    def __init__(self):
        self.width = 160
        self.height = 80

        self.cs = Pin(config.DISP_CS, Pin.OUT, value=1)
        self.rst = Pin(config.DISP_RST, Pin.OUT, value=1)
        self.dc = Pin(config.DISP_DC, Pin.OUT, value=1)

        self.spi = SPI(
            1,
            10_000_000,
            polarity=0,
            phase=0,
            sck=Pin(config.DISP_SCK),
            mosi=Pin(config.DISP_MOSI),
            miso=None
        )

        self.bl = PWM(Pin(config.DISP_BL))
        self.bl.freq(1000)

        self.buffer = bytearray(self.width * self.height * 2)
        super().__init__(
            self.buffer,
            self.width,
            self.height,
            framebuf.RGB565
        )

        self.init_display()

    def cmd(self, value):
        self.dc(0)
        self.cs(0)
        self.spi.write(bytes((value,)))
        self.cs(1)

    def data(self, value):
        self.dc(1)
        self.cs(0)

        if isinstance(value, int):
            self.spi.write(bytes((value,)))
        else:
            self.spi.write(value)

        self.cs(1)

    def backlight(self, value):
        value = max(0, min(value, 1000))
        self.bl.duty_u16(value * 65535 // 1000)

    def init_display(self):
        self.rst(1)
        time.sleep_ms(200)
        self.rst(0)
        time.sleep_ms(200)
        self.rst(1)
        time.sleep_ms(200)

        self.backlight(1000)

        self.cmd(0x11)
        time.sleep_ms(120)
        self.cmd(0x21)

        sequence = (
            (0xB1, b"\x05\x3A\x3A"),
            (0xB2, b"\x05\x3A\x3A"),
            (0xB3, b"\x05\x3A\x3A\x05\x3A\x3A"),
            (0xB4, b"\x03"),
            (0xC0, b"\x62\x02\x04"),
            (0xC1, b"\xC0"),
            (0xC2, b"\x0D\x00"),
            (0xC3, b"\x8D\x6A"),
            (0xC4, b"\x8D\xEE"),
            (0xC5, b"\x0E"),
            (0xE0, b"\x10\x0E\x02\x03\x0E\x07\x02\x07"
                   b"\x0A\x12\x27\x37\x00\x0D\x0E\x10"),
            (0xE1, b"\x10\x0E\x03\x03\x0F\x06\x02\x08"
                   b"\x0A\x13\x26\x36\x00\x0D\x0E\x10"),
            (0x3A, b"\x05"),
            (0x36, b"\xA8"),
        )

        for command, values in sequence:
            self.cmd(command)
            self.data(values)

        self.cmd(0x29)

    def show(self):
        self.cmd(0x2A)
        self.data(b"\x00\x01\x00\xA0")

        self.cmd(0x2B)
        self.data(b"\x00\x1A\x00\x69")

        self.cmd(0x2C)
        self.dc(1)
        self.cs(0)
        self.spi.write(self.buffer)
        self.cs(1)

    def text_right(self, text, y, color, right=155):
        self.text(text, right - len(text) * 8, y, color)


def init():
    """LCD anlegen. Einmal beim Start aus main.py rufen."""
    global lcd
    lcd = LCD_0inch96()


def draw():
    lcd.fill(colors.BLACK)
    lcd.text(config.MODE_NAMES[state.mode], 5, 4, colors.GREY)

    if state.wifi_active:
        lcd.text_right("WLAN", 4, colors.GREEN)

    lcd.fill_rect(0, 16, 160, 2, colors.GREY)

    if state.last_temp is None:
        lcd.text("warte auf Sensor...", 5, 30, colors.GREY)

    elif state.mode == 0:
        values = (
            ("%.1fC" % state.last_temp, "Temperatur", 26, colors.AMBER),
            ("%.0f%%" % state.last_hum, "Feuchte", 42, colors.CYAN),
            ("%.0fhPa" % state.last_pres, "Druck", 58, colors.LIGHTBLUE)
        )

        for value, label, y, color in values:
            lcd.text(value, 5, y, color)
            lcd.text_right(label, y, colors.LIGHTGREY)

    elif state.mode == 1:
        pct, label, color = sensors.iaq_relative(state.last_gas)

        lcd.text("%.0f kOhm" % state.last_gas, 5, 26, colors.WHITE)
        lcd.text(label, 5, 42, color)

        if pct is not None:
            lcd.text_right("%.0f%%" % pct, 42, colors.GREY)

    elif state.mode == 2:
        values = (
            ("Temp", state.min_temp, state.max_temp, 20, colors.LIGHTBLUE, colors.LIGHTRED, "%.1f"),
            ("Feuchte", state.min_hum, state.max_hum, 36, colors.LIGHTRED, colors.LIGHTBLUE, "%.0f"),
            ("Druck", state.min_pres, state.max_pres, 52, colors.DARKBLUE, colors.LIGHTCYAN, "%.0f")
        )

        for label, low, high, y, low_color, high_color, fmt in values:
            lcd.text(label, 5, y, colors.LIGHTGREY)
            lcd.text(fmt % low, 70, y, low_color)
            lcd.text(fmt % high, 115, y, high_color)

            if label == "Druck":
                swing_char = {"auf": "^", "ab": "v"}.get(sensors.pressure_swing(), "")
                if swing_char:
                    lcd.text(swing_char, 55, y, colors.WHITE)

    elif state.mode == 3:
        connected = state.wifi_active and state.wlan is not None and state.wlan.isconnected()

        lcd.text("Status", 5, 20, colors.LIGHTGREY)
        lcd.text_right(
            "ONLINE" if connected else ((state.wifi_note or "LINK?") if state.wifi_active else "OFFLINE"),
            20,
            colors.GREEN if connected else colors.RED
        )

        lcd.text("IP", 5, 36, colors.LIGHTGREY)
        lcd.text_right(state.ip or "--", 36, colors.LIGHTBLUE)

        lcd.text("Laufzeit", 5, 52, colors.LIGHTGREY)
        lcd.text_right(history.uptime(), 52, colors.WHITE)

    else:
        label, color = sensors.selftest_text()

        lcd.text("Pico-Temp", 5, 20, colors.LIGHTGREY)
        lcd.text_right("%.0fC" % sensors.internal_temp(), 20, colors.AMBER)

        lcd.text("Selbsttest", 5, 36, colors.LIGHTGREY)
        lcd.text_right(label, 36, color)

        lcd.text("RAM min", 5, 52, colors.LIGHTGREY)
        lcd.text_right("%d" % state.min_mem_free, 52, colors.YELLOW)

    lcd.fill_rect(0, 66, 160, 2, colors.GREY)
    lcd.text("CTRL WLAN A/B<>Mode", 2, 72, colors.GREY)
    lcd.show()


def draw_screensaver():
    """Horizontaler Scanner mit verblassendem Schweif, angelehnt an die
    K.I.T.T.-Lauflicht-Optik: heller Kopf (RED), vier dahinter verblassende
    Segmente - bewusst nur bestehende, bestaetigte Farbkonstanten statt neu
    berechneter Zwischentoene (die letzten beiden Segmente wiederholen GREY,
    da uns keine weiteren verifizierten, noch dunkleren Rot-/Grautoene
    vorliegen)."""
    bar_w = config.SCREENSAVER_BAR_W
    bar_h = 16
    y = (lcd.height - bar_h) // 2
    step = 16  # Versatz zwischen den Schweif-Segmenten

    x = state.screensaver_x
    d = state.screensaver_dir

    lcd.fill(colors.BLACK)

    # Schweif zuerst zeichnen (am weitesten hinten zuerst), Kopf zuletzt -
    # damit der Kopf bei Ueberlappung immer obenauf sichtbar bleibt.
    tail_colors = (colors.LIGHTRED, colors.GREY, colors.GREY, colors.GREY)
    for i in range(4, 0, -1):
        seg_x = x - d * step * i
        if 0 <= seg_x <= lcd.width - bar_w:
            lcd.fill_rect(seg_x, y, bar_w, bar_h, tail_colors[i - 1])

    lcd.fill_rect(x, y, bar_w, bar_h, colors.RED)

    lcd.show()

# EOF 2026-09-24
```

### `colors.py`

Farbkonstanten (BGR565) (20 Zeilen)

```python
# colors.py
# Farbkonstanten im BGR565-Format. Eigenes, abhaengigkeitsfreies Modul, damit
# sowohl display.py als auch sensors.py (selftest_text/iaq_relative geben
# Farben zurueck) sie nutzen koennen, ohne sich gegenseitig zu importieren.

BLACK = 0x0000
WHITE = 0xFFFF
GREY = 0x6D6B
LIGHTGREY = 0x59CE
AMBER = 0x80FD
CYAN = 0xFB06
GREEN = 0xE007
YELLOW = 0xE0FF
RED = 0x00F8
LIGHTBLUE = 0xBF64
LIGHTRED = 0x2CFB
DARKBLUE = 0x9602
LIGHTCYAN = 0x3F97

# EOF 2026-09-23
```

### `web.py`

HTML-Dashboard mit SVG-Verläufen, JSON-Endpoint /data (740 Zeilen)

```python
# web.py
# HTML-Dashboard, JSON-Endpoint, HTTP-Antworten senden/empfangen.

import gc

import config
import state
import sensors
import history


# Paket 2: Umlaute und Grad-Zeichen im Web-Dashboard. Das LCD bleibt bei
# ASCII (die eingebaute 8x8-Schrift von framebuf kennt keine Umlaute), deshalb
# liefern sensors.py-Texte weiter ASCII, und erst hier wird uebersetzt.
_DE = (
    ("aufwaermen...", "Aufwärmphase"),
    ("maessig", "mäßig"),
    ("gueltig", "gültig"),
    ("kuehl", "kühl"),
    ("pruefe", "prüfe"),
)


def _de(text):
    for ascii_text, german in _DE:
        text = text.replace(ascii_text, german)
    return text


def sparkline(values, color, min_span=0):
    # Paket 2: ganze Historie zeichnen (bis 3 h). Vorher stand hier
    # values[-60:] - das Diagramm zeigte nur die letzte Stunde, obwohl
    # Ueberschrift und "3h: ... bis ..." drei Stunden versprachen.

    if len(values) < 2:
        return (
            '<div class="chart-empty">'
            'Verlauf wird aufgebaut ...'
            '</div>'
        )

    low = min(values)
    high = max(values)

    # Mindesthoehe der Skala: sonst blaest die Autoskalierung kleinste
    # Schwankungen (0,1 C, 1 %) auf die volle Hoehe auf.
    if high - low < min_span:
        mid = (high + low) / 2
        low = mid - min_span / 2
        high = mid + min_span / 2

    span = high - low

    if span == 0:
        span = 1

    width = 320
    height = 70
    points = []

    for index, value in enumerate(values):
        x = index * width // (len(values) - 1)
        y = height - 5 - int((value - low) * (height - 10) / span)
        points.append("%d,%d" % (x, y))

    return (
        '<svg class="chart" viewBox="0 0 320 70" preserveAspectRatio="none">'
        '<polyline fill="none" stroke="%s" stroke-width="3" '
        'points="%s" />'
        '</svg>'
    ) % (color, " ".join(points))


def iaq_overlay():
    values = state.history_gas

    if len(values) < 2 or state.iaq is None or not state.iaq.ready:
        return (
            '<div class="overlay-empty" id="gas-overlay-box">'
            'IAQ-Trend wird aufgebaut ...'
            '</div>'
        )

    width = 320
    height = 46
    points = []

    for index, gas in enumerate(values):
        pct = (state.iaq.score(gas) or 0) * 100
        x = index * width // (len(values) - 1)
        y = height - 5 - int(pct * (height - 10) / 100)
        points.append("%d,%d" % (x, y))

    return (
        '<div class="iaq-overlay" id="gas-overlay-box">'
        '<svg viewBox="0 0 320 46" preserveAspectRatio="none">'
        '<polyline fill="none" stroke="rgba(255,255,255,0.75)" '
        'stroke-width="4" points="%s" />'
        '</svg>'
        '</div>'
    ) % " ".join(points)


def chart_card(title, values, color, unit, decimals=1, min_span=0):
    if values:
        current = ("%." + str(decimals) + "f") % values[-1]
        low = ("%." + str(decimals) + "f") % min(values)
        high = ("%." + str(decimals) + "f") % max(values)
        summary = "3h: %s bis %s %s" % (low, high, unit)
    else:
        current = "--"
        summary = "Noch keine Verlaufspunkte"

    return """<div class="chart-card">
<div class="chart-head"><span>%s</span><strong>%s %s</strong></div>
%s
<div class="chart-footer">%s</div>
</div>""" % (
        title,
        current,
        unit,
        sparkline(values, color, min_span),
        summary
    )


def pressure_chart():
    if state.history_pres:
        summary = "3h: %.1f bis %.1f hPa" % (min(state.history_pres), max(state.history_pres))
    else:
        summary = "Noch keine Verlaufspunkte"

    return """<div class="chart-card" id="pressure-card">
<div class="chart-head">
<span>Luftdruck</span>
<strong>%s hPa</strong>
</div>
%s
<div class="chart-footer">%s</div>
</div>""" % (
        "%.0f" % state.last_pres if state.last_pres is not None else "--",
        sparkline(state.history_pres, "#7fb3d5", 2),
        summary,
    )


def weather_banner():
    emoji, text = sensors.weather_trend()
    swing = sensors.pressure_swing()
    swing_symbol = {"auf": "&#8593;", "ab": "&#8595;"}.get(swing, "&#8212;")

    return """<div class="weather-box weather-box-full">
<div class="weather-emoji">%s</div>
<div class="trend-swing">10 min <span class="swing-arrow">%s</span> 20 min</div>
<div><strong>%s</strong><br><small>%s</small></div>
</div>""" % (
        emoji,
        swing_symbol,
        text,
        sensors.pressure_trend()
    )


def gas_chart():
    if state.last_gas is not None:
        pct, _, _ = sensors.iaq_relative(state.last_gas)
    else:
        pct = None

    marker_position = 50 if pct is None else int(pct)
    gas_10m = history.delta_from_history(state.history_gas, 10)

    return """<div class="chart-card">
<div class="chart-head">
<span>Gaswiderstand</span>
<strong>%s kOhm</strong>
</div>
<div class="iaq-scale">
<div class="iaq-marker" style="left:%d%%"></div>
</div>
<div class="iaq-legend">
<span>sehr schlecht</span><span>mäßig</span><span>gut</span>
</div>
%s
<div class="iaq-trend-text">IAQ-Trend: %s</div>
</div>""" % (
        "%.0f" % state.last_gas if state.last_gas is not None else "--",
        marker_position,
        iaq_overlay(),
        "Aufwärmphase" if pct is None else (
            "zunehmend besser" if gas_10m is not None and gas_10m > 0
            else "stabil bis fallend"
        )
    )


def json_data():
    if state.last_gas is not None:
        pct, label, _ = sensors.iaq_relative(state.last_gas)
    else:
        pct, label = None, "--"

    temp_10m = history.delta_from_history(state.history_temp, 10)
    hum_10m = history.delta_from_history(state.history_hum, 10)
    # Paket 1 (2026-09-23): dieselbe Ausgleichsgerade wie
    # sensors.pressure_trend() - vorher rechnete das JSON mit nur zwei
    # Randpunkten, und beide Aussagen konnten sich widersprechen.
    pres_3h = history.linreg_change(state.history_pres, config.PRESSURE_TREND_WINDOW_MIN)
    gas_10m = history.delta_from_history(state.history_gas, 10)

    def value(number, fmt):
        return fmt % number if number is not None else "--"

    return (
        '{"temp":"%s","hum":"%s","pres":"%s","gas":"%s",'
        '"iaq":"%s","gas_status":"%s","comfort":"%s",'
        '"pressure_trend":"%s","temp_trend":"%s",'
        '"hum_trend":"%s","pres_trend":"%s",'
        '"gas_trend":"%s","uptime":"%s"}'
    ) % (
        value(state.last_temp, "%.1f"),
        value(state.last_hum, "%.0f"),
        value(state.last_pres, "%.0f"),
        value(state.last_gas, "%.0f"),
        _de(label),
        _de(sensors.gas_status_text()),
        _de(sensors.comfort_text()),
        sensors.pressure_trend(),
        history.signed_value(temp_10m, 1, " °C / 10 min"),
        history.signed_value(hum_10m, 0, " % / 10 min"),
        history.signed_value(pres_3h, 1, " hPa / 3 h"),
        history.signed_value(gas_10m, 0, " kOhm / 10 min"),
        history.uptime()
    )


def html_page():
    if state.last_gas is not None:
        _, label, _ = sensors.iaq_relative(state.last_gas)
    else:
        label = "--"

    iaq_color = {
        "gut": "#2ecc71",
        "maessig": "#f39c12",
        "schlecht": "#e74c3c",
        "sehr schlecht": "#8e44ad"
    }.get(label, "#888")

    def value(number, fmt):
        return fmt % number if number is not None else "--"

    def minmax(low, high, fmt):
        if low is None:
            return "--"

        return "min " + fmt % low + " &middot; max " + fmt % high

    charts = (
        chart_card("Temperatur", state.history_temp, "#f5b041", "°C", 1, 1.0) +
        chart_card("Luftfeuchte", state.history_hum, "#4fc3f7", "%", 0, 4) +
        pressure_chart() +
        gas_chart()
    )

    return """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>PicoBME690</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #1a1a2e;
    color: #eee;
    margin: 0;
    padding: 20px;
}

h1 {
    color: #00d4ff;
    text-align: center;
    font-size: 1.45em;
    margin-bottom: 20px;
}

h2 {
    max-width: 620px;
    margin: 28px auto 12px;
    color: #9bb7ff;
    font-size: 1em;
}

.grid, .chart-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    max-width: 620px;
    margin: 0 auto;
}

.card, .iaq-card, .chart-card {
    background: #16213e;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
    border: 1px solid #0f3460;
}

.card .label, .iaq-card .label {
    font-size: 0.75em;
    color: #aaa;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
}

.card .value {
    font-size: 1.8em;
    font-weight: bold;
    color: #00d4ff;
}

.card .subvalue {
    color: #8ea6d7;
    font-size: 0.72em;
    margin-top: 7px;
}

.card .minmax, .iaq-card .minmax {
    font-size: 0.7em;
    color: #6a7ba5;
    margin-top: 6px;
}

.iaq-card {
    grid-column: 1 / -1;
}

.iaq-value {
    font-size: 2em;
    font-weight: bold;
    color: %s;
    text-align: center;
}

.status {
    text-align: center;
    color: #9bb7ff;
    font-size: 0.72em;
    margin-top: 8px;
}

.chart-card {
    padding: 12px;
    min-width: 0;
    display: flex;
    flex-direction: column;
}

.chart-head {
    display: flex;
    justify-content: space-between;
    color: #aaa;
    font-size: 0.72em;
    margin-bottom: 8px;
}

.chart-head strong {
    color: #eee;
    font-size: 1.05em;
}

.chart {
    width: 100%%;
    flex: 1;
    min-height: 70px;
    max-height: 180px;
    background: #101a31;
    border-radius: 6px;
}

.chart-empty {
    flex: 1;
    min-height: 70px;
    max-height: 180px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6a7ba5;
    font-size: 0.7em;
    background: #101a31;
    border-radius: 6px;
}

.overlay-empty {
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6a7ba5;
    font-size: 0.7em;
    background: #101a31;
    border-radius: 6px;
}

.chart-footer {
    color: #6a7ba5;
    font-size: 0.68em;
    margin-top: 6px;
}

.weather-box {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    text-align: left;
    background: #101a31;
    border-radius: 7px;
    padding: 10px;
    margin-top: 10px;
    font-size: 0.75em;
}

.weather-box-full {
    grid-column: 1 / -1;
    margin-top: 0;
}

.trend-swing {
    font-size: 0.72em;
    color: #8095c5;
    white-space: nowrap;
}

.swing-arrow {
    font-size: 1.3em;
    color: #eee;
    padding: 0 2px;
}

.weather-emoji {
    font-size: 2em;
}

.weather-box strong {
    color: #b9d8ff;
}

.weather-box small {
    color: #8095c5;
}

.iaq-scale {
    position: relative;
    height: 17px;
    border-radius: 10px;
    background: linear-gradient(
        90deg,
        #8e44ad 0%%,
        #e74c3c 25%%,
        #f39c12 50%%,
        #f1e05a 70%%,
        #2ecc71 100%%
    );
    margin: 15px 3px 7px;
}

.iaq-marker {
    position: absolute;
    top: -5px;
    width: 9px;
    height: 27px;
    border-radius: 5px;
    transform: translateX(-50%%);
    background: rgba(255,255,255,0.9);
    box-shadow: 0 0 0 2px rgba(0,0,0,0.3);
}

.iaq-legend {
    display: flex;
    justify-content: space-between;
    color: #a8afc1;
    font-size: 0.62em;
}

.iaq-trend-text {
    text-align: center;
    color: #6a7ba5;
    font-size: 0.72em;
    margin: 6px 0 0;
}

.iaq-overlay {
    height: 36px;
    background: linear-gradient(
        180deg,
        rgba(255,255,255,0.03),
        rgba(255,255,255,0.12)
    );
    border-radius: 6px;
    overflow: hidden;
}

.iaq-overlay svg {
    width: 100%%;
    height: 100%%;
}

.footer {
    text-align: center;
    color: #7a8bb5;
    font-size: 0.75em;
    max-width: 620px;
    margin: 20px auto 0;
    padding-top: 12px;
    border-top: 1px solid #2a3a5c;
}

@media (max-width: 500px) {
    .chart-grid {
        grid-template-columns: 1fr;
    }
}
</style>
</head>

<body>
<h1>PicoBME690 &#x1F321;&#xFE0F; Wetterstation</h1>

<div class="grid">

<div class="card">
<div class="label">Temperatur</div>
<div class="value" id="temp">%s&deg;C</div>
<div class="subvalue" id="temp-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Luftfeuchte</div>
<div class="value" id="hum">%s%%</div>
<div class="subvalue" id="hum-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Luftdruck</div>
<div class="value" id="pres">%s hPa</div>
<div class="subvalue" id="pres-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Gaswiderstand</div>
<div class="value" id="gas">%s kOhm</div>
<div class="subvalue" id="gas-trend">--</div>
<div class="minmax">%s</div>
</div>

%s

<div class="iaq-card">
<div class="label">Luftqualität (relativ)</div>
<div class="iaq-value" id="iaq">%s</div>
<div class="status" id="gas-status">%s</div>
<div class="minmax">
Komfort: <span id="comfort">%s</span>
&middot;
Luftdruck: <span id="pressure-trend">%s</span>
</div>
</div>

</div>

<h2>Verlauf der letzten drei Stunden</h2>
<div class="chart-grid">
%s
</div>

<div class="footer">
Messwerte alle 5 s aktualisiert | Diagramme jede Minute aktualisiert<br>
IP: %s | Laufzeit: <span id="uptime">%s</span> | Pico: ~%s °C (grob)
</div>

<script>
function setText(id, value) {
    var node = document.getElementById(id);
    if (node) {
        node.textContent = value;
    }
}

function syncGasBoxHeight() {
    var card = document.getElementById("pressure-card");
    var gasBox = document.getElementById("gas-overlay-box");
    if (!card || !gasBox) {
        return;
    }
    var refBox = card.querySelector(".chart, .chart-empty");
    if (!refBox) {
        return;
    }
    gasBox.style.height = refBox.offsetHeight + "px";
}

function refreshValues() {
    fetch("/data", {cache: "no-store"})
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            setText("temp", data.temp + " °C");
            setText("hum", data.hum + "%%");
            setText("pres", data.pres + " hPa");
            setText("gas", data.gas + " kOhm");
            setText("iaq", data.iaq);
            setText("gas-status", data.gas_status);
            setText("comfort", data.comfort);
            setText("pressure-trend", data.pressure_trend);
            setText("temp-trend", data.temp_trend);
            setText("hum-trend", data.hum_trend);
            setText("pres-trend", data.pres_trend);
            setText("gas-trend", data.gas_trend);
            setText("uptime", data.uptime);
        })
        .catch(function() {});
}

refreshValues();
syncGasBoxHeight();
setInterval(refreshValues, 5000);
window.addEventListener("resize", syncGasBoxHeight);
</script>

</body>
</html>""" % (
        iaq_color,
        value(state.last_temp, "%.1f"),
        minmax(state.min_temp, state.max_temp, "%.1f"),
        value(state.last_hum, "%.0f"),
        minmax(state.min_hum, state.max_hum, "%.0f"),
        value(state.last_pres, "%.0f"),
        minmax(state.min_pres, state.max_pres, "%.0f"),
        value(state.last_gas, "%.0f"),
        minmax(state.min_gas, state.max_gas, "%.0f"),
        weather_banner(),
        _de(label),
        _de(sensors.gas_status_text()),
        _de(sensors.comfort_text()),
        sensors.pressure_trend(),
        charts,
        state.ip or "--",
        history.uptime(),
        "%.0f" % sensors.internal_temp()
    )


def send_all(conn, data):
    view = memoryview(data)
    offset = 0

    while offset < len(view):
        sent = conn.send(view[offset:])

        if sent is None or sent <= 0:
            raise OSError("Verbindung beim Senden geschlossen")

        offset += sent


def send_response(conn, content_type, body, status="200 OK"):
    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ) % (status, content_type, len(body))

    send_all(conn, header.encode("utf-8"))
    send_all(conn, body)


def _drain(conn):
    """Ungelesene Anfragedaten verwerfen, bevor close() laeuft. Liegen noch
    Bytes im Empfangspuffer (z.B. Anfrage > 1024 Bytes durch Cookies),
    schickt lwIP beim close() ein RST statt FIN - der Browser meldet dann
    ERR_CONNECTION_RESET, obwohl die Antwort vollstaendig ankam."""
    try:
        conn.setblocking(False)
        for _ in range(8):
            if not conn.recv(256):
                break
    except Exception:
        pass


def handle_request(conn):
    try:
        conn.settimeout(2)
        request = conn.recv(1024)

        if not request:
            return

        if request.startswith(b"GET /favicon.ico"):
            send_response(conn, "text/plain", b"", "204 No Content")

        elif request.startswith(b"GET /data"):
            gc.collect()
            body = json_data().encode("utf-8")
            send_response(conn, "application/json; charset=utf-8", body)

        else:
            gc.collect()
            body = html_page().encode("utf-8")
            send_response(conn, "text/html; charset=utf-8", body)

    except OSError as error:
        code = error.args[0] if error.args else 0

        # Normale Browserabbrüche nicht in der REPL ausgeben.
        if code not in (104, 110):
            print("Webserverfehler:", error)

    except Exception as error:
        print("Webserverfehler:", error)

    finally:
        _drain(conn)
        conn.close()
        gc.collect()

# EOF 2026-09-26
```

### `wifi.py`

WLAN-Zustandsautomat mit Wiederverbindung und Webserver-Polling (248 Zeilen)

```python
# wifi.py
# WLAN an/aus (Taste CTRL), Wiederverbindung und Server-Polling.
#
# Paket 1 (2026-09-23): nicht blockierender Zustandsautomat statt der
# alten 10-s-Warteschleife. Drei Zustaende:
#   OFF        - WLAN aus (state.wifi_active == False)
#   CONNECTING - Verbindung laeuft, alle WIFI_RETRY_MS neuer Versuch
#   CONNECTED  - verbunden, Webserver-Socket offen
# Faellt der Link weg (Router-Neustart), schliesst poll() den verwaisten
# Server-Socket, verbindet neu und oeffnet danach einen FRISCHEN Socket.
# Aendert sich die IP ohne Linkverlust, baut poll() den Socket ebenfalls neu.
#
# Fix 2026-09-24: Der Pico hing nach dem Start dauerhaft in CONNECTING,
# ohne jede Meldung. Jetzt:
#   - jeder Fehlversuch schreibt den Funkchip-Status in die REPL und als
#     Kurztext auf die System-Seite (state.wifi_note),
#   - vor jedem neuen connect() wird die alte Verbindung getrennt,
#   - nach WIFI_RESET_AFTER Fehlversuchen wird die Schnittstelle komplett
#     aus- und wieder eingeschaltet (wie zweimal CTRL von Hand),
#   - _enable() raeumt beim Start einen haengengebliebenen Chip-Zustand
#     aus einer vorherigen Sitzung (Soft-Reset/Thonny) ab.
#
# WLAN-Angleich (2026-09-25): Das Enviro+ arbeitet jetzt nach demselben
# Muster. Neu hier nur: Meldung, falls der Laendercode nicht greift.

import network
import socket
import time

import config
import state
import secrets
import web

_OFF = 0
_CONNECTING = 1
_CONNECTED = 2

_mode = _OFF
_t_connect = 0   # Start des aktuellen Connect-Versuchs
_t_check = 0     # letzte Linkpruefung
_fails = 0       # Fehlversuche seit dem letzten Erfolg
_country_reported = False


def _status_text():
    """Funkchip-Status als (Kurztext, Klartext). Zahlen als Rueckfall,
    falls die Firmware eine Konstante nicht definiert."""
    try:
        st = state.wlan.status()
    except Exception:
        return "?", "Status nicht lesbar"
    table = (
        (getattr(network, "STAT_WRONG_PASSWORD", -3), "AUTH", "falsches Passwort"),
        (getattr(network, "STAT_NO_AP_FOUND", -2), "NOAP", "Netz nicht gefunden"),
        (getattr(network, "STAT_CONNECT_FAIL", -1), "FAIL", "Verbindung abgelehnt"),
        (getattr(network, "STAT_IDLE", 0), "IDLE", "kein Versuch aktiv"),
        (getattr(network, "STAT_CONNECTING", 1), "JOIN", "verbindet noch"),
        (2, "NOIP", "verbunden, aber keine IP (DHCP)"),
    )
    for code, short, text in table:
        if st == code:
            return short, text + " (" + str(st) + ")"
    return "S" + str(st), "Status " + str(st)


def _set_country():
    """Ländercode VOR wlan.active(True) setzen. Neuere Firmware kennt
    network.country(), aeltere nur rp2.country() - beides versuchen."""
    global _country_reported
    code = getattr(secrets, "WIFI_COUNTRY", config.WIFI_COUNTRY_DEFAULT)
    try:
        network.country(code)
        return
    except Exception:
        pass
    try:
        import rp2
        rp2.country(code)
        return
    except Exception:
        pass
    if not _country_reported:
        print("WLAN: Laendercode", code, "liess sich nicht setzen -",
              "Kanal 12/13 evtl. unsichtbar")
        _country_reported = True


def _close_server():
    if state.server is not None:
        try:
            state.server.close()
        except Exception:
            pass
    state.server = None


def _open_server():
    _close_server()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 80))
    s.listen(3)
    s.setblocking(False)
    state.server = s


def _start_connect():
    global _mode, _t_connect
    try:
        state.wlan.disconnect()   # alten, evtl. haengenden Versuch beenden
    except Exception:
        pass
    try:
        state.wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    except Exception as error:
        print("WLAN-Connect-Fehler:", error)
    _mode = _CONNECTING
    _t_connect = time.ticks_ms()


def _power_up():
    """Schnittstelle sauber aus- und wieder einschalten. Blockiert kurz
    (einige hundert ms), laeuft aber nur beim Start und nach mehreren
    Fehlversuchen."""
    _set_country()
    if state.wlan is None:
        state.wlan = network.WLAN(network.STA_IF)
    try:
        state.wlan.disconnect()
    except Exception:
        pass
    state.wlan.active(False)
    time.sleep_ms(200)
    state.wlan.active(True)
    try:
        state.wlan.config(pm=config.WIFI_PM)
        state.wlan.config(hostname=config.WIFI_HOSTNAME)
    except Exception:
        pass


def _enable():
    global _fails
    _power_up()
    state.wifi_active = True
    state.ip = None
    state.wifi_note = ""
    _fails = 0
    _start_connect()
    print("WLAN: verbinde...")


def _disable():
    global _mode
    _close_server()
    if state.wlan is not None:
        try:
            state.wlan.disconnect()
            state.wlan.active(False)
        except Exception:
            pass
    state.wifi_active = False
    state.ip = None
    state.wifi_note = ""
    _mode = _OFF
    print("WLAN deaktiviert")


def toggle_wifi():
    """Kehrt sofort zurueck - den Verbindungsaufbau erledigt poll()."""
    if state.wifi_active:
        _disable()
    else:
        _enable()


def poll():
    """Jede Schleifenrunde aufrufen. Prueft den Link hoechstens alle
    WIFI_CHECK_MS - isconnected() ist ein Aufruf an den Funkchip."""
    global _mode, _t_check, _fails
    if _mode == _OFF:
        return

    now = time.ticks_ms()
    if time.ticks_diff(now, _t_check) < config.WIFI_CHECK_MS:
        return
    _t_check = now

    linked = state.wlan.isconnected()

    if _mode == _CONNECTING:
        if linked:
            state.ip = state.wlan.ifconfig()[0]
            try:
                _open_server()
                _mode = _CONNECTED
                _fails = 0
                state.wifi_note = ""
                print("Webserver: http://" + state.ip)
            except Exception as error:
                # Socket-Fehler: beim naechsten Check erneut versuchen.
                print("Server-Start fehlgeschlagen:", error)
        elif time.ticks_diff(now, _t_connect) > config.WIFI_RETRY_MS:
            _fails += 1
            short, text = _status_text()
            state.wifi_note = short
            print("WLAN: Versuch", _fails, "erfolglos -", text)
            if _fails % config.WIFI_RESET_AFTER == 0:
                print("WLAN: setze Schnittstelle zurueck")
                try:
                    _power_up()
                except Exception as error:
                    print("WLAN-Reset fehlgeschlagen:", error)
            _start_connect()
        return

    # _CONNECTED
    if not linked:
        print("WLAN: Verbindung verloren, verbinde neu...")
        _close_server()
        state.ip = None
        _start_connect()
        return

    ip = state.wlan.ifconfig()[0]
    if ip != state.ip or state.server is None:
        print("WLAN: IP", ip, "- Server-Socket (neu) oeffnen")
        state.ip = ip
        try:
            _open_server()
        except Exception as error:
            print("Server-Neustart fehlgeschlagen:", error)
            _close_server()


def poll_server():
    if state.server is None:
        return

    try:
        conn, _ = state.server.accept()
    except OSError:
        return  # kein wartender Client - normal bei non-blocking accept()

    web.handle_request(conn)

# EOF 2026-09-25
```

