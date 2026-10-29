#!/usr/bin/env python3
"""
Konfigurasi Robinhood Pool Screener (Robinhood Chain, chain id 4663).

Filosofi sama dengan screener Solana: tolak cepat dengan data murah
(umur, likuiditas, MC, buyers m5), lalu panggil API mahal (GoPlus, holder
scan on-chain lewat RPC, trades) hanya untuk kandidat yang tersisa.

Perbedaan penting dengan chain Solana:
  - Tidak ada mint/freeze authority di EVM. Penggantinya: honeypot,
    mintable, owner/creator holding, tax, dan fungsi berbahaya dari GoPlus.
  - Holder dihitung langsung dari log Transfer ERC20 lewat RPC, jadi tidak
    bergantung pada indexer yang sering belum siap untuk pool baru.
  - LP Uniswap v4 berupa position NFT. Status LP dipakai kalau GoPlus sudah
    mengindeks; kalau belum, alert tetap dikirim dengan label "unknown"
    (bisa diubah lewat LP_REQUIRE_KNOWN).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SCREENER_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("SCREENER_DB", DATA_DIR / "robinhood.db"))


def _load_env(path):
    """Pembaca .env sederhana, tanpa dependensi luar."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")


def _s(key, default=""):
    return os.environ.get(key, default).strip()


def _f(key, default):
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _i(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _b(key, default):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "ya")


def _ints(key, default):
    raw = _s(key, default)
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return tuple(sorted(set(out))) or (300, 1800, 3600, 21600)


# ---------------------------------------------------------------- identitas
CHAIN_NAME = "Robinhood Chain"
CHAIN_ID = _i("CHAIN_ID", 4663)
GECKO_NETWORK = _s("GECKO_NETWORK", "robinhood")
EXPLORER_URL = _s("EXPLORER_URL", "https://robinhoodchain.blockscout.com")
DEXSCREENER_NETWORK = _s("DEXSCREENER_NETWORK", "robinhood")
GMGN_BASE = _s("GMGN_BASE", "https://gmgn.ai/rh/token")

# PoolManager Uniswap v4 adalah singleton: dia memegang token semua pool v4
# sekaligus, jadi tidak boleh dihitung sebagai holder yang bisa menjual.
UNISWAP_V4_POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
BURN_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}

# ---------------------------------------------------------------- filter utama
# Pool baru di Robinhood Chain lebih lambat matang daripada Solana: saat
# diuji, new_pools berisi pool berumur 2-41 menit. Default 60 menit memberi
# waktu holder dan data keamanan untuk terbentuk.
MAX_AGE_SEC = _i("MAX_AGE_SEC", 3600)
MIN_AGE_SEC = _i("MIN_AGE_SEC", 0)
MIN_LIQ_USD = _f("MIN_LIQ_USD", 5_000)
MIN_MC_USD = _f("MIN_MC_USD", 8_000)
MAX_MC_USD = _f("MAX_MC_USD", 100_000)
TOP10_MAX_PCT = _f("TOP10_MAX_PCT", 35.0)
MIN_TOP10_HOLDERS = _i("MIN_TOP10_HOLDERS", 10)
MIN_TOP10_TOTAL_PCT = _f("MIN_TOP10_TOTAL_PCT", 5.0)
MIN_UNIQUE_BUYERS = _i("MIN_UNIQUE_BUYERS", 15)  # Robinhood lebih sepi: pakai jendela 5 menit
BUYER_WINDOW_SEC = _i("BUYER_WINDOW_SEC", 300)

# ---------------------------------------------------------------- keamanan EVM
REQUIRE_VERIFIED_CONTRACT = _b("REQUIRE_VERIFIED_CONTRACT", True)
REJECT_HONEYPOT = _b("REJECT_HONEYPOT", True)
REJECT_MINTABLE = _b("REJECT_MINTABLE", True)
REJECT_HIDDEN_OWNER = _b("REJECT_HIDDEN_OWNER", True)
REJECT_BLACKLIST = _b("REJECT_BLACKLIST", True)
REJECT_PAUSABLE = _b("REJECT_PAUSABLE", True)
REJECT_MUTABLE_TAX = _b("REJECT_MUTABLE_TAX", True)
MAX_OWNER_PCT = _f("MAX_OWNER_PCT", 10.0)
MAX_CREATOR_PCT = _f("MAX_CREATOR_PCT", 10.0)
MAX_TAX_PCT = _f("MAX_TAX_PCT", 5.0)

# LP: status dari GoPlus (lp_holders), atau cadangan on-chain untuk pool v2.
# "unknown" artinya indexer belum melihat posisi LP; default tetap lolos
# dengan label jujur di alert, karena memaksa "known" akan menolak hampir
# semua pool baru Uniswap v4.
LP_MIN_LOCKED_PCT = _f("LP_MIN_LOCKED_PCT", 99.0)
LP_ACCEPT_LOCKED = _b("LP_ACCEPT_LOCKED", True)
LP_REQUIRE_KNOWN = _b("LP_REQUIRE_KNOWN", False)
MIN_POOL_LIQ_USD = _f("MIN_POOL_LIQ_USD", 1_000)

# ---------------------------------------------------------------- sumber data
GECKO_BASE = "https://api.geckoterminal.com/api/v2"
GOPLUS_BASE = "https://api.gopluslabs.io/api/v1"
RPC_URL = _s("RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
RPC_FALLBACKS = [
    u.strip()
    for u in _s(
        "RPC_FALLBACKS",
        "https://robinhood-rpc.publicnode.com,https://robinhood.drpc.org",
    ).split(",")
    if u.strip()
]
SCAN_PAGES = _i("SCAN_PAGES", 2)
GECKO_MIN_INTERVAL = _f("GECKO_MIN_INTERVAL", 4.0)
GOPLUS_MIN_INTERVAL = _f("GOPLUS_MIN_INTERVAL", 1.5)
RPC_MIN_INTERVAL = _f("RPC_MIN_INTERVAL", 0.1)
HTTP_TIMEOUT = _f("HTTP_TIMEOUT", 25.0)
RPC_TIMEOUT = _f("RPC_TIMEOUT", 20.0)
HTTP_RETRIES = _i("HTTP_RETRIES", 3)
USER_AGENT = _s(
    "USER_AGENT",
    "robinhood-pool-screener/1.0 (+https://github.com/lyan88/robinhood-pool-screener)",
)

# Keamanan & holder cache: cukup pendek supaya data ikut matang, cukup
# panjang supaya satu putaran tidak memanggil API yang sama berkali-kali.
SECURITY_CACHE_SEC = _i("SECURITY_CACHE_SEC", 120)
HOLDER_CACHE_SEC = _i("HOLDER_CACHE_SEC", 120)

# Holder scan: RPC membatasi eth_getLogs maksimum 10 juta blok per request.
# Token baru biasanya cukup satu potongan; mundur maksimal beberapa potongan
# untuk token yanglebih tua.
HOLDER_SCAN_CHUNK_BLOCKS = _i("HOLDER_SCAN_CHUNK_BLOCKS", 10_000_000)
HOLDER_SCAN_MAX_CHUNKS = _i("HOLDER_SCAN_MAX_CHUNKS", 3)
HOLDER_SCAN_MAX_LOGS = _i("HOLDER_SCAN_MAX_LOGS", 60_000)

# ---------------------------------------------------------------- outcome
OUTCOME_HORIZONS = _ints("OUTCOME_HORIZONS", "300,1800,3600,21600")
WIN_MFE_MIN = _f("WIN_MFE_MIN", 1.5)
TRACK_MAX_ALERTS = _i("TRACK_MAX_ALERTS", 25)
TRACK_LOOKBACK_DAYS = _i("TRACK_LOOKBACK_DAYS", 7)
TRACK_MAX_ATTEMPTS = _i("TRACK_MAX_ATTEMPTS", 3)
REPORT_HOURS = _i("REPORT_HOURS", 24)

# ---------------------------------------------------------------- Telegram
TELEGRAM_BOT_TOKEN = _s("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _s("TELEGRAM_CHAT_ID")
TELEGRAM_ENABLED = _b("TELEGRAM_ENABLED", True)
ALERT_LANG = _s("ALERT_LANG", "en").strip().lower()
if ALERT_LANG not in ("en", "id"):
    ALERT_LANG = "en"
TELEGRAM_MIN_INTERVAL_SEC = _f("TELEGRAM_MIN_INTERVAL_SEC", 3.0)
TELEGRAM_MAX_PER_HOUR = _i("TELEGRAM_MAX_PER_HOUR", 40)
TELEGRAM_MAX_PER_DAY = _i("TELEGRAM_MAX_PER_DAY", 400)
DRY_RUN = _b("DRY_RUN", False)

# ---------------------------------------------------------------- antrean alert
ALERT_QUEUE_TTL_SEC = _i("ALERT_QUEUE_TTL_SEC", 900)
ALERT_QUEUE_MAX_ATTEMPTS = _i("ALERT_QUEUE_MAX_ATTEMPTS", 3)
ALERT_DRAIN_MAX = _i("ALERT_DRAIN_MAX", 6)
ALERT_QUEUE_MAX_PRICE_AGE_SEC = _i("ALERT_QUEUE_MAX_PRICE_AGE_SEC", 90)

# ---------------------------------------------------------------- watchlist
# Pool Robinhood butuh waktu lebih lama untuk "matang"; watchlist boleh
# hidup selama sisa umur pool (dibatasi MAX_AGE_SEC).
WATCH_TTL_SEC = _i("WATCH_TTL_SEC", 3600)
WATCH_INTERVAL_SEC = _i("WATCH_INTERVAL_SEC", 120)
WATCH_MAX_PER_ROUND = _i("WATCH_MAX_PER_ROUND", 4)
WATCH_MAX_CHECKS = _i("WATCH_MAX_CHECKS", 15)
WATCH_TOP10_MARGIN_PCT = _f("WATCH_TOP10_MARGIN_PCT", 10.0)
WATCH_LP_MIN_PCT = _f("WATCH_LP_MIN_PCT", 90.0)
WATCH_BUYERS_RATIO = _f("WATCH_BUYERS_RATIO", 0.6)

# ---------------------------------------------------------------- operasional
SCAN_INTERVAL_SEC = _i("SCAN_INTERVAL_SEC", 120)
LOG_KEEP_DAYS = _i("LOG_KEEP_DAYS", 14)


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def summary():
    return {
        "chain": "%s (%d)" % (CHAIN_NAME, CHAIN_ID),
        "umur_maks": MAX_AGE_SEC,
        "likuiditas_min": MIN_LIQ_USD,
        "mc": (MIN_MC_USD, MAX_MC_USD),
        "top10_maks": TOP10_MAX_PCT,
        "top10_holder_min": MIN_TOP10_HOLDERS,
        "top10_total_min": MIN_TOP10_TOTAL_PCT,
        "buyer_unik": MIN_UNIQUE_BUYERS,
        "jendela_buyer": BUYER_WINDOW_SEC,
        "tax_maks": MAX_TAX_PCT,
        "owner_maks": MAX_OWNER_PCT,
        "creator_maks": MAX_CREATOR_PCT,
        "lp_locked_min": LP_MIN_LOCKED_PCT,
        "lp_wajib_diketahui": LP_REQUIRE_KNOWN,
        "halaman_gecko": SCAN_PAGES,
        "horizon_outcome": OUTCOME_HORIZONS,
        "win_mfe": WIN_MFE_MIN,
    }
