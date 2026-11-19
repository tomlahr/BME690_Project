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
- [Home Assistant (MQTT)](#home-assistant-mqtt)
- [Log file](#log-file)
- [Calibration](#calibration)
- [Files](#files)
- [Related project](#related-project)
- [License](#license)

## Features

- Five LCD pages: Climate, Gas / IAQ, Min / Max, Wi-Fi, System
- Screensaver after 2 minutes of inactivity: time, temperature, humidity and air quality in large type, one value every 4 seconds, at the lowest brightness step
- Web dashboard with live values (updated every 5 s) and 3-hour history charts (SVG)
- JSON endpoint at `/data` for use in other tools
- Home Assistant integration via MQTT with auto-discovery (no YAML needed in Home Assistant)
- Hourly log file `log.csv` on the Pico for troubleshooting (one line per hour: climate averages, sensor errors, free RAM, loop timing, Wi-Fi and MQTT errors), rotated to `log.csv.old` at 24 kB
- Web dashboard, MQTT and the log can be switched on or off independently in `config.py`
- Weather trend derived from air pressure (linear regression over 3 hours)
- Relative air quality (IAQ) from gas resistance, with the baseline stored in flash and a 20-minute warm-up after boot
- Humidity corrected to the calibrated temperature (Magnus formula) plus sensor trim
- Wi-Fi with automatic reconnect, status messages and interface reset after repeated failures
- Self-test on the System page; a missing or failing sensor shows `Fehler`, and the station keeps running and reconnects to the sensor on its own
- Wi-Fi switches off at night (00:00–06:00 local time, NTP time with CET/CEST) to match the router's Wi-Fi schedule

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

   MQTT_USER = "your_mqtt_user"           # only needed for Home Assistant
   MQTT_PASSWORD = "your_mqtt_password"
   ```

   **Never upload your real `secrets.py` to GitHub.**
4. Restart the Pico. Wi-Fi starts automatically; the IP address appears on the Wi-Fi page and in the REPL.
5. Open that IP address in a browser to see the dashboard.

Wi-Fi starts at boot (`WIFI_AUTOSTART = True` in `config.py`) and switches off between `WIFI_OFF_FROM` and `WIFI_OFF_UNTIL`. The time comes via NTP (`NTP_HOSTS`, default `pool.ntp.org`) as soon as Wi-Fi is connected. Without a valid time the schedule does nothing and Wi-Fi stays on. The hostname is set via `WIFI_HOSTNAME`.

## Controls

| Button | Action |
|---|---|
| A / joystick right | next page |
| B / joystick left | previous page |
| Joystick up / down | brightness |
| CTRL (joystick push) | Wi-Fi on/off (with web server and MQTT); overrides the night schedule until the next switching time |

Status codes on the Wi-Fi page: `ONLINE`, `LINK?` (connecting), `OFFLINE`, or an error:
`NOAP` network not found, `AUTH` wrong password, `FAIL` rejected, `NOIP` no IP via DHCP.

## Home Assistant (MQTT)

The station publishes its readings to an MQTT broker (e.g. the Mosquitto add-on in Home Assistant). Home Assistant creates the device and all entities automatically via MQTT discovery.

**Requirements**

- An MQTT broker reachable from the Pico, and the MQTT integration set up in Home Assistant
- `umqtt.simple` from micropython-lib in `/lib` on the Pico (e.g. via Thonny's package manager). A version with `connect(timeout=...)` is required (current micropython-lib releases have it); with an older version MQTT does not connect. Check in the REPL: `print('timeout=None' in open('/lib/umqtt/simple.py').read())` must print `True`
- `MQTT_USER` and `MQTT_PASSWORD` in `secrets.py`. Without them, MQTT stays off and everything else runs normally

**Settings in `config.py`**

| Setting | Default | Meaning |
|---|---|---|
| `WEB_ENABLED` | `True` | web dashboard on port 80; `False` does not even load `web.py` (saves RAM) |
| `MQTT_ENABLED` | `True` | MQTT on/off |
| `LOG_ENABLED` | `True` | hourly log `log.csv` on/off (see [Log file](#log-file)) |
| `MQTT_HOST` / `MQTT_PORT` | `192.168.178.25` / `1883` | broker address |
| `MQTT_NODE_ID` | `pico_bme690` | client ID, topic name and base of the unique IDs; must be unique per device |
| `MQTT_DEVICE_NAME` | `pico_bme690` | device name in Home Assistant, base of the entity IDs |
| `MQTT_PUBLISH_MS` | `60000` | state is sent every 60 s, not on every 3 s measurement |

All switches take effect at boot. Wi-Fi, NTP and the night schedule keep running when both are off.

**Topics**

| Topic | Content | Retained |
|---|---|---|
| `homeassistant/sensor/pico_bme690/<key>/config` | discovery configuration, one per entity | yes |
| `pico/pico_bme690/state` | all values as one JSON object | no |
| `pico/pico_bme690/status` | `online` / `offline` (last will) | yes |

**Entities**

Temperature, humidity, air pressure, gas resistance, relative air quality (%) and air quality as text. Diagnostic entities: Wi-Fi signal, uptime, self-test and free memory. Gas resistance and relative air quality report `null` (unknown) while the gas heater is not stable and during the 20-minute warm-up.

**Behaviour**

- Non-blocking: the client is a small state machine in the main loop, like the Wi-Fi handling. Connecting and sending can each block for at most 2 s (`MQTT_TIMEOUT_S`); a failed connection attempt always closes its socket. After a failure it waits 15 s, doubling up to 5 minutes
- Before Wi-Fi is switched off (night schedule or CTRL), the station reports `offline` itself. After a power loss the broker sends the last will after about 3 minutes
- At night (Wi-Fi off) nothing is sent and the entities show as unavailable. Readings are not buffered, because Home Assistant would store late MQTT values with their arrival time, not the measurement time

## Log file

The station writes one line per hour to `log.csv` on the Pico (separator `;`), plus a line `# Start;<reset cause>;<local time>;after N s` after every boot. It is written once the clock is set via NTP (usually a few seconds after boot), or after 60 s with `-` if there is no time yet. The file is rotated to `log.csv.old` above `LOG_MAX_BYTES` (24 kB), so both files together hold about four weeks. With 24 writes per day the flash wear is negligible. Copy the file off the Pico with Thonny and open it in a spreadsheet.

| Column | Meaning |
|---|---|
| `ab` | start of the hour, local time (`-` before the first NTP sync) |
| `n` / `fehler` | measurements in that hour / measurements that failed the self-test |
| `temp`, `hum`, `hpa`, `gas`, `iaq` | hourly averages (°C, %, hPa, kΩ, relative IAQ %) |
| `ram_min` / `block` | lowest free RAM / largest free heap block at write time (kB) |
| `loop_max` / `ruckler` | longest main-loop pass (ms) / passes over 250 ms |
| `wlan_err` | failed Wi-Fi connection attempts plus connection losses |
| `mqtt_ok` / `mqtt_err` | states sent / MQTT connection or send errors |
| `wlan` | Wi-Fi connected at the end of the hour (1/0) |

When the column layout changes, the old file is moved to `log.csv.old` and a new one starts with the new header.

## Calibration

The offsets in `config.py` apply to one specific setup, measuring interval and an active Wi-Fi connection. Recalibrate them for your own build and location.

| Setting | Current value | Meaning |
|---|---|---|
| `TEMP_OFFSET` | -3.2 | added to the raw value (self-heating from Pico, Wi-Fi, display and gas heater) |
| `HUMIDITY_TRIM` | 7.0 | percentage points added after the Magnus correction |
| `PRESSURE_OFFSET` | 1.0 | hPa, compared against a DWD reference station |

Findings from comparison measurements:

- Without a Wi-Fi connection the station reads about 1 °C lower, because the radio chip produces less heat. With the night schedule this applies every night between 00:00 and 06:00.
- Direct sunlight and warm surfaces distort every measurement.
- The sensor runs on a 3-second interval; recalibrate the offset at the final location.
- Whether the humidity trim works better as a fixed amount or a factor will only become clear in dry heating-season air (35–45 %).

## Files

| File | Purpose |
|---|---|
| [`main.py`](src/main.py) | Initialisation, button handling (edge detection), main loop |
| [`config.py`](src/config.py) | Central settings: pins, intervals, calibration, IAQ, Wi-Fi |
| [`state.py`](src/state.py) | Shared state across all modules |
| [`sensors.py`](src/sensors.py) | Reads the BME690, applies calibration, self-test, status and trend texts, German umlaut translation for web and MQTT |
| [`iaq.py`](src/iaq.py) | Relative air quality from gas resistance (shared with the Enviro+ project) |
| [`history.py`](src/history.py) | 3-hour history, deltas, linear regression, uptime |
| [`display.py`](src/display.py) | LCD driver (ST7735S, 160×80) and screen pages |
| [`colors.py`](src/colors.py) | Colour constants (BGR565) |
| [`web.py`](src/web.py) | HTML dashboard with SVG charts, JSON endpoint `/data` |
| [`wifi.py`](src/wifi.py) | Wi-Fi state machine with reconnect and web server polling |
| [`mqtt.py`](src/mqtt.py) | Home Assistant integration via MQTT discovery (non-blocking) |
| [`hourlog.py`](src/hourlog.py) | Hourly log `log.csv` for troubleshooting (same scheme as the Enviro+ project) |
| [`wifi_schedule.py`](src/wifi_schedule.py) | Night-time Wi-Fi schedule with NTP and CET/CEST (shared with the Enviro+ project) |
| [`secrets_example.py`](src/secrets_example.py) | Template for your Wi-Fi and MQTT credentials |

The station creates `iaq_baseline.txt`, `log.csv` and `log.csv.old` on the Pico by itself; they are not part of this repository.

## Related project

[Pimoroni-EnviroPlus-Board](https://github.com/tomlahr/Pimoroni-EnviroPlus-Board) – indoor environment monitor with the Pimoroni Enviro+ Pack on a Pico W, sharing the same IAQ module.

## License

[MIT](LICENSE)
