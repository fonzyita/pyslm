"""Typical densities of metals used in L-PBF / SLM, for the part mass estimate."""

from typing import List, Tuple

# (name shown in the menu, density in g/cm^3). Values are typical for dense printed material; real alloys and
# heat treatments vary by a few percent.
MATERIALS: List[Tuple[str, float]] = [
    ("Acciaio generico", 7.85),
    # Aluminium
    ("Alluminio AlSi10Mg", 2.67),
    ("Alluminio 6061", 2.70),
    # Steels most used in metal 3D printing
    ("Acciaio inox 316L", 7.99),
    ("Acciaio inox 17-4 PH", 7.80),
    ("Acciaio maraging 1.2709", 8.10),
    ("Acciaio per utensili H13", 7.80),
    # Other engineering alloys
    ("Titanio Ti6Al4V", 4.43),
    ("Inconel 718", 8.19),
    ("Inconel 625", 8.44),
    ("Cobalto-cromo CoCrMo", 8.30),
    # Copper
    ("Rame puro", 8.96),
    ("Rame CuCrZr", 8.89),
    # Precious metals
    ("Oro 24 kt", 19.32),
    ("Oro 18 kt giallo", 15.50),
    ("Argento 925", 10.36),
    ("Platino 950", 20.70),
]

CUSTOM_MATERIAL = "Personalizzato"
