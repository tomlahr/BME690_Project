# web.py
# HTML-Dashboard, JSON-Endpoint, HTTP-Antworten senden/empfangen.

import gc

import config
import state
import sensors
import history


# Paket 2: Umlaute und Grad-Zeichen im Web-Dashboard. Das LCD bleibt bei
# ASCII (die eingebaute 8x8-Schrift von framebuf kennt keine Umlaute), deshalb
# liefern sensors.py-Texte weiter ASCII, und erst hier wird uebersetzt.
_DE = (
    ("aufwaermen...", "Aufwärmphase"),
    ("maessig", "mäßig"),
    ("gueltig", "gültig"),
    ("kuehl", "kühl"),
    ("pruefe", "prüfe"),
)


def _de(text):
    for ascii_text, german in _DE:
        text = text.replace(ascii_text, german)
    return text


def sparkline(values, color, min_span=0):
    # Paket 2: ganze Historie zeichnen (bis 3 h). Vorher stand hier
    # values[-60:] - das Diagramm zeigte nur die letzte Stunde, obwohl
    # Ueberschrift und "3h: ... bis ..." drei Stunden versprachen.

    if len(values) < 2:
        return (
            '<div class="chart-empty">'
            'Verlauf wird aufgebaut ...'
            '</div>'
        )

    low = min(values)
    high = max(values)

    # Mindesthoehe der Skala: sonst blaest die Autoskalierung kleinste
    # Schwankungen (0,1 C, 1 %) auf die volle Hoehe auf.
    if high - low < min_span:
        mid = (high + low) / 2
        low = mid - min_span / 2
        high = mid + min_span / 2

    span = high - low

    if span == 0:
        span = 1

    width = 320
    height = 70
    points = []

    for index, value in enumerate(values):
        x = index * width // (len(values) - 1)
        y = height - 5 - int((value - low) * (height - 10) / span)
        points.append("%d,%d" % (x, y))

    return (
        '<svg class="chart" viewBox="0 0 320 70" preserveAspectRatio="none">'
        '<polyline fill="none" stroke="%s" stroke-width="3" '
        'points="%s" />'
        '</svg>'
    ) % (color, " ".join(points))


def iaq_overlay():
    values = state.history_gas

    if len(values) < 2 or state.iaq is None or not state.iaq.ready:
        return (
            '<div class="overlay-empty" id="gas-overlay-box">'
            'IAQ-Trend wird aufgebaut ...'
            '</div>'
        )

    width = 320
    height = 46
    points = []

    for index, gas in enumerate(values):
        pct = (state.iaq.score(gas) or 0) * 100
        x = index * width // (len(values) - 1)
        y = height - 5 - int(pct * (height - 10) / 100)
        points.append("%d,%d" % (x, y))

    return (
        '<div class="iaq-overlay" id="gas-overlay-box">'
        '<svg viewBox="0 0 320 46" preserveAspectRatio="none">'
        '<polyline fill="none" stroke="rgba(255,255,255,0.75)" '
        'stroke-width="4" points="%s" />'
        '</svg>'
        '</div>'
    ) % " ".join(points)


def chart_card(title, values, color, unit, decimals=1, min_span=0):
    if values:
        current = ("%." + str(decimals) + "f") % values[-1]
        low = ("%." + str(decimals) + "f") % min(values)
        high = ("%." + str(decimals) + "f") % max(values)
        summary = "3h: %s bis %s %s" % (low, high, unit)
    else:
        current = "--"
        summary = "Noch keine Verlaufspunkte"

    return """<div class="chart-card">
<div class="chart-head"><span>%s</span><strong>%s %s</strong></div>
%s
<div class="chart-footer">%s</div>
</div>""" % (
        title,
        current,
        unit,
        sparkline(values, color, min_span),
        summary
    )


def pressure_chart():
    if state.history_pres:
        summary = "3h: %.1f bis %.1f hPa" % (min(state.history_pres), max(state.history_pres))
    else:
        summary = "Noch keine Verlaufspunkte"

    return """<div class="chart-card" id="pressure-card">
<div class="chart-head">
<span>Luftdruck</span>
<strong>%s hPa</strong>
</div>
%s
<div class="chart-footer">%s</div>
</div>""" % (
        "%.0f" % state.last_pres if state.last_pres is not None else "--",
        sparkline(state.history_pres, "#7fb3d5", 2),
        summary,
    )


def weather_banner():
    emoji, text = sensors.weather_trend()
    swing = sensors.pressure_swing()
    swing_symbol = {"auf": "&#8593;", "ab": "&#8595;"}.get(swing, "&#8212;")

    return """<div class="weather-box weather-box-full">
<div class="weather-emoji">%s</div>
<div class="trend-swing">10 min <span class="swing-arrow">%s</span> 20 min</div>
<div><strong>%s</strong><br><small>%s</small></div>
</div>""" % (
        emoji,
        swing_symbol,
        text,
        sensors.pressure_trend()
    )


def gas_chart():
    if state.last_gas is not None:
        pct, _, _ = sensors.iaq_relative(state.last_gas)
    else:
        pct = None

    marker_position = 50 if pct is None else int(pct)
    gas_10m = history.delta_from_history(state.history_gas, 10)

    return """<div class="chart-card">
<div class="chart-head">
<span>Gaswiderstand</span>
<strong>%s kOhm</strong>
</div>
<div class="iaq-scale">
<div class="iaq-marker" style="left:%d%%"></div>
</div>
<div class="iaq-legend">
<span>sehr schlecht</span><span>mäßig</span><span>gut</span>
</div>
%s
<div class="iaq-trend-text">IAQ-Trend: %s</div>
</div>""" % (
        "%.0f" % state.last_gas if state.last_gas is not None else "--",
        marker_position,
        iaq_overlay(),
        "Aufwärmphase" if pct is None else (
            "zunehmend besser" if gas_10m is not None and gas_10m > 0
            else "stabil bis fallend"
        )
    )


def json_data():
    if state.last_gas is not None:
        pct, label, _ = sensors.iaq_relative(state.last_gas)
    else:
        pct, label = None, "--"

    temp_10m = history.delta_from_history(state.history_temp, 10)
    hum_10m = history.delta_from_history(state.history_hum, 10)
    # Paket 1 (2026-09-23): dieselbe Ausgleichsgerade wie
    # sensors.pressure_trend() - vorher rechnete das JSON mit nur zwei
    # Randpunkten, und beide Aussagen konnten sich widersprechen.
    pres_3h = history.linreg_change(state.history_pres, config.PRESSURE_TREND_WINDOW_MIN)
    gas_10m = history.delta_from_history(state.history_gas, 10)

    def value(number, fmt):
        return fmt % number if number is not None else "--"

    return (
        '{"temp":"%s","hum":"%s","pres":"%s","gas":"%s",'
        '"iaq":"%s","gas_status":"%s","comfort":"%s",'
        '"pressure_trend":"%s","temp_trend":"%s",'
        '"hum_trend":"%s","pres_trend":"%s",'
        '"gas_trend":"%s","uptime":"%s"}'
    ) % (
        value(state.last_temp, "%.1f"),
        value(state.last_hum, "%.0f"),
        value(state.last_pres, "%.0f"),
        value(state.last_gas, "%.0f"),
        _de(label),
        _de(sensors.gas_status_text()),
        _de(sensors.comfort_text()),
        sensors.pressure_trend(),
        history.signed_value(temp_10m, 1, " °C / 10 min"),
        history.signed_value(hum_10m, 0, " % / 10 min"),
        history.signed_value(pres_3h, 1, " hPa / 3 h"),
        history.signed_value(gas_10m, 0, " kOhm / 10 min"),
        history.uptime()
    )


def html_page():
    if state.last_gas is not None:
        _, label, _ = sensors.iaq_relative(state.last_gas)
    else:
        label = "--"

    iaq_color = {
        "gut": "#2ecc71",
        "maessig": "#f39c12",
        "schlecht": "#e74c3c",
        "sehr schlecht": "#8e44ad"
    }.get(label, "#888")

    def value(number, fmt):
        return fmt % number if number is not None else "--"

    def minmax(low, high, fmt):
        if low is None:
            return "--"

        return "min " + fmt % low + " &middot; max " + fmt % high

    charts = (
        chart_card("Temperatur", state.history_temp, "#f5b041", "°C", 1, 1.0) +
        chart_card("Luftfeuchte", state.history_hum, "#4fc3f7", "%", 0, 4) +
        pressure_chart() +
        gas_chart()
    )

    return """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>PicoBME690</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #1a1a2e;
    color: #eee;
    margin: 0;
    padding: 20px;
}

h1 {
    color: #00d4ff;
    text-align: center;
    font-size: 1.45em;
    margin-bottom: 20px;
}

h2 {
    max-width: 620px;
    margin: 28px auto 12px;
    color: #9bb7ff;
    font-size: 1em;
}

.grid, .chart-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    max-width: 620px;
    margin: 0 auto;
}

.card, .iaq-card, .chart-card {
    background: #16213e;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
    border: 1px solid #0f3460;
}

.card .label, .iaq-card .label {
    font-size: 0.75em;
    color: #aaa;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
}

.card .value {
    font-size: 1.8em;
    font-weight: bold;
    color: #00d4ff;
}

.card .subvalue {
    color: #8ea6d7;
    font-size: 0.72em;
    margin-top: 7px;
}

.card .minmax, .iaq-card .minmax {
    font-size: 0.7em;
    color: #6a7ba5;
    margin-top: 6px;
}

.iaq-card {
    grid-column: 1 / -1;
}

.iaq-value {
    font-size: 2em;
    font-weight: bold;
    color: %s;
    text-align: center;
}

.status {
    text-align: center;
    color: #9bb7ff;
    font-size: 0.72em;
    margin-top: 8px;
}

.chart-card {
    padding: 12px;
    min-width: 0;
    display: flex;
    flex-direction: column;
}

.chart-head {
    display: flex;
    justify-content: space-between;
    color: #aaa;
    font-size: 0.72em;
    margin-bottom: 8px;
}

.chart-head strong {
    color: #eee;
    font-size: 1.05em;
}

.chart {
    width: 100%%;
    flex: 1;
    min-height: 70px;
    max-height: 180px;
    background: #101a31;
    border-radius: 6px;
}

.chart-empty {
    flex: 1;
    min-height: 70px;
    max-height: 180px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6a7ba5;
    font-size: 0.7em;
    background: #101a31;
    border-radius: 6px;
}

.overlay-empty {
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #6a7ba5;
    font-size: 0.7em;
    background: #101a31;
    border-radius: 6px;
}

.chart-footer {
    color: #6a7ba5;
    font-size: 0.68em;
    margin-top: 6px;
}

.weather-box {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    text-align: left;
    background: #101a31;
    border-radius: 7px;
    padding: 10px;
    margin-top: 10px;
    font-size: 0.75em;
}

.weather-box-full {
    grid-column: 1 / -1;
    margin-top: 0;
}

.trend-swing {
    font-size: 0.72em;
    color: #8095c5;
    white-space: nowrap;
}

.swing-arrow {
    font-size: 1.3em;
    color: #eee;
    padding: 0 2px;
}

.weather-emoji {
    font-size: 2em;
}

.weather-box strong {
    color: #b9d8ff;
}

.weather-box small {
    color: #8095c5;
}

.iaq-scale {
    position: relative;
    height: 17px;
    border-radius: 10px;
    background: linear-gradient(
        90deg,
        #8e44ad 0%%,
        #e74c3c 25%%,
        #f39c12 50%%,
        #f1e05a 70%%,
        #2ecc71 100%%
    );
    margin: 15px 3px 7px;
}

.iaq-marker {
    position: absolute;
    top: -5px;
    width: 9px;
    height: 27px;
    border-radius: 5px;
    transform: translateX(-50%%);
    background: rgba(255,255,255,0.9);
    box-shadow: 0 0 0 2px rgba(0,0,0,0.3);
}

.iaq-legend {
    display: flex;
    justify-content: space-between;
    color: #a8afc1;
    font-size: 0.62em;
}

.iaq-trend-text {
    text-align: center;
    color: #6a7ba5;
    font-size: 0.72em;
    margin: 6px 0 0;
}

.iaq-overlay {
    height: 36px;
    background: linear-gradient(
        180deg,
        rgba(255,255,255,0.03),
        rgba(255,255,255,0.12)
    );
    border-radius: 6px;
    overflow: hidden;
}

.iaq-overlay svg {
    width: 100%%;
    height: 100%%;
}

.footer {
    text-align: center;
    color: #7a8bb5;
    font-size: 0.75em;
    max-width: 620px;
    margin: 20px auto 0;
    padding-top: 12px;
    border-top: 1px solid #2a3a5c;
}

@media (max-width: 500px) {
    .chart-grid {
        grid-template-columns: 1fr;
    }
}
</style>
</head>

<body>
<h1>PicoBME690 &#x1F321;&#xFE0F; Wetterstation</h1>

<div class="grid">

<div class="card">
<div class="label">Temperatur</div>
<div class="value" id="temp">%s&deg;C</div>
<div class="subvalue" id="temp-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Luftfeuchte</div>
<div class="value" id="hum">%s%%</div>
<div class="subvalue" id="hum-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Luftdruck</div>
<div class="value" id="pres">%s hPa</div>
<div class="subvalue" id="pres-trend">--</div>
<div class="minmax">%s</div>
</div>

<div class="card">
<div class="label">Gaswiderstand</div>
<div class="value" id="gas">%s kOhm</div>
<div class="subvalue" id="gas-trend">--</div>
<div class="minmax">%s</div>
</div>

%s

<div class="iaq-card">
<div class="label">Luftqualität (relativ)</div>
<div class="iaq-value" id="iaq">%s</div>
<div class="status" id="gas-status">%s</div>
<div class="minmax">
Komfort: <span id="comfort">%s</span>
&middot;
Luftdruck: <span id="pressure-trend">%s</span>
</div>
</div>

</div>

<h2>Verlauf der letzten drei Stunden</h2>
<div class="chart-grid">
%s
</div>

<div class="footer">
Messwerte alle 5 s aktualisiert | Diagramme jede Minute aktualisiert<br>
IP: %s | Laufzeit: <span id="uptime">%s</span> | Pico: ~%s °C (grob)
</div>

<script>
function setText(id, value) {
    var node = document.getElementById(id);
    if (node) {
        node.textContent = value;
    }
}

function syncGasBoxHeight() {
    var card = document.getElementById("pressure-card");
    var gasBox = document.getElementById("gas-overlay-box");
    if (!card || !gasBox) {
        return;
    }
    var refBox = card.querySelector(".chart, .chart-empty");
    if (!refBox) {
        return;
    }
    gasBox.style.height = refBox.offsetHeight + "px";
}

function refreshValues() {
    fetch("/data", {cache: "no-store"})
        .then(function(response) {
            return response.json();
        })
        .then(function(data) {
            setText("temp", data.temp + " °C");
            setText("hum", data.hum + "%%");
            setText("pres", data.pres + " hPa");
            setText("gas", data.gas + " kOhm");
            setText("iaq", data.iaq);
            setText("gas-status", data.gas_status);
            setText("comfort", data.comfort);
            setText("pressure-trend", data.pressure_trend);
            setText("temp-trend", data.temp_trend);
            setText("hum-trend", data.hum_trend);
            setText("pres-trend", data.pres_trend);
            setText("gas-trend", data.gas_trend);
            setText("uptime", data.uptime);
        })
        .catch(function() {});
}

refreshValues();
syncGasBoxHeight();
setInterval(refreshValues, 5000);
window.addEventListener("resize", syncGasBoxHeight);
</script>

</body>
</html>""" % (
        iaq_color,
        value(state.last_temp, "%.1f"),
        minmax(state.min_temp, state.max_temp, "%.1f"),
        value(state.last_hum, "%.0f"),
        minmax(state.min_hum, state.max_hum, "%.0f"),
        value(state.last_pres, "%.0f"),
        minmax(state.min_pres, state.max_pres, "%.0f"),
        value(state.last_gas, "%.0f"),
        minmax(state.min_gas, state.max_gas, "%.0f"),
        weather_banner(),
        _de(label),
        _de(sensors.gas_status_text()),
        _de(sensors.comfort_text()),
        sensors.pressure_trend(),
        charts,
        state.ip or "--",
        history.uptime(),
        "%.0f" % sensors.internal_temp()
    )


def send_all(conn, data):
    view = memoryview(data)
    offset = 0

    while offset < len(view):
        sent = conn.send(view[offset:])

        if sent is None or sent <= 0:
            raise OSError("Verbindung beim Senden geschlossen")

        offset += sent


def send_response(conn, content_type, body, status="200 OK"):
    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ) % (status, content_type, len(body))

    send_all(conn, header.encode("utf-8"))
    send_all(conn, body)


def _drain(conn):
    """Ungelesene Anfragedaten verwerfen, bevor close() laeuft. Liegen noch
    Bytes im Empfangspuffer (z.B. Anfrage > 1024 Bytes durch Cookies),
    schickt lwIP beim close() ein RST statt FIN - der Browser meldet dann
    ERR_CONNECTION_RESET, obwohl die Antwort vollstaendig ankam."""
    try:
        conn.setblocking(False)
        for _ in range(8):
            if not conn.recv(256):
                break
    except Exception:
        pass


def handle_request(conn):
    try:
        conn.settimeout(2)
        request = conn.recv(1024)

        if not request:
            return

        if request.startswith(b"GET /favicon.ico"):
            send_response(conn, "text/plain", b"", "204 No Content")

        elif request.startswith(b"GET /data"):
            gc.collect()
            body = json_data().encode("utf-8")
            send_response(conn, "application/json; charset=utf-8", body)

        else:
            gc.collect()
            body = html_page().encode("utf-8")
            send_response(conn, "text/html; charset=utf-8", body)

    except OSError as error:
        code = error.args[0] if error.args else 0

        # Normale Browserabbrüche nicht in der REPL ausgeben.
        if code not in (104, 110):
            print("Webserverfehler:", error)

    except Exception as error:
        print("Webserverfehler:", error)

    finally:
        _drain(conn)
        conn.close()
        gc.collect()

# EOF 2026-09-26
