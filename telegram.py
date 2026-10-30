#!/usr/bin/env python3
"""Kirim alert ke Telegram, dengan batas laju dan state harian."""

import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config
import db
import filters
import i18n

STATE_PATH = config.DATA_DIR / "telegram_state.json"


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sent": []}


def _save_state(state):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def _rate_ok(state):
    now = time.time()
    sent = [float(x) for x in state.get("sent", []) if now - float(x) < 86400]
    state["sent"] = sent
    hour = [x for x in sent if now - x < 3600]
    if len(hour) >= config.TELEGRAM_MAX_PER_HOUR:
        return False, "batas %d pesan/jam tercapai" % config.TELEGRAM_MAX_PER_HOUR
    if len(sent) >= config.TELEGRAM_MAX_PER_DAY:
        return False, "batas %d pesan/hari tercapai" % config.TELEGRAM_MAX_PER_DAY
    if sent and now - sent[-1] < config.TELEGRAM_MIN_INTERVAL_SEC:
        return False, "jeda minimum %.0fs" % config.TELEGRAM_MIN_INTERVAL_SEC
    return True, ""


def send(text, dry_run=None, disable_preview=True, bypass_limits=False):
    dry_run = config.DRY_RUN if dry_run is None else dry_run
    if not config.TELEGRAM_ENABLED:
        return False, "Telegram dimatikan"
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi"
    if dry_run:
        return False, "dry-run"

    state = _load_state()
    if not bypass_limits:
        ok, reason = _rate_ok(state)
        if not ok:
            return False, reason

    url = "https://api.telegram.org/bot%s/sendMessage" % config.TELEGRAM_BOT_TOKEN
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_preview else "false",
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, str(exc)
    if not body.get("ok"):
        return False, str(body.get("description") or body)[:200]

    state = _load_state()
    state.setdefault("sent", []).append(time.time())
    state["sent"] = state["sent"][-500:]
    _save_state(state)
    return True, "terkirim"


def _delayed_message(message, delay_sec, lang=None):
    if delay_sec < 30:
        return message
    if delay_sec < 60:
        delay_text = "%ds" % int(delay_sec)
    else:
        delay_text = "%dm" % max(1, int(delay_sec // 60))
    return (i18n.text(lang, "delay_banner") % delay_text) + "\n" + message


def drain_queue(conn, dry_run=None, max_send=None):
    """
    Kirim antrean alert, skor tertinggi dulu.

    Berhenti saat kuota/jeda tercapai supaya sisa antrean dicoba lagi pada
    putaran berikutnya. Alert yang tertunda lama tidak memakai harga lama
    sebagai entry (biar outcome tidak menyesatkan).
    """
    dry_run = config.DRY_RUN if dry_run is None else dry_run
    max_send = config.ALERT_DRAIN_MAX if max_send is None else int(max_send)
    db.expire_queue(conn)
    rows = db.pending_queue(conn, limit=max_send)

    sent = failed = 0
    for row in rows:
        if sent >= max_send:
            break
        delay = max(0, int(time.time()) - int(row["created_at"]))
        text = _render(_decode_payload(row["message"]), delay)
        if dry_run:
            print(text)
            print()
            continue

        ok, reason = send(text)
        if not ok and reason.startswith("jeda minimum"):
            time.sleep(max(0.5, config.TELEGRAM_MIN_INTERVAL_SEC))
            ok, reason = send(text)

        if ok:
            sent_at = int(time.time())
            price = row["price_usd"]
            if delay > config.ALERT_QUEUE_MAX_PRICE_AGE_SEC:
                price = None
            recorded = db.record_alert(
                conn,
                {
                    "mint": row["mint"], "pool": row["pool"], "name": row["name"],
                    "symbol": row["symbol"], "created_at": sent_at,
                    "age_sec": row["age_sec"], "liq_usd": row["liq_usd"],
                    "mc_usd": row["mc_usd"], "buyers2": row["buyers2"],
                    "top10_pct": row["top10_pct"], "lp_status": row["lp_status"],
                    "price_usd": price, "message": row["message"],
                },
            )
            db.mark_queue_sent(conn, row["mint"])
            if recorded:
                db.mark_evaluation_alerted(conn, row["mint"], sent_at)
                sent += 1
            continue

        if "batas" in reason:
            # Kuota penuh: jangan buang, coba lagi setelah kuota pulih.
            db.mark_queue_blocked(conn, row["mint"], reason)
            break

        final = (row["attempts"] + 1) >= config.ALERT_QUEUE_MAX_ATTEMPTS
        db.mark_queue_failed(conn, row["mint"], reason, final=final)
        failed += 1

    return {"sent": sent, "failed": failed}


def _e(value):
    return html.escape("" if value is None else str(value), quote=True)


def _num(value):
    if value is None:
        return "?"
    return ("%.2f" % float(value)).rstrip("0").rstrip(".")


def _contract_line(lang, details):
    honeypot = details.get("honeypot")
    mintable = details.get("mintable")
    owner = details.get("owner_pct")

    if honeypot is True:
        head = "honeypot ⚠️"
    elif honeypot is False:
        head = "honeypot %s ✅" % i18n.text(lang, "safe")
    else:
        head = "honeypot %s ❔" % i18n.text(lang, "unknown")

    if mintable is True:
        head += " · %s ⚠️" % i18n.text(lang, "mintable")
    elif mintable is False:
        head += " · %s" % i18n.text(lang, "not_mintable")

    if owner is not None:
        head += " · " + i18n.text(lang, "owner") % ("%.1f%%" % float(owner))
    return i18n.text(lang, "contract") % _e(head)


def format_alert(pool, sec, buyers, now=None, lang=None):
    lang = i18n.normalize(lang or config.ALERT_LANG)
    now = now or datetime.now(timezone.utc)
    age = pool.get("age_sec") or 0
    age_text = "%dm%02ds" % (age // 60, age % 60)
    details = sec.get("details") or {}
    lp_status = details.get("lp_status") or "unknown"
    lp_pct = details.get("lp_pct")
    lp_label = i18n.status_label(lang, lp_status)
    if lp_pct is not None:
        lp_text = "%s %.1f%%" % (lp_label, float(lp_pct))
    else:
        lp_text = lp_label

    mc = pool.get("mc_usd")
    liq = pool.get("liq_usd")
    buyers2 = buyers or {}
    top10 = sec.get("top10_pct")

    buyers_line = i18n.text(lang, "buyers") % {
        "window": buyers2.get("window_sec", config.BUYER_WINDOW_SEC),
        "buyers": buyers2.get("buyers", 0),
        "buys": buyers2.get("buys", 0),
        "sells": buyers2.get("sells", 0),
    }

    lines = [
        "<b>$%s</b>" % _e(pool.get("symbol") or "?"),
        i18n.text(lang, "line_meta") % (
            _e(pool.get("name") or "?"),
            _e(pool.get("dex") or "?"),
            age_text,
        ),
        "",
        i18n.text(lang, "mc_liq") % (filters.fmt_usd(mc), filters.fmt_usd(liq)),
        buyers_line,
        i18n.text(lang, "top10") % (
            "%.1f%%" % top10 if top10 is not None else "?"
        ),
        _contract_line(lang, details),
        i18n.text(lang, "tax") % (
            _num(details.get("buy_tax")), _num(details.get("sell_tax"))
        ),
        i18n.text(lang, "lp") % _e(lp_text),
        "",
        i18n.text(lang, "price") % _e(filters.fmt_price(pool.get("price_usd"))),
        "CA: <code>%s</code>" % _e(pool.get("mint")),
        "Pool: <code>%s</code>" % _e(pool.get("pool")),
        "",
        '<a href="https://dexscreener.com/%s/%s">DexScreener</a> · '
        '<a href="%s/token/%s">Explorer</a> · '
        '<a href="%s/%s">GMGN</a>' % (
            urllib.parse.quote(config.DEXSCREENER_NETWORK),
            urllib.parse.quote(pool.get("pool") or ""),
            config.EXPLORER_URL.rstrip("/"),
            urllib.parse.quote(pool.get("mint") or ""),
            config.GMGN_BASE.rstrip("/"),
            urllib.parse.quote(pool.get("mint") or ""),
        ),
    ]
    return "\n".join(lines)


DIVIDER = "──────────"


def _human_delay(delay_sec):
    if delay_sec < 60:
        return "%ds" % int(delay_sec)
    return "%dm" % max(1, int(delay_sec // 60))


def _render(payload, delay_sec=0, mode=None):
    """
    Ubah isi antrean menjadi satu pesan siap kirim.

    ``payload`` bisa berupa teks biasa (alert satu bahasa / baris lama di
    antrean) atau dict {"en": ..., "id": ...} untuk mode both. Setiap blok
    mendapat banner keterlambatan dalam bahasanya sendiri.
    """
    if isinstance(payload, dict):
        blocks = []
        for lang in i18n.SUPPORTED:
            body = payload.get(lang)
            if not body:
                continue
            blocks.append(
                "<b>%s</b>\n%s"
                % (lang.upper(), _delayed_message(body, delay_sec, lang=lang))
            )
        return ("\n\n" + DIVIDER + "\n\n").join(blocks)

    lang = i18n.normalize_mode(mode or config.ALERT_LANG)
    if lang == "both":
        lang = i18n.DEFAULT_LANG
    return _delayed_message(payload, delay_sec, lang=lang)


def format_alert_auto(pool, sec, buyers, now=None, mode=None):
    """
    Format sesuai ALERT_LANG. Mode both mengembalikan JSON berisi dua versi
    supaya antrean tetap satu baris dan hanya satu pesan yang dikirim.
    """
    mode = i18n.normalize_mode(mode or config.ALERT_LANG)
    langs = i18n.langs(mode)
    if len(langs) == 1:
        return format_alert(pool, sec, buyers, now=now, lang=langs[0])
    payload = {
        lang: format_alert(pool, sec, buyers, now=now, lang=lang) for lang in langs
    }
    return json.dumps(payload, ensure_ascii=False)


def _decode_payload(message):
    """Baris antrean lama berisi teks biasa; mode both berisi JSON."""
    if not isinstance(message, str) or not message.startswith("{"):
        return message
    try:
        data = json.loads(message)
    except ValueError:
        return message
    if isinstance(data, dict) and data and all(
        isinstance(value, str) for value in data.values()
    ):
        return data
    return message


def preview(payload, delay_sec=0):
    """Teks yang akan benar-benar dikirim, untuk dry-run dan log."""
    return _render(_decode_payload(payload), delay_sec)


def _test_block(lang):
    return i18n.text(lang, "test_ready") + "\n" + i18n.text(lang, "test_filter") % (
        config.CHAIN_ID,
        config.MAX_OWNER_PCT,
        config.MAX_TAX_PCT,
        config.TOP10_MAX_PCT,
        filters.fmt_usd(config.MIN_MC_USD), filters.fmt_usd(config.MAX_MC_USD),
        filters.fmt_usd(config.MIN_LIQ_USD),
        config.MAX_AGE_SEC // 60, config.MIN_UNIQUE_BUYERS,
        config.BUYER_WINDOW_SEC,
    )


def send_test(lang=None):
    mode = i18n.normalize_mode(lang or config.ALERT_LANG)
    langs = i18n.langs(mode)
    if len(langs) == 1:
        return send(_test_block(langs[0]))
    blocks = ["<b>%s</b>\n%s" % (l.upper(), _test_block(l)) for l in langs]
    return send(("\n\n" + DIVIDER + "\n\n").join(blocks))
