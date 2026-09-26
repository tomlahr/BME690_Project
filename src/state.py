# state.py
# Gemeinsamer, veraenderlicher Zustand ueber alle Module hinweg.
# Andere Module schreiben direkt state.last_temp = ... statt "global" zu
# nutzen - "global" wirkt nur innerhalb einer Datei, nicht ueber mehrere.

last_temp = None
last_pres = None
last_hum = None
last_gas = None
last_gas_reliable = False

min_temp = max_temp = None
min_hum = max_hum = None
min_pres = max_pres = None
min_gas = max_gas = None   # echte Extremwerte seit Start (wie Temp/Feuchte)
iaq = None                 # iaq.IAQ-Objekt, in main.py angelegt

history_temp = []
history_hum = []
history_pres = []
history_gas = []

selftest_results = []

wifi_active = False
wlan = None
server = None
ip = None
# Kurzer WLAN-Statustext fuer die System-Seite (z. B. "NOAP", "AUTH").
wifi_note = ""

mode = 0
brightness_idx = 1
boot_time = 0
min_mem_free = 0

screensaver_active = False
screensaver_x = 0
screensaver_dir = 1
last_activity = 0

# EOF 2026-09-26
