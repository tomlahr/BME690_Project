# colors.py
# Farbkonstanten im BGR565-Format. Eigenes, abhaengigkeitsfreies Modul, damit
# sowohl display.py als auch sensors.py (selftest_text/iaq_relative geben
# Farben zurueck) sie nutzen koennen, ohne sich gegenseitig zu importieren.

BLACK = 0x0000
WHITE = 0xFFFF
GREY = 0x6D6B
LIGHTGREY = 0x59CE
AMBER = 0x80FD
CYAN = 0xFB06
GREEN = 0xE007
YELLOW = 0xE0FF
RED = 0x00F8
LIGHTBLUE = 0xBF64
LIGHTRED = 0x2CFB
DARKBLUE = 0x9602
LIGHTCYAN = 0x3F97

# EOF 2026-09-23
