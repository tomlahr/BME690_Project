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
