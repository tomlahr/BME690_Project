# mqtt.py
# MQTT-Anbindung an Home Assistant per Discovery (umqtt.simple).
#
# Ablauf (Zustandsautomat wie wifi.py, ein Schritt pro Schleifenrunde):
#   kein Client  -> connect() (blockiert hoechstens MQTT_TIMEOUT_S; bei
#                   Fehlschlag Wartezeit 15 s, verdoppelt bis 5 min)
#   Discovery    -> pro Runde eine Konfig-Nachricht (retained)
#   Betrieb      -> alle MQTT_PUBLISH_MS ein JSON-Zustand (nicht retained)
# Verfuegbarkeit: Last Will "offline" (retained). Vor dem Abschalten des WLANs
# meldet goodbye() "offline" selbst, weil ein sauberes DISCONNECT den Last Will
# unterdrueckt.
# Zugangsdaten stehen in secrets.py (MQTT_USER, MQTT_PASSWORD).
# Der Timeout gilt auch fuers Senden: umqtt.simple setzt ihn beim connect()
# und laesst ihn stehen - ein haengender Broker blockiert publish() also
# hoechstens MQTT_TIMEOUT_S lang.

import gc
import json
import time

import config
import state
import sensors
import history
import secrets

try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None

_USER = getattr(secrets, "MQTT_USER", None)
_PASS = getattr(secrets, "MQTT_PASSWORD", None)

_BASE = "pico/" + config.MQTT_NODE_ID
_T_STATE = _BASE + "/state"
_T_STATUS = _BASE + "/status"

# (Schluessel, Name, Einheit, device_class, state_class, Nachkommastellen,
#  Icon, diagnostic)
_ENTITIES = (
    ("temp", "Temperatur", "°C", "temperature", "measurement", 1, None, False),
    ("hum", "Luftfeuchte", "%", "humidity", "measurement", 0, None, False),
    ("pres", "Luftdruck", "hPa", "atmospheric_pressure", "measurement", 1, None, False),
    ("gas", "Gaswiderstand", "kΩ", None, "measurement", 0, "mdi:molecule", False),
    ("iaq", "Luftqualität relativ", "%", None, "measurement", 0, "mdi:air-filter", False),
    ("iaq_label", "Luftqualität", None, None, None, None, "mdi:air-filter", False),
    ("rssi", "WLAN-Signal", "dBm", "signal_strength", "measurement", 0, None, True),
    ("uptime", "Laufzeit", "s", "duration", None, 0, None, True),
    ("selftest", "Selbsttest", None, None, None, None, "mdi:heart-pulse", True),
    ("mem", "Freier Speicher", "B", None, "measurement", 0, "mdi:memory", True),
)

_DISCOVERY = 1
_RUN = 2

_client = None
_phase = _DISCOVERY
_idx = 0
# Ende der Wartezeit nach einem Fehlschlag, None = keine Wartezeit. Bewusst
# kein alter Zeitstempel: ticks_diff() ist nur ~6 Tage eindeutig - nach
# laengerem fehlerfreiem Betrieb haette der Vergleich sonst tagelang
# "noch warten" gemeldet.
_t_retry = None
_t_pub = 0
_backoff = config.MQTT_RETRY_MS
_n_ok = 0        # gesendete Zustaende       } fuer hourlog.py,
_n_err = 0       # Verbindungs-/Sendefehler  } stuendlich zurueckgesetzt


def _enabled():
    return (config.MQTT_ENABLED and MQTTClient is not None
            and _USER is not None and _PASS is not None)


def _drop():
    """Verbindung ohne DISCONNECT verwerfen (Last Will bleibt gueltig)."""
    global _client
    c = _client
    _client = None
    if c is not None:
        try:
            c.sock.close()
        except Exception:
            pass


def pop_stats():
    """(gesendet, Fehler) fuer das Stundenlog lesen und zuruecksetzen."""
    global _n_ok, _n_err
    stats = (_n_ok, _n_err)
    _n_ok = _n_err = 0
    return stats


def _fail(now):
    global _t_retry, _backoff, _n_err
    _n_err += 1
    _drop()
    _t_retry = time.ticks_add(now, _backoff)
    _backoff = min(_backoff * 2, config.MQTT_RETRY_MAX_MS)


def _connect():
    global _client, _phase, _idx, _backoff
    c = MQTTClient(config.MQTT_NODE_ID, config.MQTT_HOST,
                   port=config.MQTT_PORT, user=_USER, password=_PASS,
                   keepalive=config.MQTT_KEEPALIVE_S)
    c.set_last_will(_T_STATUS, b"offline", retain=True)
    try:
        c.connect(timeout=config.MQTT_TIMEOUT_S)
    except Exception:
        # umqtt.simple schliesst den Socket bei Fehlschlag nicht selbst -
        # sonst sammeln sich bei totem Broker offene Sockets an.
        try:
            c.sock.close()
        except Exception:
            pass
        raise
    _client = c
    _phase = _DISCOVERY
    _idx = 0
    _backoff = config.MQTT_RETRY_MS
    print("MQTT: verbunden mit", config.MQTT_HOST)


def _discovery_payload(ent):
    key, name, unit, dev_cla, st_cla, prec, icon, diag = ent
    p = {
        "name": name,
        "unique_id": config.MQTT_NODE_ID + "_" + key,
        "state_topic": _T_STATE,
        "value_template": "{{ value_json." + key + " }}",
        "availability_topic": _T_STATUS,
        "device": {
            "identifiers": [config.MQTT_NODE_ID],
            "name": config.MQTT_DEVICE_NAME,
            "manufacturer": "Raspberry Pi / Bosch Sensortec",
            "model": config.MQTT_DEVICE_MODEL,
        },
    }
    if state.ip:
        p["device"]["configuration_url"] = "http://" + state.ip
    if unit:
        p["unit_of_measurement"] = unit
    if dev_cla:
        p["device_class"] = dev_cla
    if st_cla:
        p["state_class"] = st_cla
    if prec is not None:
        p["suggested_display_precision"] = prec
    if icon:
        p["icon"] = icon
    if diag:
        p["entity_category"] = "diagnostic"
    return p


def _r(value, digits):
    return None if value is None else round(value, digits)


def _state_payload():
    iaq = label = None
    if state.last_gas is not None:
        iaq, label, _ = sensors.iaq_relative(state.last_gas)
    try:
        rssi = state.wlan.status("rssi")
    except Exception:
        rssi = None
    return {
        "temp": _r(state.last_temp, 1),
        "hum": _r(state.last_hum, 1),
        "pres": _r(state.last_pres, 1),
        # unzuverlaessige Gaswerte (Heizer nicht stabil) nicht melden
        "gas": _r(state.last_gas, 1) if state.last_gas_reliable else None,
        "iaq": _r(iaq, 0),
        "iaq_label": sensors.de(label) if label else None,
        "rssi": rssi,
        "uptime": history.uptime_s(),
        "selftest": sensors.de(sensors.selftest_text()[0]),
        "mem": gc.mem_free(),
    }


def poll(linked):
    """Jede Schleifenrunde aufrufen, linked = wifi.connected()."""
    global _phase, _idx, _t_pub, _n_ok, _t_retry
    if not _enabled():
        return
    if not linked:
        if _client is not None:
            _drop()   # Socket ist mit dem WLAN-Link ohnehin tot
        return

    now = time.ticks_ms()
    if _client is None:
        if _t_retry is not None:
            if time.ticks_diff(now, _t_retry) < 0:
                return
            _t_retry = None
        try:
            _connect()
        except Exception as error:
            print("MQTT: Verbindung fehlgeschlagen:", error)
            _fail(time.ticks_ms())
        return

    try:
        if _phase == _DISCOVERY:
            ent = _ENTITIES[_idx]
            topic = "%s/sensor/%s/%s/config" % (
                config.MQTT_DISCOVERY_PREFIX, config.MQTT_NODE_ID, ent[0])
            _client.publish(topic, json.dumps(_discovery_payload(ent)).encode("utf-8"),
                            retain=True)
            _idx += 1
            if _idx >= len(_ENTITIES):
                _client.publish(_T_STATUS, b"online", retain=True)
                _phase = _RUN
                _t_pub = time.ticks_add(now, -config.MQTT_PUBLISH_MS)   # sofort senden
                gc.collect()
        elif time.ticks_diff(now, _t_pub) >= config.MQTT_PUBLISH_MS \
                and state.last_temp is not None:
            _t_pub = now
            _client.publish(_T_STATE, json.dumps(_state_payload()).encode("utf-8"))
            _n_ok += 1
    except Exception as error:
        print("MQTT: Sendefehler:", error)
        _fail(time.ticks_ms())


def goodbye():
    """Vor dem Abschalten des WLANs: 'offline' melden und sauber trennen."""
    global _client
    c = _client
    if c is None:
        return
    _client = None
    try:
        c.publish(_T_STATUS, b"offline", retain=True)
        c.disconnect()             # schliesst auch den Socket
    except Exception:
        try:
            c.sock.close()
        except Exception:
            pass

# EOF 2026-11-19
