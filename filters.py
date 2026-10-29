#!/usr/bin/env python3
"""
Filter murni: tidak menyentuh jaringan, supaya bisa diuji tanpa API.

Urutan evaluasi sengaja dari yang paling murah:
  umur -> likuiditas -> market cap -> buyers m5
  -> keamanan kontrak (GoPlus) -> top holder (RPC) -> LP
  -> unique buyer 2 menit (butuh trades)

Perbedaan dengan versi Solana: mint/freeze authority tidak ada di EVM.
Penggantinya adalah honeypot, mintable, owner/creator holding, tax, dan
fungsi berbahaya lain yang dilaporkan GoPlus.
"""

import math

import config

# DEX yang memakai bonding curve: tidak ada token LP yang bisa ditarik dev.
BONDING_DEXES = {"pons-v2", "pons"}
# Pons adalah launchpad Robinhood Chain; pool bonding curve tidak punya LP
# fungible, jadi status "burned" adalah label yang jujur.
LP_TOKEN_DEAD = "burned"


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value):
    """GoPlus memakai string "0"/"1"; None berarti belum diketahui."""
    if value is None or value == "":
        return None
    return str(value).strip() == "1"


def _frac_pct(value):
    """GoPlus mengirim persentase sebagai fraksi (0.25 = 25%)."""
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return None


def check_age(pool):
    age = pool.get("age_sec")
    if age is None:
        return False, "umur tidak diketahui"
    if age < config.MIN_AGE_SEC:
        return False, "terlalu baru (%ds)" % age
    if age >= config.MAX_AGE_SEC:
        return False, "umur %dm >= %dm" % (age / 60.0, config.MAX_AGE_SEC / 60.0)
    return True, "umur %dm%02ds" % (age // 60, age % 60)


def check_liquidity(pool):
    liq = _f(pool.get("liq_usd"))
    if liq < config.MIN_LIQ_USD:
        return False, "likuiditas $%s < $%s" % (fmt_usd(liq), fmt_usd(config.MIN_LIQ_USD))
    return True, "likuiditas $%s" % fmt_usd(liq)


def check_market_cap(pool):
    mc = pool.get("mc_usd")
    if mc is None or mc <= 0:
        return False, "market cap tidak tersedia"
    if mc < config.MIN_MC_USD:
        return False, "MC $%s < $%s" % (fmt_usd(mc), fmt_usd(config.MIN_MC_USD))
    if mc > config.MAX_MC_USD:
        return False, "MC $%s > $%s" % (fmt_usd(mc), fmt_usd(config.MAX_MC_USD))
    return True, "MC $%s" % fmt_usd(mc)


def check_buyers5(pool):
    """Prefilter murah: unique buyer 5 menit tidak mungkin lebih kecil dari 2 menit."""
    buyers = pool.get("buyers5") or 0
    if buyers < config.MIN_UNIQUE_BUYERS:
        return False, "buyer 5m %d < %d" % (buyers, config.MIN_UNIQUE_BUYERS)
    return True, "buyer 5m %d" % buyers


def security_state(report):
    """Ringkasan field keamanan GoPlus. None = belum diketahui."""
    if not report:
        return {
            "honeypot": None, "cannot_buy": None, "cannot_sell_all": None,
            "verified": None, "mintable": None, "hidden_owner": None,
            "take_back_ownership": None, "pausable": None, "cooldown": None,
            "blacklist": None, "whitelist": None, "selfdestruct": None,
            "mutable_tax": None, "owner_pct": None, "creator_pct": None,
            "buy_tax": None, "sell_tax": None, "in_dex": None,
            "honeypot_same_creator": None,
        }
    supply = _f(report.get("total_supply"), 0.0)

    def holding_pct(balance, field):
        if supply > 0 and report.get(balance) not in (None, ""):
            return _f(report.get(balance)) * 100.0 / supply
        return _frac_pct(report.get(field))

    return {
        "honeypot": _flag(report.get("is_honeypot")),
        "cannot_buy": _flag(report.get("cannot_buy")),
        "cannot_sell_all": _flag(report.get("cannot_sell_all")),
        "verified": _flag(report.get("is_open_source")),
        "mintable": _flag(report.get("is_mintable")),
        "hidden_owner": _flag(report.get("hidden_owner")),
        "take_back_ownership": _flag(report.get("can_take_back_ownership")),
        "pausable": _flag(report.get("transfer_pausable")),
        "cooldown": _flag(report.get("trading_cooldown")),
        "blacklist": _flag(report.get("is_blacklisted")),
        "whitelist": _flag(report.get("is_whitelisted")),
        "selfdestruct": _flag(report.get("selfdestruct")),
        "mutable_tax": _flag(report.get("slippage_modifiable")),
        "honeypot_same_creator": _flag(report.get("honeypot_with_same_creator")),
        "owner_pct": holding_pct("owner_balance", "owner_percent"),
        "creator_pct": holding_pct("creator_balance", "creator_percent"),
        "buy_tax": _f(report.get("buy_tax"), None),
        "sell_tax": _f(report.get("sell_tax"), None),
        "in_dex": _flag(report.get("is_in_dex")),
    }


def check_security(report):
    """Cek honeypot/kontrak/owner. Kembalikan (ok, detail)."""
    if not report:
        return False, "data keamanan tidak tersedia"
    state = security_state(report)
    risks = []

    if state["honeypot"] is True:
        risks.append("honeypot")
    elif state["honeypot"] is None and config.REJECT_HONEYPOT:
        risks.append("status honeypot tidak diketahui")
    if state["cannot_buy"] is True:
        risks.append("tidak bisa dibeli")
    if state["cannot_sell_all"] is True:
        risks.append("tidak bisa dijual semua")
    if config.REQUIRE_VERIFIED_CONTRACT and state["verified"] is False:
        risks.append("kontrak belum verified")
    if config.REJECT_MINTABLE and state["mintable"] is True:
        risks.append("mintable")
    if config.REJECT_HIDDEN_OWNER and state["hidden_owner"] is True:
        risks.append("hidden owner")
    if state["take_back_ownership"] is True:
        risks.append("ownership bisa diambil kembali")
    if config.REJECT_PAUSABLE and state["pausable"] is True:
        risks.append("transfer bisa dipause")
    if state["cooldown"] is True:
        risks.append("trading cooldown")
    if config.REJECT_BLACKLIST and state["blacklist"] is True:
        risks.append("fungsi blacklist")
    if state["whitelist"] is True:
        risks.append("fungsi whitelist")
    if state["selfdestruct"] is True:
        risks.append("selfdestruct")
    if state["honeypot_same_creator"] is True:
        risks.append("creator pernah bikin honeypot")
    if state["owner_pct"] is not None and state["owner_pct"] > config.MAX_OWNER_PCT:
        risks.append("owner %.1f%% > %.0f%%" % (state["owner_pct"], config.MAX_OWNER_PCT))
    if state["creator_pct"] is not None and state["creator_pct"] > config.MAX_CREATOR_PCT:
        risks.append("creator %.1f%% > %.0f%%" % (state["creator_pct"], config.MAX_CREATOR_PCT))

    if risks:
        return False, ", ".join(risks)
    owner = state["owner_pct"]
    detail = "honeypot clear"
    if state["mintable"] is False:
        detail += " · tidak mintable"
    if owner is not None:
        detail += " · owner %.1f%%" % owner
    return True, detail


def check_tax(report):
    """Pajak beli/jual dan apakah pajak bisa diubah sepihak."""
    if not report:
        return False, "data pajak tidak tersedia"
    state = security_state(report)
    risks = []
    if config.REJECT_MUTABLE_TAX and state["mutable_tax"] is True:
        risks.append("pajak bisa diubah")
    for label, key in (("beli", "buy_tax"), ("jual", "sell_tax")):
        value = state[key]
        if value is not None and value > config.MAX_TAX_PCT:
            risks.append("tax %s %.1f%% > %.0f%%" % (label, value, config.MAX_TAX_PCT))
    if risks:
        return False, ", ".join(risks)
    if state["buy_tax"] is None and state["sell_tax"] is None:
        return True, "tax belum terindeks"
    return True, "tax beli %s%% / jual %s%%" % (
        _fmt_num(state["buy_tax"]), _fmt_num(state["sell_tax"]),
    )


def top10(holders):
    """
    Persentase 10 holder terbesar yang dihitung dari log Transfer.

    ``holders`` adalah keluaran sources.holders_from_logs yang sudah membuang
    PoolManager Uniswap v4, alamat pool, dan alamat burn.
    """
    if not holders:
        return None, "data holder tidak tersedia"
    pct = holders.get("top10_pct")
    count = holders.get("holders") or 0
    if pct is None or count <= 0:
        return None, "data holder tidak tersedia"
    if count < config.MIN_TOP10_HOLDERS:
        return None, "hanya %d holder nyata (< %d); top10 belum berarti" % (
            count, config.MIN_TOP10_HOLDERS,
        )
    if pct < config.MIN_TOP10_TOTAL_PCT:
        return None, "top10 hanya %.2f%% supply (< %.1f%%); float terlalu tipis" % (
            pct, config.MIN_TOP10_TOTAL_PCT,
        )
    return round(pct, 4), "%d holder dihitung" % count


def pool_dead(report, pool_address):
    """Pool dianggap mati kalau GoPlus melihat likuiditasnya nyaris nol."""
    if not report or not pool_address:
        return False
    pool_address = pool_address.lower()
    for entry in report.get("dex") or []:
        if (entry.get("pair") or "").lower() != pool_address:
            continue
        liq = _f(entry.get("liquidity"), 0.0)
        return liq < config.MIN_POOL_LIQ_USD
    return False


def lp_state(report, lp_burned=None, pool_address=None):
    """
    Kembalikan (status, pct, detail).
    status: burned | locked | unlocked | unknown | dead
    """
    if report and pool_dead(report, pool_address):
        return "dead", None, "pool mati (likuiditas GoPlus nyaris nol)"

    # Cadangan on-chain untuk Uniswap v2: token LP = alamat pair.
    if lp_burned is not None:
        if lp_burned >= config.LP_MIN_LOCKED_PCT:
            return "burned", lp_burned, "LP dibakar %.2f%% (on-chain)" % lp_burned
        return "unlocked", lp_burned, "LP terbuka %.2f%% (on-chain)" % lp_burned

    if not report:
        return "unknown", None, "data LP tidak tersedia"

    holders = report.get("lp_holders")
    if not isinstance(holders, list) or not holders:
        return "unknown", None, "posisi LP belum terindeks"

    burned_pct = locked_pct = total_pct = 0.0
    for holder in holders:
        pct = _frac_pct(holder.get("percent")) or 0.0
        total_pct += pct
        address = (holder.get("address") or "").lower()
        locked = holder.get("is_locked") in (1, "1", True)
        if address in config.BURN_ADDRESSES:
            burned_pct += pct
        elif locked:
            locked_pct += pct

    if burned_pct >= config.LP_MIN_LOCKED_PCT:
        return "burned", min(100.0, burned_pct), "LP dibakar %.2f%% (GoPlus)" % burned_pct
    locked_total = min(100.0, burned_pct + locked_pct)
    if locked_total >= config.LP_MIN_LOCKED_PCT:
        return "locked", locked_total, "LP terkunci %.2f%% (GoPlus)" % locked_total
    if total_pct > 0:
        return "unlocked", min(100.0, total_pct), "LP terbuka %.2f%% (GoPlus)" % total_pct
    return "unknown", None, "persentase LP tidak tersedia"


def check_lp(report, lp_burned=None, pool_address=None):
    status, pct, detail = lp_state(report, lp_burned=lp_burned, pool_address=pool_address)
    if status == "burned":
        return True, detail, status, pct
    if status == "locked":
        if config.LP_ACCEPT_LOCKED:
            return True, detail, status, pct
        return False, "LP terkunci, bukan burned", status, pct
    if status == "unknown" and not config.LP_REQUIRE_KNOWN:
        return True, detail, status, pct
    return False, detail, status, pct


def buyer_window(trades, now, window_sec=None, created_at=None):
    """
    Hitung unique buyer dalam jendela terakhir.

    Kalau pool lebih muda dari jendela, pakai seluruh umur pool.
    """
    window_sec = config.BUYER_WINDOW_SEC if window_sec is None else window_sec
    if now is None:
        return None
    if created_at is not None:
        age = (now - created_at).total_seconds()
        if age < window_sec:
            window_sec = max(1.0, age)
    cutoff = now.timestamp() - window_sec

    buyers = set()
    buys = sells = 0
    for trade in trades or []:
        ts = trade.get("ts")
        if ts is None or ts.timestamp() < cutoff:
            continue
        if trade.get("anomalous"):
            continue
        wallet = (trade.get("wallet") or "").lower()
        if not wallet:
            continue
        if trade.get("kind") == "buy":
            buys += 1
            buyers.add(wallet)
        elif trade.get("kind") == "sell":
            sells += 1

    truncated = False
    if len(trades or []) >= 300:
        oldest = min((t.get("ts") for t in trades if t.get("ts")), default=None)
        if oldest is not None and oldest.timestamp() > cutoff:
            truncated = True

    return {
        "buyers": len(buyers),
        "buys": buys,
        "sells": sells,
        "window_sec": int(window_sec),
        "truncated": truncated,
    }


def check_buyers_window(trades, now, created_at=None):
    stats = buyer_window(trades, now, created_at=created_at)
    if stats is None:
        return False, "trade tidak tersedia", None
    if stats["truncated"] and stats["buyers"] < config.MIN_UNIQUE_BUYERS:
        return False, "data trade terpotong, buyer tidak bisa dipastikan", stats
    if stats["buyers"] < config.MIN_UNIQUE_BUYERS:
        return (
            False,
            "buyer unik %ds: %d < %d"
            % (stats["window_sec"], stats["buyers"], config.MIN_UNIQUE_BUYERS),
            stats,
        )
    return (
        True,
        "buyer unik %ds: %d (%d beli / %d jual)"
        % (stats["window_sec"], stats["buyers"], stats["buys"], stats["sells"]),
        stats,
    )


def alert_score(pool, sec, buyers=None):
    """
    Skor pengurutan antrean (makin tinggi makin layak dikirim lebih dulu).

    Bukan filter: hanya dipakai saat kuota terbatas.
    """
    score = 0.0

    top10_pct = (sec or {}).get("top10_pct")
    if top10_pct is not None:
        score += max(0.0, config.TOP10_MAX_PCT - float(top10_pct)) * 2.0

    buyer_count = (buyers or {}).get("buyers")
    if buyer_count is None:
        buyer_count = pool.get("buyers2") or pool.get("buyers5") or 0
    score += min(float(buyer_count), 150.0) / 15.0

    mc = float(pool.get("mc_usd") or 0)
    liq = float(pool.get("liq_usd") or 0)
    if mc > 0:
        score += min(liq / mc, 0.6) * 20.0

    age = float(pool.get("age_sec") or 0)
    score += max(0.0, (config.MAX_AGE_SEC - age) / 60.0) * 0.5
    return round(score, 3)


def near_miss(row):
    """
    Apakah penolakan ini masih mungkin membaik dalam beberapa menit?

    Semua alasan yang ada harus "masih mungkin". Honeypot/mintable/tax yang
    buruk tidak akan berubah, jadi langsung dibuang.
    """
    reasons = set(row.get("reasons") or [])
    if not reasons or reasons & {"security", "tax", "pool_dead"}:
        return False
    if not reasons <= {"top10", "lp", "buyers", "trades_unavailable"}:
        return False

    if "top10" in reasons:
        pct = row.get("top10_pct")
        if pct is not None and not (
            config.TOP10_MAX_PCT
            <= float(pct)
            <= config.TOP10_MAX_PCT + config.WATCH_TOP10_MARGIN_PCT
        ):
            return False

    if "lp" in reasons:
        status = row.get("lp_status")
        pct = row.get("lp_pct")
        if status == "unknown":
            pass
        elif status == "unlocked" and pct is not None and float(pct) >= config.WATCH_LP_MIN_PCT:
            pass
        else:
            return False

    if "buyers" in reasons:
        buyers = row.get("buyers2") or 0
        if buyers < config.MIN_UNIQUE_BUYERS * config.WATCH_BUYERS_RATIO:
            return False

    return True


def fmt_usd(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "?"
    if value >= 1_000_000:
        return "%.2fM" % (value / 1_000_000)
    if value >= 1_000:
        return "%.1fk" % (value / 1_000)
    return "%.0f" % value


def _fmt_num(value):
    if value is None:
        return "?"
    return ("%.2f" % value).rstrip("0").rstrip(".")


def fmt_price(value, sig=8):
    """
    Format harga tanpa notasi ilmiah.

    ``%.10g`` membuat harga memecoin seperti 9.09e-06 terlihat seperti
    angka aneh di Telegram. Di sini selalu desimal biasa dengan 8 angka
    penting, lalu nol di belakang dibuang.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(value) or value <= 0:
        return "?"
    if value >= 1:
        text = "%.*f" % (max(2, sig - 1 - int(math.floor(math.log10(value)))), value)
    else:
        exponent = int(math.floor(math.log10(value)))
        decimals = min(18, max(0, sig - 1 - exponent))
        text = "%.*f" % (decimals, value)
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def evaluate_cheap(pool):
    """Filter tanpa API tambahan. Kembalikan (lolos, alasan_gagal)."""
    for fn in (check_age, check_liquidity, check_market_cap, check_buyers5):
        ok, detail = fn(pool)
        if not ok:
            return False, fn.__name__, detail
    return True, None, "lolos filter murah"


def evaluate_security(pool, report, holders=None, lp_burned=None):
    """Filter keamanan + holder + LP. Kembalikan dict hasil."""
    passed = True
    reasons = []
    details = {}

    if pool_dead(report, pool.get("pool")):
        detail = lp_state(report, pool_address=pool.get("pool"))[2]
        return {
            "passed": False,
            "reasons": ["pool_dead"],
            "details": {
                "security_detail": "dilewati: pool mati",
                "tax_detail": "dilewati: pool mati",
                "top10_pct": None,
                "top10_detail": "dilewati: pool mati",
                "lp_status": "dead",
                "lp_pct": None,
                "lp_detail": detail,
                "honeypot": None,
                "mintable": None,
                "owner_pct": None,
                "creator_pct": None,
                "buy_tax": None,
                "sell_tax": None,
            },
            "top10_pct": None,
            "excluded_holders": [],
        }

    ok, security_detail = check_security(report)
    details["security_detail"] = security_detail
    if not ok:
        passed = False
        reasons.append("security")

    ok, tax_detail = check_tax(report)
    details["tax_detail"] = tax_detail
    if not ok:
        passed = False
        reasons.append("tax")

    state = security_state(report)
    details.update({
        "honeypot": state["honeypot"],
        "mintable": state["mintable"],
        "owner_pct": state["owner_pct"],
        "creator_pct": state["creator_pct"],
        "buy_tax": state["buy_tax"],
        "sell_tax": state["sell_tax"],
    })

    pct, top_detail = top10(holders)
    details["top10_pct"] = pct
    details["top10_detail"] = top_detail
    if pct is None or pct >= config.TOP10_MAX_PCT:
        passed = False
        reasons.append("top10")
        if pct is not None:
            details["top10_detail"] = "top10 %.1f%% >= %.0f%%" % (pct, config.TOP10_MAX_PCT)

    ok, lp_detail, lp_status, lp_pct = check_lp(
        report, lp_burned=lp_burned, pool_address=pool.get("pool")
    )
    details["lp_status"] = lp_status
    details["lp_pct"] = lp_pct
    details["lp_detail"] = lp_detail
    if not ok:
        passed = False
        reasons.append("pool_dead" if lp_status == "dead" else "lp")

    return {
        "passed": passed,
        "reasons": reasons,
        "details": details,
        "top10_pct": pct,
        "excluded_holders": (holders or {}).get("top") or [],
    }
