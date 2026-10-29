#!/usr/bin/env python3
"""Uji orkestrasi scanner dengan API palsu: antrean, watchlist, isolasi error."""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import scanner  # noqa: E402

NOW = datetime.now(timezone.utc)
POOL = "0x17db0f2014ec7bd0fa77d909ba3f68cef9a297246da04c026fece478a83d63d1"
MINT = "0xd5d09671ba79e2aa01f7feddbff03ce20a3d0a39"


def make_pool(mint=MINT, pool=POOL, age=300):
    return {
        "pool": pool,
        "mint": mint,
        "name": "Scan / WETH",
        "symbol": "SCAN",
        "dex": "uniswap-v4-robinhood",
        "age_sec": age,
        "liq_usd": 20_000,
        "mc_usd": 50_000,
        "buyers5": 30,
        "price_usd": 0.001,
        "created_at": NOW - timedelta(seconds=age),
    }


def make_report(honeypot="0", lp_percent="1.0"):
    return {
        "is_honeypot": honeypot,
        "cannot_buy": "0",
        "cannot_sell_all": "0",
        "is_open_source": "1",
        "is_mintable": "0",
        "hidden_owner": "0",
        "can_take_back_ownership": "0",
        "transfer_pausable": "0",
        "trading_cooldown": "0",
        "is_blacklisted": "0",
        "is_whitelisted": "0",
        "selfdestruct": "0",
        "slippage_modifiable": "0",
        "honeypot_with_same_creator": "0",
        "is_in_dex": "1",
        "owner_balance": "0",
        "creator_balance": "0",
        "total_supply": "1000000000",
        "buy_tax": "0",
        "sell_tax": "0",
        "dex": [{"pair": POOL, "liquidity": "50000",
                 "pool_manager": config.UNISWAP_V4_POOL_MANAGER}],
        "lp_holders": [
            {"address": "0x000000000000000000000000000000000000dead",
             "percent": lp_percent, "is_locked": 1},
        ],
    }


def make_holders(top10_pct=20.0, holders=20):
    return {
        "holders": holders,
        "top10_pct": top10_pct,
        "top": [{"address": "0xabc", "pct": top10_pct}],
        "supply": 1_000_000_000,
        "logs": 50,
        "complete": True,
    }


def make_trades(count=30):
    return [
        {
            "ts": NOW - timedelta(seconds=10 + i),
            "kind": "buy",
            "wallet": "0xwallet%d" % i,
            "from_token": "0x0000000000000000000000000000000000000000",
            "to_token": MINT,
            "price_from_usd": 2350.0,
            "price_to_usd": 0.001,
            "volume_usd": 10.0,
            "anomalous": False,
        }
        for i in range(count)
    ]


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self._old = (config.DB_PATH, config.DATA_DIR, config.TELEGRAM_ENABLED)
        config.DB_PATH = base / "test.db"
        config.DATA_DIR = base
        config.TELEGRAM_ENABLED = True
        self.conn = db.connect()
        db.init(self.conn)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH, config.DATA_DIR, config.TELEGRAM_ENABLED = self._old

    def _run(self, report=None, holders=None, trades=None, pools=None,
             trades_error=False):
        trades_patch = (
            mock.patch.object(
                scanner.sources, "fetch_trades",
                side_effect=scanner.sources.net.SourceError("429"),
            )
            if trades_error
            else mock.patch.object(
                scanner.sources, "fetch_trades",
                return_value=trades if trades is not None else make_trades(),
            )
        )
        with mock.patch.object(
            scanner.sources, "fetch_new_pools",
            return_value=(pools if pools is not None else [make_pool()], []),
        ), mock.patch.object(
            scanner.sources, "fetch_goplus", return_value=report or make_report(),
        ), mock.patch.object(
            scanner.sources, "fetch_holders",
            return_value=holders if holders is not None else make_holders(),
        ), mock.patch.object(
            scanner.sources, "fetch_lp_burned", return_value=None,
        ), trades_patch, mock.patch.object(
            scanner.telegram, "send", return_value=(True, "terkirim"),
        ):
            return scanner.scan_once(dry_run=False)

    def test_passing_pool_is_alerted_once(self):
        self.assertEqual(self._run(), 0)
        alerts = self.conn.execute("SELECT * FROM alerts").fetchall()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["mint"], MINT)
        self.assertAlmostEqual(alerts[0]["price_usd"], 0.001)
        self.assertEqual(alerts[0]["lp_status"], "burned")

    def test_second_run_does_not_alert_again(self):
        self._run()
        self._run()
        alerts = self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        self.assertEqual(alerts, 1)

    def test_honeypot_is_rejected_and_not_alerted(self):
        self._run(report=make_report(honeypot="1"))
        alerts = self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        self.assertEqual(alerts, 0)
        row = self.conn.execute("SELECT * FROM evaluations").fetchone()
        self.assertEqual(row["passed"], 0)
        self.assertIn("security", row["reasons"])

    def test_near_miss_goes_to_watchlist(self):
        self._run(holders=make_holders(top10_pct=config.TOP10_MAX_PCT + 5))
        watched = self.conn.execute("SELECT * FROM watchlist").fetchall()
        self.assertEqual(len(watched), 1)
        self.assertEqual(watched[0]["status"], "watching")

    def test_unrecoverable_rejection_is_not_watched(self):
        self._run(trades_error=True)  # trades_unavailable masih recoverable
        watched = self.conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        self.assertEqual(watched, 1)

        self.conn.execute("DELETE FROM watchlist")
        self.conn.execute("DELETE FROM evaluations")
        self.conn.commit()
        self._run(report=make_report(honeypot="1"))
        watched = self.conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        self.assertEqual(watched, 0)

    def test_age_is_recomputed_from_created_at(self):
        pool = make_pool()
        pool["age_sec"] = 1  # snapshot bohong; created_at yang benar
        self._run(pools=[pool])
        row = self.conn.execute("SELECT age_sec FROM evaluations").fetchone()
        self.assertGreaterEqual(row["age_sec"], 290)


if __name__ == "__main__":
    unittest.main(verbosity=2)
