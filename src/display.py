# display.py
# LCD-Treiber (ST7735-artig, 160x80) und der Bildschirmaufbau fuer alle
# fuenf Modi (Klima, Gas/IAQ, Min/Max, WLAN, System).

from machine import Pin, SPI, PWM
import framebuf
import time

import config
import state
import colors
import sensors
import history
import wifi_schedule

lcd = None


class LCD_0inch96(framebuf.FrameBuffer):
    def __init__(self):
        self.width = 160
        self.height = 80

        self.cs = Pin(config.DISP_CS, Pin.OUT, value=1)
        self.rst = Pin(config.DISP_RST, Pin.OUT, value=1)
        self.dc = Pin(config.DISP_DC, Pin.OUT, value=1)

        self.spi = SPI(
            1,
            10_000_000,
            polarity=0,
            phase=0,
            sck=Pin(config.DISP_SCK),
            mosi=Pin(config.DISP_MOSI),
            miso=None
        )

        self.bl = PWM(Pin(config.DISP_BL))
        self.bl.freq(1000)

        self.buffer = bytearray(self.width * self.height * 2)
        super().__init__(
            self.buffer,
            self.width,
            self.height,
            framebuf.RGB565
        )

        self.init_display()

    def cmd(self, value):
        self.dc(0)
        self.cs(0)
        self.spi.write(bytes((value,)))
        self.cs(1)

    def data(self, value):
        self.dc(1)
        self.cs(0)

        if isinstance(value, int):
            self.spi.write(bytes((value,)))
        else:
            self.spi.write(value)

        self.cs(1)

    def backlight(self, value):
        value = max(0, min(value, 1000))
        self.bl.duty_u16(value * 65535 // 1000)

    def init_display(self):
        self.rst(1)
        time.sleep_ms(200)
        self.rst(0)
        time.sleep_ms(200)
        self.rst(1)
        time.sleep_ms(200)

        self.backlight(1000)

        self.cmd(0x11)
        time.sleep_ms(120)
        self.cmd(0x21)

        sequence = (
            (0xB1, b"\x05\x3A\x3A"),
            (0xB2, b"\x05\x3A\x3A"),
            (0xB3, b"\x05\x3A\x3A\x05\x3A\x3A"),
            (0xB4, b"\x03"),
            (0xC0, b"\x62\x02\x04"),
            (0xC1, b"\xC0"),
            (0xC2, b"\x0D\x00"),
            (0xC3, b"\x8D\x6A"),
            (0xC4, b"\x8D\xEE"),
            (0xC5, b"\x0E"),
            (0xE0, b"\x10\x0E\x02\x03\x0E\x07\x02\x07"
                   b"\x0A\x12\x27\x37\x00\x0D\x0E\x10"),
            (0xE1, b"\x10\x0E\x03\x03\x0F\x06\x02\x08"
                   b"\x0A\x13\x26\x36\x00\x0D\x0E\x10"),
            (0x3A, b"\x05"),
            (0x36, b"\xA8"),
        )

        for command, values in sequence:
            self.cmd(command)
            self.data(values)

        self.cmd(0x29)

    def show(self):
        self.cmd(0x2A)
        self.data(b"\x00\x01\x00\xA0")

        self.cmd(0x2B)
        self.data(b"\x00\x1A\x00\x69")

        self.cmd(0x2C)
        self.dc(1)
        self.cs(0)
        self.spi.write(self.buffer)
        self.cs(1)

    def text_right(self, text, y, color, right=155):
        self.text(text, right - len(text) * 8, y, color)


def init():
    """LCD anlegen. Einmal beim Start aus main.py rufen."""
    global lcd
    lcd = LCD_0inch96()


def draw():
    lcd.fill(colors.BLACK)
    lcd.text(config.MODE_NAMES[state.mode], 5, 4, colors.GREY)

    if state.wifi_active:
        lcd.text_right("WLAN", 4, colors.GREEN)

    lcd.fill_rect(0, 16, 160, 2, colors.GREY)

    if state.last_temp is None:
        lcd.text("warte auf Sensor...", 5, 30, colors.GREY)

    elif state.mode == 0:
        values = (
            ("%.1fC" % state.last_temp, "Temperatur", 26, colors.AMBER),
            ("%.0f%%" % state.last_hum, "Feuchte", 42, colors.CYAN),
            ("%.0fhPa" % state.last_pres, "Druck", 58, colors.LIGHTBLUE)
        )

        for value, label, y, color in values:
            lcd.text(value, 5, y, color)
            lcd.text_right(label, y, colors.LIGHTGREY)

    elif state.mode == 1:
        pct, label, color = sensors.iaq_relative(state.last_gas)

        lcd.text("%.0f kOhm" % state.last_gas, 5, 26, colors.WHITE)
        lcd.text(label, 5, 42, color)

        if pct is not None:
            lcd.text_right("%.0f%%" % pct, 42, colors.GREY)

    elif state.mode == 2:
        values = (
            ("Temp", state.min_temp, state.max_temp, 20, colors.LIGHTBLUE, colors.LIGHTRED, "%.1f"),
            ("Feuchte", state.min_hum, state.max_hum, 36, colors.LIGHTRED, colors.LIGHTBLUE, "%.0f"),
            ("Druck", state.min_pres, state.max_pres, 52, colors.DARKBLUE, colors.LIGHTCYAN, "%.0f")
        )

        for label, low, high, y, low_color, high_color, fmt in values:
            lcd.text(label, 5, y, colors.LIGHTGREY)
            lcd.text(fmt % low, 70, y, low_color)
            lcd.text(fmt % high, 115, y, high_color)

            if label == "Druck":
                swing_char = {"auf": "^", "ab": "v"}.get(sensors.pressure_swing(), "")
                if swing_char:
                    lcd.text(swing_char, 55, y, colors.WHITE)

    elif state.mode == 3:
        connected = state.wifi_active and state.wlan is not None and state.wlan.isconnected()

        lcd.text("Status", 5, 20, colors.LIGHTGREY)
        lcd.text_right(
            "ONLINE" if connected else ((state.wifi_note or "LINK?") if state.wifi_active else "OFFLINE"),
            20,
            colors.GREEN if connected else colors.RED
        )

        lcd.text("IP", 5, 36, colors.LIGHTGREY)
        lcd.text_right(state.ip or "--", 36, colors.LIGHTBLUE)

        lcd.text("Laufzeit", 5, 52, colors.LIGHTGREY)
        lcd.text_right(history.uptime(), 52, colors.WHITE)

    else:
        label, color = sensors.selftest_text()

        lcd.text("Pico-Temp", 5, 20, colors.LIGHTGREY)
        lcd.text_right("%.0fC" % sensors.internal_temp(), 20, colors.AMBER)

        lcd.text("Selbsttest", 5, 36, colors.LIGHTGREY)
        lcd.text_right(label, 36, color)

        lcd.text("RAM min", 5, 52, colors.LIGHTGREY)
        lcd.text_right("%d" % state.min_mem_free, 52, colors.YELLOW)

    lcd.fill_rect(0, 66, 160, 2, colors.GREY)
    lcd.text("CTRL WLAN A/B<>Mode", 2, 72, colors.GREY)
    lcd.show()


# ── Bildschirmschoner: Wechselseite mit grosser Schrift ─────
# Vier Seiten im Wechsel (SCREENSAVER_PAGE_MS): Uhrzeit, Temperatur,
# Luftfeuchte, Luftqualitaet - ein Wert sehr gross, darunter klein die
# Beschriftung. framebuf kennt nur die feste 8x8-Schrift. Fuer grosse Zeichen
# wird jedes Zeichen in einen 8x8-Puffer geschrieben und Pixel fuer Pixel als
# Quadrat gezeichnet. Gradzeichen (fehlt in der Schrift) und Doppelpunkt
# (dort 8 Spalten breit, nur 2 belegt) als eigene schmale Muster - sonst
# passt "12:34" nicht in die groesste Stufe.
_GLYPH_BUF = bytearray(8)
_GLYPH = framebuf.FrameBuffer(_GLYPH_BUF, 8, 8, framebuf.MONO_VLSB)
_NARROW = {
    "°": (0x02, 0x05, 0x02, 0x00),    # 4 Spalten, Bit 0 = oberste Zeile
    ":": (0x00, 0x24, 0x24, 0x00),    # Spalten 3-4 der 8x8-Schrift
}
_SS_AREA_W = 156                      # Platz fuer den grossen Wert
_SS_AREA_H = 56
_SS_LABEL_Y = 64


def _glyph_cols(ch):
    """Spalten eines Zeichens; MONO_VLSB = ein Byte pro Spalte, Bit 0 oben."""
    narrow = _NARROW.get(ch)
    if narrow is not None:
        return narrow
    _GLYPH.fill(0)
    _GLYPH.text(ch, 0, 0, 1)
    return _GLYPH_BUF


def _text_w(s, scale):
    return sum(len(_NARROW[ch]) if ch in _NARROW else 8 for ch in s) * scale


def _big_text(s, x, y, color, scale):
    for ch in s:
        cols = _glyph_cols(ch)
        for j in range(len(cols)):
            v = cols[j]
            yy = y
            while v:
                if v & 1:
                    lcd.fill_rect(x + j * scale, yy, scale, scale, color)
                v >>= 1
                yy += scale
        x += len(cols) * scale


def _fit_lines(text, max_scale):
    """Groesster Massstab, mit dem text einzeilig oder - an einem Leerzeichen
    geteilt - zweizeilig in die Wertflaeche passt."""
    for scale in range(max_scale, 0, -1):
        if _text_w(text, scale) <= _SS_AREA_W and 8 * scale <= _SS_AREA_H:
            return [text], scale
        if " " in text:
            a, b = text.split(" ", 1)
            if max(_text_w(a, scale), _text_w(b, scale)) <= _SS_AREA_W \
                    and 16 * scale + 2 <= _SS_AREA_H:
                return [a, b], scale
    return [text], 1


def draw_screensaver():
    page = state.screensaver_page
    if page == 0:
        sched = state.sched
        if sched is not None and sched.synced:
            lt = wifi_schedule.local_time()
            val = "%02d:%02d" % (lt[3], lt[4])
        else:
            val = "--:--"                 # noch kein Zeitabgleich seit dem Start
        color, label = colors.WHITE, "Uhrzeit"
    elif page == 1:
        val = "--" if state.last_temp is None else "%.1f°" % state.last_temp
        color, label = colors.AMBER, "Temperatur in °C"
    elif page == 2:
        val = "--" if state.last_hum is None else "%.0f%%" % state.last_hum
        color, label = colors.CYAN, "Luftfeuchte"
    else:
        if state.last_gas is None:
            val, color = "--", colors.GREY
        else:
            _, val, color = sensors.iaq_relative(state.last_gas)
        label = "Luftqualitaet"

    lines, scale = _fit_lines(val, 4)
    h = len(lines) * 8 * scale + (len(lines) - 1) * 2
    y = (_SS_AREA_H - h) // 2
    lcd.fill(colors.BLACK)
    for ln in lines:
        _big_text(ln, (lcd.width - _text_w(ln, scale)) // 2, y, color, scale)
        y += 8 * scale + 2
    _big_text(label, (lcd.width - _text_w(label, 1)) // 2, _SS_LABEL_Y, colors.LIGHTGREY, 1)
    lcd.show()

# EOF 2026-11-11
