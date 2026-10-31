#!/usr/bin/env python3
"""
Kirim notifikasi agent ke Telegram.

Dipakai oleh deploy/agent-daily.sh. Pesan dibaca dari stdin supaya tidak ada
masalah quoting. Dijalankan dari direktori produksi agar `.env` terbaca.

    echo "halo" | python3 deploy/agent_notify.py
"""

import sys

import telegram


def main():
    text = sys.stdin.read().strip()
    if not text:
        print("pesan kosong", file=sys.stderr)
        return 1
    ok, reason = telegram.send(text, bypass_limits=True)
    print("notifikasi: %s %s" % (ok, reason))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
