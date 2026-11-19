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
import wifi_schedule
import iaq
import mqtt
import hourlog

# ── Tasten ─────────────────────────────────────────────────────
# Flankenerkennung statt Warteschleife: genau ein Ereignis pro Druck, eine
# gehaltene Taste blockiert Sensor, Display und Webserver nicht.
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


def _backlight():
    display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])


# ── Initialisierung ─────────────────────────────────────────────
display.init()

i2c = PimoroniI2C(sda=config.I2C_SDA, scl=config.I2C_SCL)
sensors.init(i2c)
state.iaq = iaq.IAQ()   # laedt die Baseline vom Flash, falls vorhanden

state.min_mem_free = gc.mem_free()
_backlight()            # Starthelligkeit: BRIGHTNESS_LEVELS[1]

t0 = time.ticks_ms()
last_sensor = time.ticks_add(t0, -config.SENSOR_INTERVAL_MS)
last_display = time.ticks_add(t0, -config.DISPLAY_INTERVAL_MS)
last_history = time.ticks_add(t0, -config.HISTORY_INTERVAL_MS)
last_iaq_save = t0
last_page = t0
state.last_activity = t0

# Frueher sammeln statt erst im Notfall
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

sched = wifi_schedule.WifiSchedule(config.WIFI_OFF_FROM, config.WIFI_OFF_UNTIL,
                                   config.NTP_HOSTS, config.NTP_RESYNC_MS,
                                   config.NTP_RETRY_MS)
state.sched = sched      # Uhrzeit fuer den Bildschirmschoner

hourlog.init()           # schreibt "# Start;<Reset-Grund>" ins Log

if config.WIFI_AUTOSTART:
    wifi.toggle_wifi()

# ── Hauptschleife ───────────────────────────────────────────────
while True:
    now = time.ticks_ms()

    # Alle Tasten JEDE Runde abfragen - sonst verpasst eine Taste, die durch
    # "or"-Kurzschluss uebersprungen wird, ihre Flanke.
    k_next = KEY_A.pressed() | KEY_RIGHT.pressed()
    k_prev = KEY_B.pressed() | KEY_LEFT.pressed()
    k_up = KEY_UP.pressed()
    k_down = KEY_DOWN.pressed()
    k_ctrl = KEY_CTRL.pressed()

    if k_next or k_prev or k_up or k_down or k_ctrl:
        state.last_activity = now
        if state.screensaver_active:          # erster Tastendruck weckt nur
            state.screensaver_active = False
            _backlight()
        elif k_next:
            state.mode = (state.mode + 1) % len(config.MODE_NAMES)
        elif k_prev:
            state.mode = (state.mode - 1) % len(config.MODE_NAMES)
        elif k_up:
            state.brightness_idx = min(state.brightness_idx + 1,
                                       len(config.BRIGHTNESS_LEVELS) - 1)
            _backlight()
        elif k_down:
            state.brightness_idx = max(state.brightness_idx - 1, 0)
            _backlight()
        else:
            mqtt.goodbye()      # "offline" melden, falls das WLAN gleich ausgeht
            wifi.toggle_wifi()
            sched.manual()      # Eingriff bis zum naechsten Schaltpunkt
        last_display = time.ticks_add(now, -config.DISPLAY_INTERVAL_MS)   # sofort zeichnen

    wifi.poll()          # Verbindungsaufbau / Wiederverbindung
    wifi.poll_server()
    mqtt.poll(wifi.connected())

    # update() meldet "on"/"off" nur, wenn der Sollzustand vom Istzustand
    # abweicht - umschalten genuegt also.
    action = sched.update(state.wifi_active, wifi.connected())
    if action:
        if action == "off":
            mqtt.goodbye()
        wifi.toggle_wifi()

    history.tick_uptime()

    free = gc.mem_free()
    if free < state.min_mem_free:
        state.min_mem_free = free
    hourlog.note_loop(free)
    hourlog.tick()

    if time.ticks_diff(now, last_sensor) >= config.SENSOR_INTERVAL_MS:
        last_sensor = now
        sensors.update_selftest(sensors.update_sensor())
        hourlog.add_sample(state.selftest_results[-1])

    if time.ticks_diff(now, last_history) >= config.HISTORY_INTERVAL_MS:
        last_history = now
        history.record_history()

    if time.ticks_diff(now, last_iaq_save) >= config.IAQ_SAVE_INTERVAL_MS:
        last_iaq_save = now
        state.iaq.save()

    if not state.screensaver_active and \
       time.ticks_diff(now, state.last_activity) >= config.SCREENSAVER_IDLE_MS:
        state.screensaver_active = True
        state.screensaver_page = 0
        last_page = now
        last_display = time.ticks_add(now, -config.SCREENSAVER_REDRAW_MS)   # sofort zeichnen
        display.lcd.backlight(config.SCREENSAVER_BRIGHTNESS)

    if state.screensaver_active:
        if time.ticks_diff(now, last_page) >= config.SCREENSAVER_PAGE_MS:
            last_page = now
            state.screensaver_page = (state.screensaver_page + 1) % display.SCREENSAVER_PAGES
            last_display = time.ticks_add(now, -config.SCREENSAVER_REDRAW_MS)
        if time.ticks_diff(now, last_display) >= config.SCREENSAVER_REDRAW_MS:
            last_display = now
            display.draw_screensaver()
    elif time.ticks_diff(now, last_display) >= config.DISPLAY_INTERVAL_MS:
        last_display = now
        display.draw()

    time.sleep_ms(config.LOOP_SLEEP_MS)

# EOF 2026-11-19
