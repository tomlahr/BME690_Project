# PicoBME690 - Modulare Wetterstation

Raspberry Pi Pico + Waveshare LCD-0.96 + Bosch BME690 (Temperatur, Luftfeuchte,
Luftdruck, Gaswiderstand/IAQ). MicroPython, kein externes Framework - reine
Standardbibliothek (`machine`, `framebuf`, `network`, `socket`) plus Pimoronis
`breakout_bme69x`-Treiber.

## Dateien -> Pico

Alle zehn Dateien flach ins Wurzelverzeichnis kopieren, keine Unterordner:

    config.py
    secrets.py
    colors.py
    state.py
    history.py
    sensors.py
    display.py
    web.py
    wifi.py
    main.py

**Falls du schon eine eigene `secrets.py` auf dem Pico hast: nicht mit der
hier beigelegten Platzhalter-Version überschreiben.**

## Architektur: state.py als gemeinsamer Zustand

Eine monolithische `main.py` kann alle Messwerte als einfache globale
Variablen halten, weil dort auch alle Funktionen sitzen, die per `global`
draufzugreifen. Über mehrere Dateien verteilt gibt's kein gemeinsames
"global" mehr. Lösung: `state.py` hält nur die gemeinsamen Werte
(`last_temp`, `min_gas`, `wifi_active`, `screensaver_active`, ...), alle
anderen Module lesen/schreiben direkt `state.last_temp = ...` statt
`global last_temp` zu deklarieren.

## Zuordnung der Module

| Bereich                                                      | Datei          |
|---------------------------------------------------------------|----------------|
| Konstanten (Pins, Offsets, Intervalle, Selbsttest-Grenzen)     | `config.py`    |
| Farbkonstanten                                                 | `colors.py`    |
| Gemeinsamer Zustand (`last_temp`, `wifi_active`, ...)          | `state.py`     |
| Verlauf, Trends (`record_history`, `linreg_change`, `trend_acceleration`, `uptime`) | `history.py` |
| Sensor-Lesen, Selbsttest, IAQ, Wettertrend (`update_sensor`, `update_selftest`, `pressure_swing`, ...) | `sensors.py` |
| LCD-Treiber, Bildschirmaufbau, Bildschirmschoner (`draw`, `draw_screensaver`) | `display.py` |
| Web-Dashboard (`html_page`, `json_data`, Chart-HTML)           | `web.py`       |
| WLAN an/aus, Webserver-Polling                                 | `wifi.py`      |
| Tasten, Initialisierung, Hauptschleife                         | `main.py`      |

## Funktionsumfang

### Sensorik & Kalibrierung
- BME690 im Forced Mode, IIR-Filter aktiv (`FILTER_COEFF_3`, damit volle
  20-Bit-Auflösung statt der niedrigeren Auflösung ohne Filter).
- Oversampling bewusst asymmetrisch: Feuchte 16x, Druck 1x (zugunsten der
  Feuchtegenauigkeit) - dadurch spürbar mehr Rohrauschen beim Druck, siehe
  Wettertrend unten.
- Additive Offsets für Temperatur, Feuchte und Druck (`config.TEMP_OFFSET`,
  `HUMIDITY_OFFSET`, `PRESSURE_OFFSET`) - Beispielwerte aus Vergleichsmessungen
  gegen eine externe Referenz an einem konkreten Gerät. **Für dein eigenes
  Exemplar neu ermitteln**, nicht ungeprüft übernehmen.

### Selbsttest-Näherung
Boschs eigener Selbsttest prüft u.a. den internen Heizstrom-Regelwert
(`idac`) - der ist über Pimoronis MicroPython-Treiber nicht zugänglich
(bestätigt: weder `bme.read()` noch `bme.configure()` geben ihn her, und der
Treiber hat keine Methode für rohen Registerzugriff). Stattdessen prüft
`update_selftest()`:
- Heizerstabilität + Gaswert-Gültigkeit (`STATUS_HEATER_STABLE`/`STATUS_GAS_VALID`)
- Plausibilitätsspannen für alle vier Messgrößen (`TEMP_MIN_C`/`MAX_C`,
  `PRES_MIN_HPA`/`MAX_HPA`, `HUM_MIN_PCT`/`MAX_PCT`, `GAS_MIN_KOHM`/`MAX_KOHM`)

**Wichtig:** Diese Grenzen sind selbst gewählte, großzügige
Plausibilitätswerte ("Sensor komplett kaputt/getrennt erkennen"), NICHT
Boschs exakte interne Konstanten (die stehen in `bme69x_defs.h`, die nicht
Teil dieses Treibers ist).

### Wettertrend - 3-Stunden-Drucktendenz
Der Haupttrend ist die "3-Stunden-Drucktendenz" - in der Meteorologie ein
Standardbegriff (z.B. so in METAR-/SYNOP-Meldungen verwendet: die Änderung
des Luftdrucks über die letzten drei Stunden). Ein einfacher Zwei-Punkt-
Vergleich ("jetzt minus vor 3 Stunden") reagiert allerdings empfindlich auf
einzelne verrauschte Messwerte an den Fensterrändern - besonders relevant
hier, weil Druck nur mit 1x Oversampling läuft. Stattdessen legt
`history.linreg_change()` eine Kleinste-Quadrate-Ausgleichsgerade durch alle
Punkte im Fenster (`config.PRESSURE_TREND_WINDOW_MIN`, Standard: 180 Minuten
= die volle Ringpuffer-Länge); ein einzelner Ausreißer an einem Rand wird
dadurch automatisch heruntergewichtet, statt die ganze Aussage zu kippen.

**Schwellenwert** (`config.PRESSURE_TREND_THRESHOLD`, Standard: 1,5 hPa über
das volle Fenster): Quellen dazu gehen weit auseinander - von ~0,8 hPa/3h
(eine Home-Assistant-DIY-Anleitung für Hobby-Sensoren, mit dem Hinweis
"Startwert, keine Naturkonstante") bis ~3 hPa/3h (verbreiteter Seefahrt-/
Flugwetter-Schwellenwert für "Sturmwarnung/Frontdurchgang"). 1,5 hPa liegt
bewusst dazwischen - strenger als der twitchy DIY-Wert, weit unter der
Sturmwarnschwelle. Wie bei den anderen Kalibrierwerten in diesem Projekt:
ein Startwert, keine hergeleitete Konstante.

**Konsequenz aus der 3-Stunden-Fensterlänge:** Der Ringpuffer fasst genau
181 Punkte (`HISTORY_SIZE`) - der Trend zeigt entsprechend die ersten rund
drei Stunden nach jedem Boot "warte auf Trenddaten", nicht wie bei einem
kürzeren Fenster nach wenigen Minuten. Unvermeidlich bei einer echten
3-Stunden-Kennzahl.

Zusätzlich ein Frühwarn-Signal ("Anklopfen"): `history.trend_acceleration()`
vergleicht die Steigung der jüngsten `PRESSURE_SWING_MINUTES_NEW` Minuten
(Standard: 10) gegen die davorliegenden `PRESSURE_SWING_MINUTES_OLD` Minuten
(Standard: 20) - ein beginnender Umschwung zeigt sich hier oft, bevor er im
3-Stunden-Gesamttrend sichtbar wird. Auf dem LCD als einfacher ASCII-Pfeil
(`^`/`v`) neben der Luftdruckzeile, im Web-Dashboard als zentriertes
Icon+Pfeil-Banner oberhalb der Luftqualitäts-Kachel.

`PRESSURE_SWING_THRESHOLD` ist ebenfalls ein selbst gewählter Startwert,
noch nicht gegen viele echte Wetterwechsel kalibriert.

### Bildschirmschoner
Nach `SCREENSAVER_IDLE_MS` (Standard: 5 Minuten) ohne Tastendruck dimmt das
Display auf `SCREENSAVER_BRIGHTNESS` (~20 %) und zeigt einen horizontal
wandernden "Scanner" mit verblassendem Schweif (5 Segmente, angelehnt an die
K.I.T.T.-Lauflicht-Optik) statt komplett dunkel zu bleiben. **Jede** Taste
weckt auf; der weckende Tastendruck selbst löst keine Aktion aus (kein
versehentlicher Seitenwechsel o.ä. beim blinden Hinschauen). Sensor-Lesen,
Verlaufsaufzeichnung und Webserver laufen währenddessen unverändert weiter.

Tempo und Segmentzahl sind über `SCREENSAVER_STEP_MS`/`_STEP_PX` und den
Farbverlauf in `display.draw_screensaver()` direkt anpassbar. Aus Farben
verwendet die Animation bewusst nur bereits vorhandene, bestätigt
funktionierende Konstanten aus `colors.py` (`RED`, `LIGHTRED`, `GREY`) statt
neu berechneter Zwischentöne.

### Web-Dashboard
- `/` liefert das vollständige HTML-Dashboard (Karten, Sparklines,
  Luftqualitäts-Skala, Wettertrend-Banner), `/data` ein JSON mit den
  aktuellen Werten (alle 5 s per JS abgerufen), `/history` (falls aktiv)
  die Verlaufsreihen für die Diagramme.
- Kartenhöhen (Sparkline-Karten vs. die höhere Gaswiderstand/IAQ-Karte)
  gleichen sich über CSS Flexbox an; die Höhe der Gas-Trendbox wird zusätzlich
  per kleinem JavaScript beim Laden von der Luftdruck-Karte übernommen
  (`syncGasBoxHeight()`) - robuster als reine CSS-Anpassung, da Grid+Flex in
  verschachtelten Containern nicht immer intuitiv reagiert.
- Fußzeile zeigt zusätzlich die grob geschätzte interne Pico-Temperatur
  (`sensors.internal_temp()`, RP2040-Onboard-Sensor - nur zur groben
  Einordnung, nicht kalibriert).

## Bekannte Grenzen
- `idac`/Multi-Stufen-Heizprofile (Bosch "Parallel Mode", bis zu 10
  Heizstufen pro Zyklus) sind über diesen Treiber nicht nutzbar - bestätigt
  per REPL, weder als Modul-Konstante noch als `read()`-Parameter vorhanden.
  Für Details siehe die BME688/BME690-Datenblätter, Abschnitt "Parallel Mode"
  bzw. Register `idac_heat_x`.
- Kalibrierwerte (Offsets, Selbsttest-Grenzen, Trend-Schwellen) sind alle an
  einem konkreten Gerät gegen eine externe Referenz (SwitchBot-Sensor, DWD-
  Luftdruckdaten) ermittelt - für ein anderes Exemplar als Ausgangspunkt
  brauchbar, aber nicht blind übernehmen.

## Verifiziert vor der Auslieferung
- Alle zehn Dateien einzeln mit `py_compile` auf Syntaxfehler geprüft.
- Ein Skript hat jede `modul.name`-Referenz (z.B. `state.last_temp`,
  `config.HEATER_TEMP`) gegen die tatsächliche Definition im Zielmodul
  abgeglichen - keine Tippfehler oder fehlenden Namen.
- Die Trend-Formeln (lineare Regression, Anklopf-Vergleich) mit
  synthetischen Testreihen gegengerechnet, nicht nur auf dem Papier
  hergeleitet.

**Was nicht vorab geprüft werden konnte:** Echtes Verhalten auf der Hardware
(Timing, I2C, Speicherverbrauch, tatsächliches Seitenlayout im Browser). Der
Code ist Zeile für Zeile aus einer bestätigt funktionierenden Basis portiert
bzw. inkrementell erweitert, aber einige Feinheiten (v.a. die CSS/JS-Layout-
Angleichung der Dashboard-Kacheln) brauchten mehrere Runden mit echten
Foto-/Screenshot-Rückmeldungen, bis Höhen und Ausrichtung tatsächlich
passten - ohne direkten Zugriff auf Display oder Browser ist das am Ende
immer ein Zusammenspiel aus Code und Praxistest, nicht reine Theorie.

Disclaimer: Diese Datei ist mit Unterstützung eines KI-Assistenten (Claude,
Anthropic) entstanden und wurde iterativ gegen echtes Hardware-Feedback
abgeglichen.
