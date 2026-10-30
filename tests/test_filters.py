#!/usr/bin/env python3
"""Uji filter EVM tanpa jaringan: python3 -m unittest discover -s tests -v"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import filters  # noqa: E402

POOL = "0x17db0f2014ec7bd0fa77d909ba3f68cef9a297246da04c026fece478a83d63d1"
MINT = "0xd5d09671ba79e2aa01f7feddbff03ce20a3d0a39"
MGR = config.UNISWAP_V4_POOL_MANAGER
NOW = datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc)


def make_report(**over):
    report = {
        "is_honeypot": "0",
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
        "owner_percent": "0",
        "creator_percent": "0",
        "buy_tax": "0",
        "sell_tax": "0",
        "lp_holders": [
            {"address": "0x000000000000000000000000000000000000dead",
             "percent": "1.0", "is_locked": 1},
        ],
        "dex": [{"pair": POOL, "pool_manager": MGR, "liquidity": "50000"}],
    }
    report.update(over)
    return report


def make_holders(holders=20, top10_pct=22.0):
    return {
        "holders": holders,
        "top10_pct": top10_pct,
        "top": [{"address": "0xabc", "pct": top10_pct}],
        "supply": 1_000_000_000,
        "logs": 100,
        "complete": True,
    }


def make_pool(age=300, liq=20000, mc=50000, buyers5=30):
    return {
        "pool": POOL, "mint": MINT, "name": "Test / WETH", "symbol": "TEST",
        "dex": "uniswap-v4-robinhood", "age_sec": age, "liq_usd": liq,
        "mc_usd": mc, "buyers5": buyers5,
        "created_at": NOW - timedelta(seconds=age),
    }


def make_trades(count=15, kind="buy", age=60):
    return [
        {
            "ts": NOW - timedelta(seconds=age + i),
            "kind": kind,
            "wallet": "0xwallet%d" % i,
            "volume_usd": 10.0,
            "anomalous": False,
        }
        for i in range(count)
    ]


class CheapFilterTests(unittest.TestCase):
    def test_fresh_pool_passes(self):
        ok, check, _detail = filters.evaluate_cheap(make_pool())
        self.assertTrue(ok, check)

    def test_old_pool_is_rejected(self):
        ok, _check, detail = filters.evaluate_cheap(
            make_pool(age=config.MAX_AGE_SEC + 60)
        )
        self.assertFalse(ok)
        self.assertIn("umur", detail)

    def test_low_liquidity_is_rejected(self):
        ok, _check, detail = filters.evaluate_cheap(make_pool(liq=100))
        self.assertFalse(ok)
        self.assertIn("likuiditas", detail)

    def test_market_cap_outside_range_is_rejected(self):
        ok, _check, _detail = filters.evaluate_cheap(make_pool(mc=1))
        self.assertFalse(ok)
        ok, _check, _detail = filters.evaluate_cheap(make_pool(mc=10_000_000))
        self.assertFalse(ok)

    def test_buyers_prefilter(self):
        ok, _check, detail = filters.evaluate_cheap(make_pool(buyers5=1))
        self.assertFalse(ok)
        self.assertIn("buyer", detail)


class SecurityTests(unittest.TestCase):
    def test_clean_contract_passes(self):
        ok, detail = filters.check_security(make_report())
        self.assertTrue(ok, detail)
        self.assertIn("honeypot clear", detail)

    def test_honeypot_is_rejected(self):
        ok, detail = filters.check_security(make_report(is_honeypot="1"))
        self.assertFalse(ok)
        self.assertIn("honeypot", detail)

    def test_unknown_honeypot_is_not_trusted(self):
        report = make_report()
        report.pop("is_honeypot")
        ok, detail = filters.check_security(report)
        self.assertFalse(ok)
        self.assertIn("tidak diketahui", detail)

    def test_mintable_is_rejected(self):
        ok, detail = filters.check_security(make_report(is_mintable="1"))
        self.assertFalse(ok)
        self.assertIn("mintable", detail)

    def test_unverified_contract_is_rejected(self):
        ok, detail = filters.check_security(make_report(is_open_source="0"))
        self.assertFalse(ok)
        self.assertIn("verified", detail)

    def test_hidden_owner_and_pausable_are_rejected(self):
        ok, _detail = filters.check_security(make_report(hidden_owner="1"))
        self.assertFalse(ok)
        ok, _detail = filters.check_security(make_report(transfer_pausable="1"))
        self.assertFalse(ok)

    def test_owner_and_creator_holding_limits(self):
        report = make_report(owner_balance="200000000")
        ok, detail = filters.check_security(report)
        self.assertFalse(ok)
        self.assertIn("owner", detail)

        report = make_report(creator_balance="200000000")
        ok, detail = filters.check_security(report)
        self.assertFalse(ok)
        self.assertIn("creator", detail)

    def test_high_tax_is_rejected(self):
        ok, detail = filters.check_tax(make_report(buy_tax="12"))
        self.assertFalse(ok)
        self.assertIn("tax", detail)

    def test_mutable_tax_is_rejected(self):
        ok, detail = filters.check_tax(make_report(slippage_modifiable="1"))
        self.assertFalse(ok)
        self.assertIn("diubah", detail)

    def test_unknown_tax_is_allowed(self):
        report = make_report(buy_tax="", sell_tax="")
        ok, detail = filters.check_tax(report)
        self.assertTrue(ok, detail)
        self.assertIn("belum terindeks", detail)

    def test_missing_report_is_rejected(self):
        ok, detail = filters.check_security(None)
        self.assertFalse(ok)
        self.assertIn("tidak tersedia", detail)


class HolderTests(unittest.TestCase):
    def test_top10_with_enough_holders(self):
        pct, detail = filters.top10(make_holders())
        self.assertEqual(pct, 22.0)
        self.assertIn("20 holder", detail)

    def test_too_few_holders_is_unknown(self):
        pct, detail = filters.top10(make_holders(holders=3, top10_pct=90.0))
        self.assertIsNone(pct)
        self.assertIn("holder nyata", detail)

    def test_thin_float_is_rejected(self):
        pct, detail = filters.top10(make_holders(top10_pct=2.0))
        self.assertIsNone(pct)
        self.assertIn("float", detail)

    def test_missing_holders_is_unknown(self):
        self.assertIsNone(filters.top10(None)[0])


class LpTests(unittest.TestCase):
    def test_burned_lp_passes(self):
        status, pct, _detail = filters.lp_state(make_report(), pool_address=POOL)
        self.assertEqual(status, "burned")
        self.assertAlmostEqual(pct, 100.0)

    def test_locked_lp_passes(self):
        report = make_report(lp_holders=[
            {"address": "0xlocker", "percent": "0.995", "is_locked": 1},
        ])
        status, pct, _detail = filters.lp_state(report, pool_address=POOL)
        self.assertEqual(status, "locked")
        self.assertGreaterEqual(pct, 99.0)
        ok, _detail, status, _pct = filters.check_lp(report, pool_address=POOL)
        self.assertTrue(ok)
        self.assertEqual(status, "locked")

    def test_unlocked_lp_is_rejected(self):
        report = make_report(lp_holders=[
            {"address": "0xdev", "percent": "0.5", "is_locked": 0},
        ])
        ok, _detail, status, _pct = filters.check_lp(report, pool_address=POOL)
        self.assertFalse(ok)
        self.assertEqual(status, "unlocked")

    def test_unknown_lp_is_allowed_when_not_required(self):
        report = make_report(lp_holders=[])
        ok, detail, status, _pct = filters.check_lp(report, pool_address=POOL)
        self.assertTrue(ok)
        self.assertEqual(status, "unknown")

    def test_onchain_burned_override(self):
        status, pct, _detail = filters.lp_state(
            None, lp_burned=100.0, pool_address=POOL
        )
        self.assertEqual(status, "burned")
        self.assertEqual(pct, 100.0)

    def test_dead_pool_is_detected(self):
        report = make_report(dex=[{"pair": POOL, "liquidity": "10"}])
        ok, _detail, status, _pct = filters.check_lp(report, pool_address=POOL)
        self.assertFalse(ok)
        self.assertEqual(status, "dead")


class BuyersTests(unittest.TestCase):
    def test_enough_unique_buyers(self):
        count = config.MIN_UNIQUE_BUYERS
        ok, detail, stats = filters.check_buyers_window(
            make_trades(count), NOW, created_at=NOW - timedelta(seconds=300)
        )
        self.assertTrue(ok, detail)
        self.assertEqual(stats["buyers"], count)

    def test_sells_do_not_count_as_buyers(self):
        trades = make_trades(5) + make_trades(5, kind="sell")
        ok, _detail, stats = filters.check_buyers_window(trades, NOW)
        self.assertFalse(ok)
        self.assertEqual(stats["buyers"], 5)
        self.assertEqual(stats["sells"], 5)

    def test_old_trades_are_ignored(self):
        ok, _detail, _stats = filters.check_buyers_window(
            make_trades(30, age=600), NOW
        )
        self.assertFalse(ok)


class EvaluateTests(unittest.TestCase):
    def test_all_filters_pass(self):
        sec = filters.evaluate_security(
            make_pool(), make_report(), holders=make_holders()
        )
        self.assertTrue(sec["passed"], sec["reasons"])
        self.assertAlmostEqual(sec["top10_pct"], 22.0)
        self.assertEqual(sec["details"]["lp_status"], "burned")

    def test_security_reason_is_not_recoverable(self):
        sec = filters.evaluate_security(
            make_pool(), make_report(is_honeypot="1"), holders=make_holders()
        )
        self.assertFalse(sec["passed"])
        self.assertIn("security", sec["reasons"])
        self.assertFalse(filters.near_miss({"reasons": sec["reasons"]}))

    def test_top10_reason_can_be_watched(self):
        sec = filters.evaluate_security(
            make_pool(), make_report(),
            holders=make_holders(top10_pct=config.TOP10_MAX_PCT + 5),
        )
        self.assertIn("top10", sec["reasons"])
        self.assertTrue(filters.near_miss({
            "reasons": ["top10"], "top10_pct": config.TOP10_MAX_PCT + 5,
        }))

    def test_better_metrics_get_higher_score(self):
        sec = {"top10_pct": 18.0, "details": {"lp_status": "burned"}}
        good = filters.alert_score(
            {"mc_usd": 50_000, "liq_usd": 25_000, "age_sec": 60},
            sec, {"buyers": 120},
        )
        weak = filters.alert_score(
            {"mc_usd": 50_000, "liq_usd": 8_000, "age_sec": 500},
            {"top10_pct": 34.0, "details": {"lp_status": "unknown"}},
            {"buyers": 16},
        )
        self.assertGreater(good, weak)


class FormatTests(unittest.TestCase):
    def test_price_has_no_scientific_notation(self):
        self.assertEqual(filters.fmt_price(9.094216389484412e-06), "0.0000090942164")

    def test_usd_compact(self):
        self.assertEqual(filters.fmt_usd(74_470), "74.5k")
        self.assertEqual(filters.fmt_usd(1_240_000), "1.24M")


if __name__ == "__main__":
    unittest.main(verbosity=2)
