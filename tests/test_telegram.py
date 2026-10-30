#!/usr/bin/env python3
"""Uji format alert (Inggris & Indonesia) tanpa mengirim apa pun."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import i18n  # noqa: E402
import telegram  # noqa: E402


POOL = {
    "pool": "0x17db0f2014ec7bd0fa77d909ba3f68cef9a297246da04c026fece478a83d63d1",
    "mint": "0xd5d09671ba79e2aa01f7feddbff03ce20a3d0a39",
    "name": "DEBTCOIN / WETH 1%",
    "symbol": "DEBTCOIN",
    "dex": "uniswap-v4-robinhood",
    "age_sec": 252,
    "liq_usd": 22139.0,
    "mc_usd": 74470.0,
    "price_usd": 0.00000409517,
}

SEC = {
    "top10_pct": 22.5,
    "details": {
        "lp_status": "burned",
        "lp_pct": 100.0,
        "honeypot": False,
        "mintable": False,
        "owner_pct": 0.0,
        "buy_tax": 0.0,
        "sell_tax": 0.0,
    },
}

BUYERS = {"window_sec": 120, "buyers": 23, "buys": 31, "sells": 4}


class EnglishAlertTests(unittest.TestCase):
    def test_alert_contains_all_metrics(self):
        msg = telegram.format_alert(POOL, SEC, BUYERS, lang="en")
        self.assertIn("$DEBTCOIN", msg)
        self.assertIn("age 4m12s", msg)
        self.assertIn("MC <b>$74.5k</b>", msg)
        self.assertIn("Unique buyers 120s: <b>23</b> (31 buys / 4 sells)", msg)
        self.assertIn("Top 10: <b>22.5%</b> (excl. pool/burn)", msg)
        self.assertIn("honeypot clear", msg)
        self.assertIn("not mintable", msg)
        self.assertIn("owner 0.0%", msg)
        self.assertIn("Tax: buy 0 / sell 0", msg)
        self.assertIn("LP: <b>burned 100.0%</b>", msg)
        self.assertIn("Price: $0.00000409517", msg)
        self.assertNotIn("e-", msg)
        self.assertIn("dexscreener.com/robinhood/", msg)
        self.assertIn("CA: <code>0xd5d09671", msg)

    def test_risk_labels_are_not_hardcoded(self):
        sec = {
            "top10_pct": 10.0,
            "details": {
                "lp_status": "unknown",
                "honeypot": True,
                "mintable": True,
                "owner_pct": 42.0,
                "buy_tax": 10.0,
                "sell_tax": 12.0,
            },
        }
        msg = telegram.format_alert(POOL, sec, BUYERS, lang="en")
        self.assertIn("honeypot ⚠️", msg)
        self.assertIn("mintable ⚠️", msg)
        self.assertIn("owner 42.0%", msg)
        self.assertIn("Tax: buy 10 / sell 12", msg)
        self.assertIn("LP: <b>unknown</b>", msg)

    def test_unknown_security_never_claims_clear(self):
        sec = {"top10_pct": 10.0, "details": {"lp_status": "unknown"}}
        msg = telegram.format_alert(POOL, sec, BUYERS, lang="en")
        self.assertIn("honeypot unknown", msg)
        self.assertNotIn("honeypot clear", msg)

    def test_small_price_is_not_scientific(self):
        pool = dict(POOL, price_usd=9.094216389484412e-06)
        msg = telegram.format_alert(pool, SEC, BUYERS, lang="en")
        self.assertIn("Price: $0.0000090942164", msg)
        self.assertNotIn("e-06", msg)

    def test_delayed_banner_marks_detection_time(self):
        self.assertEqual(telegram._delayed_message("x", 29, lang="en"), "x")
        self.assertIn("Delayed 45s", telegram._delayed_message("x", 45, lang="en"))
        self.assertIn("Delayed 2m", telegram._delayed_message("x", 125, lang="en"))
        self.assertIn(
            "as of detection", telegram._delayed_message("x", 45, lang="en")
        )

    def test_symbol_is_escaped(self):
        pool = dict(POOL, symbol="<SCRIPT>")
        msg = telegram.format_alert(pool, SEC, BUYERS, lang="en")
        self.assertNotIn("<SCRIPT>", msg)
        self.assertIn("&lt;SCRIPT&gt;", msg)


class IndonesianAlertTests(unittest.TestCase):
    def test_alert_uses_indonesian_labels(self):
        sec = {
            "top10_pct": 22.5,
            "details": {
                "lp_status": "unlocked",
                "lp_pct": 12.5,
                "honeypot": False,
                "mintable": False,
                "owner_pct": 1.0,
                "buy_tax": 0.0,
                "sell_tax": 0.0,
            },
        }
        msg = telegram.format_alert(POOL, sec, BUYERS, lang="id")
        self.assertIn("umur 4m12s", msg)
        self.assertIn("MC <b>$74.5k</b> · Likuiditas <b>$22.1k</b>", msg)
        self.assertIn("Buyer unik 120s: <b>23</b> (31 beli / 4 jual)", msg)
        self.assertIn("Top 10: <b>22.5%</b> (di luar pool/burn)", msg)
        self.assertIn("Kontrak: honeypot aman", msg)
        self.assertIn("LP: <b>terbuka 12.5%</b>", msg)
        self.assertIn("Harga: $0.00000409517", msg)

    def test_indonesian_unknown_and_delay_banner(self):
        sec = {"top10_pct": 10.0, "details": {"lp_status": "unknown"}}
        msg = telegram.format_alert(POOL, sec, BUYERS, lang="id")
        self.assertIn("tidak diketahui", msg)
        self.assertIn("LP: <b>tidak diketahui</b>", msg)

        delayed = telegram._delayed_message("x", 45, lang="id")
        self.assertIn("Tertunda 45s", delayed)
        self.assertIn("saat deteksi", delayed)


class LanguageNormalizationTests(unittest.TestCase):
    def test_supported_and_fallback(self):
        self.assertEqual(i18n.normalize("en"), "en")
        self.assertEqual(i18n.normalize("ID"), "id")
        self.assertEqual(i18n.normalize("xx"), "en")
        self.assertEqual(i18n.normalize(None), "en")

    def test_modes(self):
        self.assertEqual(i18n.normalize_mode("both"), "both")
        self.assertEqual(i18n.normalize_mode("ID"), "id")
        self.assertEqual(i18n.normalize_mode("xx"), "en")
        self.assertEqual(i18n.langs("both"), ("en", "id"))
        self.assertEqual(i18n.langs("id"), ("id",))
        # "both" bukan bahasa konkret: teks jatuh ke default, bukan error.
        self.assertEqual(i18n.normalize("both"), "en")

    def test_status_labels(self):
        self.assertEqual(i18n.status_label("en", "unlocked"), "open")
        self.assertEqual(i18n.status_label("id", "unlocked"), "terbuka")
        self.assertEqual(i18n.status_label("en", "weird"), "weird")


class TranslationCoverageTests(unittest.TestCase):
    def test_every_key_exists_in_both_languages(self):
        en = set(i18n.STRINGS["en"])
        id_ = set(i18n.STRINGS["id"])
        self.assertEqual(en - id_, set(), "key hanya ada di EN: %s" % (en - id_))
        self.assertEqual(id_ - en, set(), "key hanya ada di ID: %s" % (id_ - en))

    def test_placeholders_match_between_languages(self):
        import re

        pattern = re.compile(r"%\([a-z_]+\)[sd]|%[sdf]|%%")
        for key, en_text in i18n.STRINGS["en"].items():
            id_text = i18n.STRINGS["id"][key]
            self.assertEqual(
                sorted(pattern.findall(en_text)),
                sorted(pattern.findall(id_text)),
                "placeholder %s tidak sama" % key,
            )

    def test_no_english_leftover_in_indonesian_alert(self):
        msg = telegram.format_alert(POOL, SEC, BUYERS, lang="id")
        for word in ("Price:", "Unique buyers", "Contract:", "Tax:", "age "):
            self.assertNotIn(word, msg)


class DualLanguageTests(unittest.TestCase):
    def setUp(self):
        self._old = config.ALERT_LANG
        config.ALERT_LANG = "both"
        self.addCleanup(setattr, config, "ALERT_LANG", self._old)

    def test_auto_returns_both_versions(self):
        import json

        payload = telegram.format_alert_auto(POOL, SEC, BUYERS)
        data = json.loads(payload)
        self.assertEqual(set(data), {"en", "id"})
        self.assertEqual(data["en"], telegram.format_alert(POOL, SEC, BUYERS, lang="en"))
        self.assertEqual(data["id"], telegram.format_alert(POOL, SEC, BUYERS, lang="id"))

    def test_single_message_contains_both_blocks(self):
        import json

        payload = json.loads(telegram.format_alert_auto(POOL, SEC, BUYERS))
        text = telegram._render(payload, 45)
        self.assertIn("<b>EN</b>", text)
        self.assertIn("<b>ID</b>", text)
        self.assertIn(telegram.DIVIDER, text)
        # Banner keterlambatan ikut bahasa masing-masing blok.
        self.assertIn("Delayed 45s", text)
        self.assertIn("Tertunda 45s", text)
        self.assertIn("Price:", text)
        self.assertIn("Harga:", text)
        self.assertNotIn("e-0", text)

    def test_plain_queue_row_from_before_is_still_sent(self):
        text = telegram._render("pesan lama", 0)
        self.assertEqual(text, "pesan lama")

    def test_test_message_is_dual(self):
        from unittest import mock

        with mock.patch.object(telegram, "send", return_value=(True, "ok")) as sent:
            telegram.send_test()
        text = sent.call_args[0][0]
        self.assertIn("<b>EN</b>", text)
        self.assertIn("<b>ID</b>", text)
        self.assertIn("Robinhood Pool Screener is ready", text)
        self.assertIn("Robinhood Pool Screener siap", text)

    def test_single_language_mode_stays_plain(self):
        config.ALERT_LANG = "id"
        payload = telegram.format_alert_auto(POOL, SEC, BUYERS)
        self.assertIsInstance(payload, str)
        self.assertIn("Harga:", payload)
        self.assertNotIn("<b>ID</b>", telegram._render(payload, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
