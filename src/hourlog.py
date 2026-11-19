# hourlog.py
# Stuendliches Betriebslog als CSV im Flash des Pico (config.LOG_FILE).
# Aufbau wie beim Enviro+ (dort hourlog.py): pro Stunde genau eine Zeile mit
# Mittel-/Extremwerten und Fehlerzaehlern - kein Messwert-Strom. Das schont
# den Flash (24 Schreibzugriffe pro Tag, ~2 kB/Tag) und den Heap (nur ein paar
# Zaehler, kein Puffer).
#
# Zeitstempel = Beginn des Zeitraums in Ortszeit (braucht NTP). Ohne Uhrzeit
# wird nach je 60 Minuten Laufzeit geschrieben und "-" eingetragen.
# Nach jedem Start folgt eine Zeile "# Start;<Reset-Grund>;<Ortszeit>;nach N s".
# Sie wird erst nach dem ersten Zeitabgleich geschrieben (meist wenige
# Sekunden nach dem Start); ohne Uhrzeit nach spaetestens START_WAIT_MS mit "-".
#
# Groesse: Ab LOG_MAX_BYTES wird log.csv zu log.csv.old (die aeltere .old
# faellt weg). Zwei Dateien = ca. 4 Wochen Verlauf.
#
# Spalten (Trennzeichen ;):
#   ab                 Beginn des Zeitraums
#   n                  gelungene Messungen (3 s) im Zeitraum
#   fehler             Messungen mit Selbsttest-Fehler (Lesefehler, Heizer,
#                      Werte unplausibel)
#   temp, hum, hpa     Mittelwerte (kalibriert)
#   gas                Mittelwert Gaswiderstand (kOhm, nur gueltige Werte)
#   iaq                Mittelwert relative Luftqualitaet (%)
#   ram_min            kleinster freier RAM (kB)
#   block              groesster freier Heap-Block beim Schreiben (kB)
#   loop_max, ruckler  laengster Schleifendurchlauf (ms), Anzahl > 250 ms
#   wlan_err           fehlgeschlagene Verbindungsversuche + Verbindungsabbrueche
#   mqtt_ok, mqtt_err  gesendete Zustaende / MQTT-Fehler (Verbinden, Senden)
#   wlan               WLAN am Zeilenende verbunden (1/0)

import gc
import os
import time
import machine

import config
import state
import sensors
import wifi
import wifi_schedule
import mqtt

_HEADER = ("ab;n;fehler;temp;hum;hpa;gas;iaq;ram_min;block;loop_max;ruckler;"
           "wlan_err;mqtt_ok;mqtt_err;wlan\n")
_SLOW_MS = 250
_TICK_MS = 1000
_START_WAIT_MS = 60000   # so lange auf die Uhrzeit fuer die Startzeile warten

_on = False
_label = "-"
_hour = None
_t_start = 0
_t_tick = 0
_t_loop = 0
_start = None     # Reset-Grund, solange die Startzeile noch aussteht
_t_boot = 0


def _clear():
    global _n, _err, _sum, _cnt, _ram, _loop_max, _slow
    _n = 0
    _err = 0
    _sum = [0.0, 0.0, 0.0, 0.0, 0.0]     # temp, hum, hpa, gas, iaq
    _cnt = [0, 0, 0, 0, 0]
    _ram = None
    _loop_max = 0
    _slow = 0


_clear()


def _reset_cause():
    names = (("PWRON_RESET", "Power-On"), ("HARD_RESET", "Hard-Reset"),
             ("WDT_RESET", "Watchdog"), ("SOFT_RESET", "Soft-Reset"))
    cause = machine.reset_cause()
    for name, label in names:
        if getattr(machine, name, None) == cause:
            return label
    return "unbekannt (%s)" % cause


def _largest_free_block(step=1024):
    """Binaersuche per Probe-Allokation (wie Enviro+ system.py). Kostet
    einige Garbage Collections - laeuft nur einmal pro Stunde."""
    gc.collect()
    lo, hi = 0, gc.mem_free()
    while hi - lo > step:
        mid = (lo + hi) // 2
        try:
            b = bytearray(mid)
            del b
            lo = mid
        except MemoryError:
            hi = mid
    return lo


def _rotate():
    try:
        os.remove(config.LOG_FILE + ".old")
    except OSError:
        pass
    os.rename(config.LOG_FILE, config.LOG_FILE + ".old")


def _line(text):
    """Eine Zeile anhaengen; Fehler (Flash voll o. ae.) duerfen den
    Hauptlauf nie stoeren."""
    try:
        try:
            size = os.stat(config.LOG_FILE)[6]
        except OSError:
            size = -1
        if size > config.LOG_MAX_BYTES:
            _rotate()
            size = -1
        with open(config.LOG_FILE, "a") as f:
            if size < 0:
                f.write(_HEADER)
            f.write(text)
    except Exception as error:
        print("Log:", error)


def init():
    """Einmal beim Start aus main.py rufen."""
    global _on, _t_start, _t_tick, _t_loop, _start, _t_boot
    _on = config.LOG_ENABLED
    if not _on:
        return
    _t_start = _t_tick = _t_loop = _t_boot = time.ticks_ms()
    try:                         # Spalten geaendert: alte Datei nach .old, neu beginnen
        with open(config.LOG_FILE) as f:
            first = f.readline()
        if first != _HEADER:
            _rotate()
    except OSError:
        pass
    _start = _reset_cause()      # Startzeile folgt in tick(), sobald die Uhrzeit da ist


# ── Datensammlung (billig, laeuft staendig) ───────────────────
def note_loop(free):
    """Jede Schleifenrunde: Rundenzeit und freier RAM."""
    global _t_loop, _loop_max, _slow, _ram
    if not _on:
        return
    now = time.ticks_ms()
    lap = time.ticks_diff(now, _t_loop)
    _t_loop = now
    if lap > _loop_max:
        _loop_max = lap
    if lap > _SLOW_MS:
        _slow += 1
    if _ram is None or free < _ram:
        _ram = free


def add_sample(ok):
    """Nach jeder Messung: ok = Ergebnis des Selbsttests dieser Messung."""
    global _n, _err
    if not _on:
        return
    if not ok:
        _err += 1
    if state.last_temp is None:
        return
    _n += 1
    iaq = sensors.iaq_relative(state.last_gas)[0] if state.last_gas_reliable else None
    gas = state.last_gas if state.last_gas_reliable else None
    for i, v in enumerate((state.last_temp, state.last_hum, state.last_pres, gas, iaq)):
        if v is not None:
            _sum[i] += v
            _cnt[i] += 1


# ── Schreiben ─────────────────────────────────────────────────
def tick():
    """Jede Schleifenrunde aufrufen; prueft hoechstens einmal pro Sekunde."""
    global _t_tick, _hour, _label, _t_start, _start
    if not _on:
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, _t_tick) < _TICK_MS:
        return
    _t_tick = now
    synced = state.sched is not None and state.sched.synced
    lt = wifi_schedule.local_time() if synced else None

    if _start is not None:
        waited = time.ticks_diff(now, _t_boot)
        if lt is not None or waited >= _START_WAIT_MS:
            stamp = "%04d-%02d-%02d %02d:%02d:%02d" % lt[:6] if lt else "-"
            _line("# Start;%s;%s;nach %d s\n" % (_start, stamp, waited // 1000))
            _start = None

    if lt is not None:
        if _hour is None:
            _hour = lt[3]
            _label = "%04d-%02d-%02d %02d:%02d" % lt[:5]
        elif lt[3] != _hour:
            _write()
            _hour = lt[3]
            _label = "%04d-%02d-%02d %02d:%02d" % lt[:5]
    elif time.ticks_diff(now, _t_start) >= 3600000:
        _write()
        _t_start = now


def _avg(i, fmt):
    return fmt % (_sum[i] / _cnt[i]) if _cnt[i] else ""


def _kb(v):
    return "" if v is None else "%.1f" % (v / 1024)


def _write():
    global _t_loop
    wlan_err = wifi.pop_errors()
    mqtt_ok, mqtt_err = mqtt.pop_stats()
    row = ";".join((
        _label, str(_n), str(_err),
        _avg(0, "%.1f"), _avg(1, "%.0f"), _avg(2, "%.1f"),
        _avg(3, "%.0f"), _avg(4, "%.0f"),
        _kb(_ram), _kb(_largest_free_block()),
        str(_loop_max), str(_slow),
        str(wlan_err), str(mqtt_ok), str(mqtt_err),
        "1" if wifi.connected() else "0")) + "\n"
    _clear()
    _line(row)
    _t_loop = time.ticks_ms()    # Blocksuche und Schreiben nicht als Ruckler zaehlen

# EOF 2026-11-19
