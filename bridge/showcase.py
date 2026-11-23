"""The scenario on the demo page: a quarter that looks fine at the product-line level.

Tariffs on China-origin parts went from 10% to 30% and were passed through as a 7% surcharge,
installer (DIFM) business grew at the two largest retailers, buyers moved from filters to
sensors, and units grew 3%.
"""

SHOWCASE = {
    "seed": 7,
    "changes": [
        {"type": "tariff_rate", "origin": "China", "rate": 0.30},
        {"type": "surcharge", "where": {"origin": "China"}, "pct": 0.07},
        {"type": "channel_shift", "customer": "Retailer A", "share": 0.35},
        {"type": "channel_shift", "customer": "Retailer B", "share": 0.35},
        {"type": "line_shift", "from": "Filters", "to": "Sensors", "share": 0.25},
        {"type": "volume", "pct": 0.03},
    ],
}
