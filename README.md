# PicoBME690 – Indoor Climate Station

Indoor climate station built on a **Raspberry Pi Pico 2 W**, a **Bosch BME690** sensor and a **Waveshare Pico-LCD-0.96** display, written in MicroPython.

It measures temperature, humidity, air pressure and gas resistance, shows the values on the small LCD and serves a live web dashboard on your home network.

*AI-assisted hobby project.*

## Contents

- [Features](#features)
- [Hardware](#hardware)
- [Wiring](#wiring)
- [Installation](#installation)
- [Controls](#controls)
- [Calibration](#calibration)
- [Files](#files)
- [Related project](#related-project)
- [License](#license)

## Features

- Five LCD pages: Climate, Gas / IAQ, Min / Max, Wi-Fi, System
- Screensaver with dimmed backlight after 5 minutes of inactivity
- Web dashboard with live values (updated every 5 s) and 3-hour history charts (SVG)
- JSON endpoint at `/data` for use in other tools, e.g. Home Assistant
- Weather trend derived from air pressure (linear regression over 3 hours)
- Relative air quality (IAQ) from gas resistance, with the baseline stored in flash and a 20-minute warm-up after boot
- Humidity corrected to the calibrated temperature (Magnus formula) plus sensor trim
- Wi-Fi with automatic reconnect, status messages and interface reset after repeated failures

**Note on IAQ:** The air quality value is a *relative* score based on the range of gas resistance the sensor has seen recently. It is not Bosch's BSEC IAQ index and does not measure specific gases or CO₂.

## Hardware

| Part | Details |
|---|---|
| Raspberry Pi Pico 2 W | RP2350 with Wi-Fi – [datasheet](https://pip-assets.raspberrypi.com/categories/1088-raspberry-pi-pico-2-w/documents/RP-008304-DS-3-pico-2-w-datasheet.pdf) |
| Bosch BME690 breakout | I²C, address `0x76` – [product page](https://www.bosch-sensortec.com/en/products/environmental-sensors/gas-sensors/bme690#technical) |
| Waveshare Pico-LCD-0.96 (WS 19653) | 0.96" LCD, 160×80, ST7735S, SPI, joystick and buttons – [wiki](https://www.waveshare.com/wiki/Pico-LCD-0.96) |

The hardware is relatively easy to put together; some soldering experience helps.

## Wiring

The display plugs directly onto the Pico. The BME690 connects via I²C:

| BME690 | Pico 2 W |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | GP4 |
| SCL | GP5 |

All pin assignments live in [`src/config.py`](src/config.py).

## Installation

1. Flash [Pimoroni MicroPython](https://github.com/pimoroni/pimoroni-pico) for the Pico 2 W (tested with v1.29.0-2). It provides `pimoroni_i2c` and `breakout_bme69x`; these libraries are not part of this repository.
2. Copy everything from the [`src`](src) folder to the root of the Pico (e.g. with Thonny), no subfolders.
3. On the Pico, rename `secrets_example.py` to `secrets.py` and enter your Wi-Fi credentials:

   ```python
   WIFI_SSID = "YourNetwork"
   WIFI_PASSWORD = "YourPassword"
   WIFI_COUNTRY = "DE"   # your country code
   ```

   **Never upload your real `secrets.py` to GitHub.**
4. Restart the Pico and press **CTRL** (joystick push) to turn on Wi-Fi. The IP address appears on the Wi-Fi page and in the REPL.
5. Open that IP address in a browser to see the dashboard.

To start Wi-Fi automatically at boot, uncomment `WIFI_AUTOSTART = True` in `config.py`. The hostname is set via `WIFI_HOSTNAME` in the same file.

## Controls

| Button | Action |
|---|---|
| A / joystick right | next page |
| B / joystick left | previous page |
| Joystick up / down | brightness |
| CTRL (joystick push) | Wi-Fi and web server on/off |

Status codes on the System page: `ONLINE`, `LINK?` (connecting), `OFFLINE`, or an error:
`NOAP` network not found, `AUTH` wrong password, `FAIL` rejected, `NOIP` no IP via DHCP.

## Calibration

The offsets in `config.py` apply to one specific setup, measuring interval and an active Wi-Fi connection. Recalibrate them for your own build and location.

| Setting | Current value | Meaning |
|---|---|---|
| `TEMP_OFFSET` | -3.2 | added to the raw value (self-heating from Pico, Wi-Fi, display and gas heater) |
| `HUMIDITY_TRIM` | 7.0 | percentage points added after the Magnus correction |
| `PRESSURE_OFFSET` | 1.0 | hPa, compared against a DWD reference station |

Findings from comparison measurements:

- Without a Wi-Fi connection the station reads about 1 °C lower, because the radio chip produces less heat.
- Direct sunlight and warm surfaces distort every measurement.
- The sensor runs on a 3-second interval; recalibrate the offset at the final location.
- Whether the humidity trim works better as a fixed amount or a factor will only become clear in dry heating-season air (35–45 %).

## Files

| File | Purpose |
|---|---|
| [`main.py`](src/main.py) | Initialisation, button handling (edge detection), main loop |
| [`config.py`](src/config.py) | Central settings: pins, intervals, calibration, IAQ, Wi-Fi |
| [`state.py`](src/state.py) | Shared state across all modules |
| [`sensors.py`](src/sensors.py) | Reads the BME690, applies calibration, self-test, status and trend texts |
| [`iaq.py`](src/iaq.py) | Relative air quality from gas resistance (shared with the Enviro+ project) |
| [`history.py`](src/history.py) | 3-hour history, deltas, linear regression, uptime |
| [`display.py`](src/display.py) | LCD driver (ST7735S, 160×80) and screen pages |
| [`colors.py`](src/colors.py) | Colour constants (BGR565) |
| [`web.py`](src/web.py) | HTML dashboard with SVG charts, JSON endpoint `/data` |
| [`wifi.py`](src/wifi.py) | Wi-Fi state machine with reconnect and web server polling |
| [`secrets_example.py`](src/secrets_example.py) | Template for your Wi-Fi credentials |

The station creates `iaq_baseline.txt` on the Pico by itself; it is not part of this repository.

## Related project

[Pimoroni-EnviroPlus-Board](https://github.com/tomlahr/Pimoroni-EnviroPlus-Board) – indoor environment monitor with the Pimoroni Enviro+ Pack on a Pico W, sharing the same IAQ module.

## License

[MIT](LICENSE)
