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


# Laufzeit als Summe kurzer Schritte statt als Differenz zum Boot-Zeitpunkt:
# ticks_diff() ist nur bis +-2^29 ms (~149 h) eindeutig, danach wurde die
# Laufzeit negativ. Sekunden + Rest-ms getrennt, damit alles im Small-Int-
# Bereich bleibt (keine Heap-Allokation pro Schleifenrunde).
_up_s = 0
_up_ms = 0
_up_last = None


def tick_uptime():
    """Jede Schleifenrunde aufrufen."""
    global _up_s, _up_ms, _up_last
    now = time.ticks_ms()
    if _up_last is not None:
        _up_ms += time.ticks_diff(now, _up_last)
        if _up_ms >= 1000:
            _up_s += _up_ms // 1000
            _up_ms %= 1000
    _up_last = now


def uptime():
    seconds = _up_s

    return "%02d:%02d:%02d" % (
        seconds // 3600,
        seconds % 3600 // 60,
        seconds % 60
    )

# EOF 2026-09-23
