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
import iaq

# ── Tasten ─────────────────────────────────────────────────────
# Paket 1 (2026-09-23): Flankenerkennung statt Warteschleife. Die alte
# pressed()-Funktion wartete, solange eine Taste gehalten wurde - in der
# Zeit standen Sensor, Display und Webserver. Jetzt: genau ein Ereignis
# pro Druck, kein Warten.
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


# ── Initialisierung ─────────────────────────────────────────────
display.init()

i2c = PimoroniI2C(sda=config.I2C_SDA, scl=config.I2C_SCL)
sensors.init(i2c)
state.iaq = iaq.IAQ()   # laedt die Baseline vom Flash, falls vorhanden

state.boot_time = time.ticks_ms()
state.min_mem_free = gc.mem_free()

# Starthelligkeit: 600
display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

last_sensor = time.ticks_add(state.boot_time, -config.SENSOR_INTERVAL_MS)
last_display = time.ticks_add(state.boot_time, -config.DISPLAY_INTERVAL_MS)
last_history = time.ticks_add(state.boot_time, -config.HISTORY_INTERVAL_MS)
last_iaq_save = state.boot_time

# Frueher sammeln statt erst im Notfall
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

state.last_activity = state.boot_time

# Optional: WLAN direkt einschalten (config.WIFI_AUTOSTART, standardmaessig aus)
if getattr(config, "WIFI_AUTOSTART", False):
    wifi.toggle_wifi()

# ── Hauptschleife ───────────────────────────────────────────────
while True:
    # Alle Tasten JEDE Runde abfragen - sonst verpasst eine Taste, die durch
    # "or"-Kurzschluss uebersprungen wird, ihre Flanke.
    k_a, k_right = KEY_A.pressed(), KEY_RIGHT.pressed()
    k_b, k_left = KEY_B.pressed(), KEY_LEFT.pressed()
    k_up, k_down = KEY_UP.pressed(), KEY_DOWN.pressed()
    k_ctrl = KEY_CTRL.pressed()

    any_key = False

    if k_a or k_right:
        any_key = True
        if not state.screensaver_active:
            state.mode = (state.mode + 1) % len(config.MODE_NAMES)
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    elif k_b or k_left:
        any_key = True
        if not state.screensaver_active:
            state.mode = (state.mode - 1) % len(config.MODE_NAMES)
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    elif k_up:
        any_key = True
        if not state.screensaver_active:
            state.brightness_idx = min(
                state.brightness_idx + 1,
                len(config.BRIGHTNESS_LEVELS) - 1
            )
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

    elif k_down:
        any_key = True
        if not state.screensaver_active:
            state.brightness_idx = max(state.brightness_idx - 1, 0)
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])

    elif k_ctrl:
        any_key = True
        if not state.screensaver_active:
            wifi.toggle_wifi()
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    if any_key:
        state.last_activity = time.ticks_ms()
        if state.screensaver_active:
            state.screensaver_active = False
            display.lcd.backlight(config.BRIGHTNESS_LEVELS[state.brightness_idx])
            last_display = time.ticks_add(time.ticks_ms(), -config.DISPLAY_INTERVAL_MS)

    wifi.poll()          # Verbindungsaufbau / Wiederverbindung
    wifi.poll_server()

    now = time.ticks_ms()

    free = gc.mem_free()
    if free < state.min_mem_free:
        state.min_mem_free = free

    if time.ticks_diff(now, last_sensor) >= config.SENSOR_INTERVAL_MS:
        last_sensor = now
        sensors.update_sensor()
        sensors.update_selftest()

    if time.ticks_diff(now, last_history) >= config.HISTORY_INTERVAL_MS:
        last_history = now
        history.record_history()

    if time.ticks_diff(now, last_iaq_save) >= config.IAQ_SAVE_INTERVAL_MS:
        last_iaq_save = now
        state.iaq.save()

    if not state.screensaver_active and time.ticks_diff(now, state.last_activity) >= config.SCREENSAVER_IDLE_MS:
        state.screensaver_active = True
        state.screensaver_x = 0
        state.screensaver_dir = 1
        display.lcd.backlight(config.SCREENSAVER_BRIGHTNESS)

    if state.screensaver_active:
        if time.ticks_diff(now, last_display) >= config.SCREENSAVER_STEP_MS:
            last_display = now
            state.screensaver_x += state.screensaver_dir * config.SCREENSAVER_STEP_PX
            if state.screensaver_x >= display.lcd.width - config.SCREENSAVER_BAR_W or state.screensaver_x <= 0:
                state.screensaver_dir = -state.screensaver_dir
            display.draw_screensaver()
    else:
        if time.ticks_diff(now, last_display) >= config.DISPLAY_INTERVAL_MS:
            last_display = now
            display.draw()

    time.sleep_ms(config.LOOP_SLEEP_MS)

# EOF 2026-09-26
