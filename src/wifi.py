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
