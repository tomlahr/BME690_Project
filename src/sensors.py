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
_i2c = None
_adc_temp = ADC(4)   # interner Temperatursensor des RP2350A


def _svp(t):
    """Saettigungsdampfdruck nach Magnus in hPa (ueber Wasser)."""
    return 6.112 * math.exp(17.62 * t / (243.12 + t))


def _connect():
    """Sensor anlegen und konfigurieren. Schlaegt das fehl (Sensor fehlt,
    Wackelkontakt), bleibt bme None und update_sensor() versucht es erneut -
    vorher brach main.py beim Start mit einer Exception ab."""
    global bme
    try:
        b = bme69x.BreakoutBME69X(_i2c, address=config.BME_ADDRESS)
        b.configure(
            bme69x.FILTER_COEFF_3,
            bme69x.STANDBY_TIME_1000_MS,
            bme69x.OVERSAMPLING_1X,   # Druck
            bme69x.OVERSAMPLING_2X,   # Temperatur
            bme69x.OVERSAMPLING_16X   # Feuchte
        )
        b.read(heater_temp=config.HEATER_TEMP, heater_duration=config.HEATER_DURATION_MS)
        bme = b
    except Exception as error:
        print("BME690 nicht erreichbar:", error)


def init(i2c):
    """Einmal beim Start aus main.py rufen."""
    global _i2c
    _i2c = i2c
    _connect()


def update_sensor():
    """Eine Messung. Rueckgabe True bei Erfolg - der Selbsttest wertet einen
    Fehlschlag als Fehler, statt alte Werte weiter als 'OK' zu pruefen."""
    if bme is None:
        _connect()
        if bme is None:
            return False
    try:
        t_raw, pressure, humidity, gas, status, _, _ = bme.read(
            heater_temp=config.HEATER_TEMP,
            heater_duration=config.HEATER_DURATION_MS
        )
    except Exception as error:
        print("Sensorfehler:", error)
        return False

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

    if state.min_temp is None:   # erste Messung
        state.min_temp = state.max_temp = temp
        state.min_hum = state.max_hum = humidity
        state.min_pres = state.max_pres = pressure
    else:
        state.min_temp = min(state.min_temp, temp)
        state.max_temp = max(state.max_temp, temp)
        state.min_hum = min(state.min_hum, humidity)
        state.max_hum = max(state.max_hum, humidity)
        state.min_pres = min(state.min_pres, pressure)
        state.max_pres = max(state.max_pres, pressure)

    state.last_gas_reliable = (
        (status & bme69x.STATUS_GAS_VALID) != 0
        and (status & bme69x.STATUS_HEATER_STABLE) != 0
    )

    if state.last_gas_reliable:
        if state.min_gas is None:
            state.min_gas = state.max_gas = gas
        else:
            state.min_gas = min(state.min_gas, gas)
            state.max_gas = max(state.max_gas, gas)
    if state.iaq is not None:
        state.iaq.update(gas, state.last_gas_reliable)
    return True


def update_selftest(read_ok):
    """Naeherung an Boschs Selbsttest ueber mehrere Zyklen: Messung gelungen,
    Heizer stabil, Gaswert gueltig, T/P/H in plausibler Spanne - nach dem
    Vorbild von Boschs eigenem analyze_sensor_data()."""
    if read_ok:
        ok = (state.last_gas_reliable
              and config.GAS_MIN_KOHM <= state.last_gas <= config.GAS_MAX_KOHM
              and config.TEMP_MIN_C <= state.last_temp <= config.TEMP_MAX_C
              and config.PRES_MIN_HPA <= state.last_pres <= config.PRES_MAX_HPA
              and config.HUM_MIN_PCT <= state.last_hum <= config.HUM_MAX_PCT)
    else:
        ok = False

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


# LCD-Texte bleiben ASCII (die 8x8-Schrift kennt keine Umlaute). Web und
# MQTT uebersetzen sie mit de() - eine Tabelle fuer beide.
_DE = (
    ("aufwaermen...", "Aufwärmphase"),
    ("maessig", "mäßig"),
    ("gueltig", "gültig"),
    ("kuehl", "kühl"),
    ("pruefe", "prüfe"),
)


def de(text):
    for ascii_text, german in _DE:
        text = text.replace(ascii_text, german)
    return text


def internal_temp():
    volt = _adc_temp.read_u16() * 3.3 / 65535.0
    return 27.0 - (volt - 0.706) / 0.001721


def iaq_relative(gas):
    """(Prozent 0..100 oder None, Label, Farbe). Score aus iaq.IAQ."""
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


# ── Luftdrucktrend ─────────────────────────────────────────
# Eine Klassifizierung fuer Textzeile und Wetter-Banner, damit beide nie
# auseinanderlaufen: 0 fallend, 1 stabil, 2 steigend, None ohne Daten.
_TREND_TEXT = ("fallend", "stabil", "steigend")
_WEATHER = (
    ("🌧️", "Wettertrend: wechselhaft"),
    ("☁️", "Wettertrend: stabil"),
    ("🌤️", "Wettertrend: freundlich"),
)


def _pressure_class():
    change = history.linreg_change(state.history_pres, config.PRESSURE_TREND_WINDOW_MIN)
    if change is None:
        return None
    if change > config.PRESSURE_TREND_THRESHOLD:
        return 2
    if change < -config.PRESSURE_TREND_THRESHOLD:
        return 0
    return 1


def pressure_trend():
    c = _pressure_class()
    return "warte auf Trenddaten" if c is None else _TREND_TEXT[c]


def weather_trend():
    """(Emoji, Text, Trendtext) - eine Regression fuer das ganze Banner."""
    c = _pressure_class()
    if c is None:
        return "⏳", "Wettertrend wird berechnet", "warte auf Trenddaten"
    emoji, text = _WEATHER[c]
    return emoji, text, _TREND_TEXT[c]


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

# EOF 2026-11-19
