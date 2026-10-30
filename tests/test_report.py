#!/usr/bin/env python3
"""Uji laporan harian dalam mode en / id / both, tanpa jaringan."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import report  # noqa: E402


class ReportLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self._old = (config.DB_PATH, config.DATA_DIR, config.ALERT_LANG)
        config.DB_PATH = base / "report.db"
        config.DATA_DIR = base
        self.addCleanup(self._restore)

    def _restore(self):
        config.DB_PATH, config.DATA_DIR, config.ALERT_LANG = self._old

    def test_english_report(self):
        config.ALERT_LANG = "en"
        text = report.build(hours=1)
        self.assertIn("Robinhood Pool Screener report", text)
        self.assertIn("No measured outcomes", text)
        self.assertNotIn("Laporan", text)

    def test_indonesian_report(self):
        config.ALERT_LANG = "id"
        text = report.build(hours=1)
        self.assertIn("Laporan Robinhood Pool Screener", text)
        self.assertIn("Belum ada outcome", text)
        self.assertNotIn("No measured outcomes", text)

    def test_both_mode_has_two_sections(self):
        config.ALERT_LANG = "both"
        text = report.build(hours=1)
        self.assertIn("<b>EN</b>", text)
        self.assertIn("<b>ID</b>", text)
        self.assertIn("Robinhood Pool Screener report", text)
        self.assertIn("Laporan Robinhood Pool Screener", text)
        self.assertEqual(text.count("Alerts:"), 1)
        self.assertEqual(text.count("Alert:"), 1)

    def test_both_mode_respects_single_language_argument(self):
        config.ALERT_LANG = "both"
        text = report.build(hours=1, lang="id")
        self.assertIn("Laporan", text)
        self.assertNotIn("<b>EN</b>", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
