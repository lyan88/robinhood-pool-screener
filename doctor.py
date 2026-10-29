#!/usr/bin/env python3
"""
Pemeriksaan cepat sebelum mengaktifkan cron.

    python3 doctor.py
    python3 doctor.py --telegram   # kirim satu pesan uji

Keluar dengan kode 1 kalau ada pemeriksaan yang gagal.
"""

import argparse
import sys
import time

import config
import db
import filters
import sources
import telegram

PASS = FAIL = WARN = 0


def ok(name, detail=""):
    global PASS
    PASS += 1
    print("  ok    %-34s %s" % (name, detail))


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    print("  GAGAL %-34s %s" % (name, detail))


def warn(name, detail=""):
    global WARN
    WARN += 1
    print("  hati2 %-34s %s" % (name, detail))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true", help="kirim pesan uji")
    args = parser.parse_args()

    print("=" * 62)
    print(" DOCTOR — Robinhood Pool Screener")
    print("=" * 62)
    print(" waktu UTC : %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    print(" chain     : %s (id %d)" % (config.CHAIN_NAME, config.CHAIN_ID))
    print(" filter    : %s" % config.summary())

    print("\n[berkas]")
    config.ensure_dirs()
    probe = config.DATA_DIR / ".write_test"
    try:
        probe.write_text("x")
        probe.unlink()
        ok("data dir bisa ditulis", str(config.DATA_DIR))
    except OSError as exc:
        bad("data dir", str(exc))

    print("\n[database]")
    conn = None
    try:
        conn = db.connect()
        db.init(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ok("integritas", integrity)
        stats = db.stats(conn)
        ok("isi", "%d evaluasi, %d alert (%d/24 jam)" % (
            stats["evaluations"], stats["alerts"], stats["alerts_24h"]))
    except Exception as exc:  # noqa: BLE001 - doctor harus menangkap semua
        bad("database", str(exc))

    print("\n[telegram]")
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        ok("kredensial", "token & chat id terisi")
    else:
        bad("kredensial", "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong")
    if args.telegram:
        sent, reason = telegram.send_test()
        (ok if sent else bad)("pesan uji", reason)

    print("\n[jaringan]")
    first = None
    try:
        pools, errors = sources.fetch_new_pools(pages=1)
        ok("geckoterminal", "%d pool baru, %d error" % (len(pools), len(errors)))
        first = pools[0] if pools else None
    except Exception as exc:  # noqa: BLE001
        bad("geckoterminal", str(exc))

    try:
        latest = sources.block_number()
        ok("rpc robinhood", "block %d" % latest)
    except Exception as exc:  # noqa: BLE001
        bad("rpc robinhood", str(exc))

    if first:
        try:
            report = sources.fetch_goplus(first["mint"])
        except Exception as exc:  # noqa: BLE001
            report = None
            warn("goplus", str(exc))
        if not report:
            warn("goplus", "token pertama belum terindeks (normal untuk pool baru)")
        else:
            state = filters.security_state(report)
            ok(
                "goplus",
                "honeypot=%s mintable=%s verified=%s tax=%s/%s"
                % (
                    state["honeypot"], state["mintable"], state["verified"],
                    state["buy_tax"], state["sell_tax"],
                ),
            )

        try:
            holders = sources.fetch_holders(first["mint"])
        except Exception as exc:  # noqa: BLE001
            holders = None
            warn("holder on-chain", str(exc))
        if holders is None:
            warn("holder on-chain", "log Transfer belum lengkap / pool terlalu baru")
        else:
            pct, detail = filters.top10(holders)
            ok(
                "holder on-chain",
                "%d holder, top10=%s (%s)"
                % (
                    holders.get("holders", 0),
                    "%.1f%%" % pct if pct is not None else "?",
                    detail,
                ),
            )

        try:
            lp_burned = sources.fetch_lp_burned(first["pool"])
            status, lp_pct, detail = filters.lp_state(
                report, lp_burned=lp_burned, pool_address=first["pool"]
            )
            ok(
                "status LP",
                "%s %s (%s)"
                % (
                    status,
                    "%.1f%%" % lp_pct if lp_pct is not None else "",
                    detail,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            warn("status LP", str(exc))

    print("\n" + "=" * 62)
    print(" %d ok, %d peringatan, %d gagal" % (PASS, WARN, FAIL))
    print("=" * 62)
    if conn:
        conn.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
