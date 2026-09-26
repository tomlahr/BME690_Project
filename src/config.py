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
