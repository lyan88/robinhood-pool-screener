#!/usr/bin/env python3
"""Uji adaptor sumber data tanpa jaringan (parsing, holder math, LP)."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import filters  # noqa: E402
import sources  # noqa: E402

NOW = datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc)
MINT = "0xd5d09671ba79e2aa01f7feddbff03ce20a3d0a39"
POOL = "0x17db0f2014ec7bd0fa77d909ba3f68cef9a297246da04c026fece478a83d63d1"
MGR = config.UNISWAP_V4_POOL_MANAGER


def topic(address):
    return "0x" + "0" * 24 + address[2:].lower()


def transfer(src, dst, value):
    return {
        "topics": [
            sources.TRANSFER_TOPIC,
            topic(src),
            topic(dst),
        ],
        "data": hex(value),
    }


def trade(kind="buy", age=10, price=0.002, anomalous=False):
    """Trade sudah dinormalisasi seperti keluaran _trade_from_gecko."""
    if kind == "buy":
        from_token, to_token = "0x0000000000000000000000000000000000000000", MINT
        price_from, price_to = 2350.0, price
    else:
        from_token, to_token = MINT, "0x0000000000000000000000000000000000000000"
        price_from, price_to = price, 2350.0
    return {
        "ts": NOW - timedelta(seconds=age),
        "kind": kind,
        "wallet": "0xwallet-%s-%s" % (kind, age),
        "from_token": from_token,
        "to_token": to_token,
        "price_from_usd": price_from,
        "price_to_usd": price_to,
        "anomalous": anomalous,
    }


class PoolParsingTests(unittest.TestCase):
    def test_gecko_item_is_normalized(self):
        item = {
            "id": "robinhood_" + POOL,
            "attributes": {
                "address": POOL.upper().replace("0X", "0x"),
                "name": "DEBTCOIN / WETH 1%",
                "pool_created_at": "2026-10-28T01:52:21Z",
                "fdv_usd": "4095.174915",
                "market_cap_usd": None,
                "reserve_in_usd": "3039.2",
                "base_token_price_usd": "0.00000405",
                "transactions": {"m5": {"buys": 2, "sells": 1, "buyers": 2}},
            },
            "relationships": {
                "base_token": {"data": {"id": "robinhood_" + MINT.upper()}},
                "quote_token": {"data": {"id": "robinhood_0x0000000000000000000000000000000000000000"}},
                "dex": {"data": {"id": "uniswap-v4-robinhood"}},
            },
        }
        pool = sources._pool_from_gecko(item)
        self.assertEqual(pool["mint"], MINT)
        self.assertEqual(pool["pool"], POOL)
        self.assertEqual(pool["symbol"], "DEBTCOIN")
        self.assertEqual(pool["dex"], "uniswap-v4-robinhood")
        self.assertEqual(pool["buyers5"], 2)
        self.assertEqual(pool["liq_usd"], 3039.2)
        # market_cap kosong -> pakai FDV supaya kandidat tidak dibuang.
        self.assertEqual(pool["mc_usd"], 4095.174915)
        self.assertIsNotNone(pool["age_sec"])


class TradeParsingTests(unittest.TestCase):
    def test_trade_keeps_price_fields(self):
        item = {
            "attributes": {
                "block_timestamp": "2026-10-28T01:57:46Z",
                "kind": "buy",
                "tx_from_address": "0xabc",
                "from_token_address": "0x0000000000000000000000000000000000000000",
                "to_token_address": MINT,
                "price_from_in_usd": "2350.86",
                "price_to_in_usd": "0.021058",
                "volume_in_usd": "287.5",
                "is_anomalous": False,
            }
        }
        parsed = sources._trade_from_gecko(item)
        self.assertEqual(parsed["kind"], "buy")
        self.assertEqual(parsed["wallet"], "0xabc")
        self.assertAlmostEqual(parsed["price_to_usd"], 0.021058)
        self.assertFalse(parsed["anomalous"])

    def test_price_is_found_regardless_of_address_case(self):
        upper = MINT.upper().replace("0X", "0x")
        self.assertAlmostEqual(sources.trade_price(trade(), upper), 0.002)
        self.assertAlmostEqual(sources.trade_price(trade("sell"), upper), 0.002)

    def test_anomalous_trade_is_ignored(self):
        self.assertIsNone(sources.trade_price(trade(anomalous=True), MINT))

    def test_latest_fresh_trade_wins(self):
        trades = [trade(age=200, price=0.001), trade(age=5, price=0.003)]
        self.assertAlmostEqual(
            sources.latest_trade_price(trades, MINT, now=NOW), 0.003
        )

    def test_stale_trade_returns_none(self):
        self.assertIsNone(
            sources.latest_trade_price([trade(age=600)], MINT, now=NOW)
        )


class HolderMathTests(unittest.TestCase):
    def _logs(self):
        zero = "0x0000000000000000000000000000000000000000"
        a = "0x00000000000000000000000000000000000000a1"
        b = "0x00000000000000000000000000000000000000b2"
        c = "0x00000000000000000000000000000000000000c3"
        dead = "0x000000000000000000000000000000000000dead"
        return [
            transfer(zero, a, 1_000_000),
            transfer(a, MGR, 700_000),
            transfer(a, b, 100_000),
            transfer(a, c, 50_000),
            transfer(a, dead, 10_000),
        ]

    def test_pool_manager_and_burn_are_excluded(self):
        result = sources.holders_from_logs(self._logs(), 1_000_000)
        self.assertEqual(result["holders"], 3)
        # A=140k, B=100k, C=50k -> 29%
        self.assertAlmostEqual(result["top10_pct"], 29.0)

    def test_extras_can_be_excluded(self):
        pair = "0x00000000000000000000000000000000000000b2"
        result = sources.holders_from_logs(
            self._logs(), 1_000_000, excludes={pair}
        )
        self.assertEqual(result["holders"], 2)
        self.assertAlmostEqual(result["top10_pct"], 19.0)

    def test_zero_supply_is_unusable(self):
        self.assertIsNone(sources.holders_from_logs(self._logs(), 0))
        self.assertIsNone(sources.holders_from_logs(self._logs(), None))


class LpParsingTests(unittest.TestCase):
    def test_goplus_fraction_is_converted_to_percent(self):
        report = {
            "dex": [{"pair": POOL, "liquidity": "50000"}],
            "lp_holders": [
                {"address": "0xlocker", "percent": "0.995", "is_locked": 1},
                {"address": "0xdev", "percent": "0.005", "is_locked": 0},
            ],
        }
        status, pct, _detail = filters.lp_state(report, pool_address=POOL)
        self.assertEqual(status, "locked")
        self.assertAlmostEqual(pct, 99.5)

    def test_burn_address_is_burned(self):
        report = {
            "dex": [{"pair": POOL, "liquidity": "50000"}],
            "lp_holders": [
                {"address": "0x000000000000000000000000000000000000dead",
                 "percent": "1.0", "is_locked": 0},
            ],
        }
        status, pct, _detail = filters.lp_state(report, pool_address=POOL)
        self.assertEqual(status, "burned")
        self.assertAlmostEqual(pct, 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
