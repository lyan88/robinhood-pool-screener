#!/usr/bin/env python3
"""Teks yang dilihat pengguna (alert Telegram), dalam bahasa Inggris/Indonesia."""

DEFAULT_LANG = "en"
SUPPORTED = ("en", "id")

STRINGS = {
    "en": {
        "line_meta": "%s · %s · age %s",
        "buyers": (
            "Unique buyers %(window)ds: <b>%(buyers)d</b> "
            "(%(buys)d buys / %(sells)d sells)"
        ),
        "top10": "Top 10: <b>%s</b> (excl. pool/burn)",
        "contract": "Contract: %s",
        "tax": "Tax: buy %s / sell %s",
        "lp": "LP: <b>%s</b>",
        "price": "Price: $%s",
        "safe": "clear",
        "risk": "RISK",
        "unknown": "unknown",
        "mintable": "mintable",
        "not_mintable": "not mintable",
        "owner": "owner %s",
        "lp_burned": "burned",
        "lp_locked": "locked",
        "lp_unlocked": "open",
        "lp_dead": "dead",
        "lp_unknown": "unknown",
        "delay_banner": (
            "⏳ <i>Delayed %s from detection — age & price below are as of "
            "detection.</i>"
        ),
        "test_ready": "✅ <b>Robinhood Pool Screener is ready</b>",
        "test_filter": (
            "Robinhood Chain (id %d). Filters: honeypot clear · not mintable · "
            "owner &lt; %.0f%% · tax ≤ %.0f%% · top10 &lt; %.0f%% · MC $%s–$%s · "
            "liq ≥ $%s · age &lt; %dm · ≥ %d unique buyers/%ds."
        ),
    },
    "id": {
        "line_meta": "%s · %s · umur %s",
        "buyers": (
            "Buyer unik %(window)ds: <b>%(buyers)d</b> "
            "(%(buys)d beli / %(sells)d jual)"
        ),
        "top10": "Top 10: <b>%s</b> (di luar pool/burn)",
        "contract": "Kontrak: %s",
        "tax": "Tax: beli %s / jual %s",
        "lp": "LP: <b>%s</b>",
        "price": "Harga: $%s",
        "safe": "aman",
        "risk": "BAHAYA",
        "unknown": "tidak diketahui",
        "mintable": "bisa mint",
        "not_mintable": "tidak bisa mint",
        "owner": "owner %s",
        "lp_burned": "burned",
        "lp_locked": "locked",
        "lp_unlocked": "terbuka",
        "lp_dead": "mati",
        "lp_unknown": "tidak diketahui",
        "delay_banner": (
            "⏳ <i>Tertunda %s dari deteksi — umur & harga di bawah adalah saat "
            "deteksi.</i>"
        ),
        "test_ready": "✅ <b>Robinhood Pool Screener siap</b>",
        "test_filter": (
            "Robinhood Chain (id %d). Filter: honeypot bersih · tidak mintable · "
            "owner &lt; %.0f%% · tax ≤ %.0f%% · top10 &lt; %.0f%% · MC $%s–$%s · "
            "likuiditas ≥ $%s · umur &lt; %dm · ≥ %d buyer unik/%ds."
        ),
    },
}


def normalize(lang):
    lang = (lang or DEFAULT_LANG).strip().lower()
    return lang if lang in SUPPORTED else DEFAULT_LANG


def text(lang, key):
    return STRINGS[normalize(lang)][key]


def status_label(lang, status):
    key = "lp_%s" % (status or "unknown")
    return STRINGS[normalize(lang)].get(key, status or "unknown")
