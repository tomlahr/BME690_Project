# PicoBME690 - Modulare Struktur

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
hier beigelegten Platzhalter-Version ueberschreiben.**

## Was neu ist gegenueber der letzten main.py

1. **Modulare Aufteilung** - siehe Tabelle unten. Verhalten ist unveraendert,
   nur ueber mehrere Dateien verteilt.
2. **Selbsttest um T/P/H erweitert.** Bisher pruefte `update_selftest()` nur
   Heizerstabilitaet + Gaswert-Gueltigkeit + Gaswiderstand-Plausibilitaet.
   Jetzt zusaetzlich: Temperatur, Druck und Feuchte muessen in einer
   plausiblen Spanne liegen (siehe `config.py`, `TEMP_MIN_C` etc.) - nach
   dem Vorbild von Boschs eigenem `analyze_sensor_data()` in `bme69x.c`.
   **Wichtig:** Diese Grenzen sind selbst gewaehlte, grosszuegige
   Plausibilitaetswerte ("Sensor komplett kaputt/getrennt erkennen"),
   NICHT Boschs exakte interne Konstanten - die stehen in `bme69x_defs.h`,
   die mir nicht vorliegt.

## Architektur-Loesung: state.py

Dein Original hielt alle Messwerte als globale Variablen in einer Datei -
das geht nur, weil dort auch alle Funktionen sitzen, die per `global`
draufzugreifen. Ueber mehrere Dateien verteilt, gibt's kein gemeinsames
"global" mehr. Loesung: `state.py` haelt nur die gemeinsamen Werte
(`last_temp`, `min_gas`, `wifi_active`, ...), alle anderen Module lesen/
schreiben direkt `state.last_temp = ...` statt `global last_temp` zu
deklarieren. Kein Verhaltensunterschied, nur die Art, wie der Zustand
zwischen Dateien geteilt wird.

## Zuordnung alt -> neu

| Aus der alten main.py                                    | Jetzt in       |
|------------------------------------------------------------|----------------|
| Konstanten (Pins, Offsets, Intervalle, MODE_NAMES)          | `config.py`    |
| Farbkonstanten                                              | `colors.py`    |
| Globale Messwerte/Zustand (`last_temp`, `wifi_active`, ...)  | `state.py`     |
| `record_history`, `delta_from_history`, `signed_value`, `uptime` | `history.py` |
| `update_sensor`, `update_selftest`, `selftest_text`, `internal_temp`, `iaq_relative`, `comfort_text`, `gas_status_text`, `pressure_trend`, `weather_trend` | `sensors.py` |
| `LCD_0inch96`, `draw`                                       | `display.py`   |
| `html_page`, `json_data`, `sparkline`, `iaq_overlay`, `chart_card`, `pressure_chart`, `gas_chart`, `send_all`, `send_response`, `handle_request` | `web.py` |
| `toggle_wifi`, `poll_server`                                | `wifi.py`      |
| Tasten, Initialisierung, Hauptschleife                      | `main.py`      |

## Verifiziert vor der Auslieferung
- Alle zehn Dateien einzeln mit `py_compile` auf Syntaxfehler geprueft.
- Ein Skript hat jede `modul.name`-Referenz (z.B. `state.last_temp`,
  `config.HEATER_TEMP`) gegen die tatsaechliche Definition im Zielmodul
  abgeglichen - keine Tippfehler oder fehlenden Namen gefunden.

**Was ich NICHT pruefen kann:** Echtes Verhalten auf der Hardware (Timing,
I2C, Speicherverbrauch). Der Code ist Zeile fuer Zeile aus deiner
bestaetigt funktionierenden main.py portiert, aber ein erster Testlauf auf
dem Pico bleibt trotzdem noetig.

## Bei Problemen
Falls beim ersten Start ein `ImportError` oder `AttributeError` auftaucht,
schick mir die genaue Fehlermeldung - die verrät sofort, welches Modul
betroffen ist.
