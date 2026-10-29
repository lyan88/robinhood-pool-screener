#!/usr/bin/env python3
"""
Adaptor sumber data Robinhood Chain. Semua perbedaan bentuk API
dinormalisasi di sini.

Sumber:
  - GeckoTerminal : pool baru + daftar trade + OHLCV (tanpa API key)
  - GoPlus        : keamanan kontrak EVM (honeypot, mintable, tax, owner, LP)
  - RPC node      : holder ERC20 dihitung dari log Transfer, plus totalSupply
"""

import time
from datetime import datetime, timezone

import config
import net

GECKO = net.limiter("gecko", config.GECKO_MIN_INTERVAL)
GOPLUS = net.limiter("goplus", config.GOPLUS_MIN_INTERVAL)
RPC = net.limiter("rpc", config.RPC_MIN_INTERVAL)

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
SUPPLY_SELECTOR = "0x18160ddd"
BALANCE_OF_SELECTOR = "0x70a08231"


def _f(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=None):
    v = _f(value)
    return default if v is None else int(v)


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pool_from_gecko(item):
    attrs = item.get("attributes") or {}
    rel = item.get("relationships") or {}
    base = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
    quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id", "")
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id", "")
    name = attrs.get("name") or ""
    symbol = name.split(" / ")[0].strip() if " / " in name else name.strip()
    tx = attrs.get("transactions") or {}
    m5 = tx.get("m5") or {}
    m15 = tx.get("m15") or {}
    created = parse_ts(attrs.get("pool_created_at"))
    now = datetime.now(timezone.utc)
    age = max(0, int((now - created).total_seconds())) if created else None
    market_cap = _f(attrs.get("market_cap_usd"))
    fdv = _f(attrs.get("fdv_usd"))
    # Robinhood Chain sering belum punya market_cap_usd; FDV adalah perkiraan
    # yang lebih baik daripada membuang kandidat.
    mc = market_cap if market_cap is not None else fdv
    return {
        "pool": (attrs.get("address") or item.get("id", "").split("_", 1)[-1]).lower(),
        "mint": base.split("_", 1)[-1].lower() if base else "",
        "quote_mint": quote.split("_", 1)[-1] if quote else "",
        "name": name,
        "symbol": symbol,
        "dex": dex,
        "created_at": created,
        "age_sec": age,
        "liq_usd": _f(attrs.get("reserve_in_usd"), 0.0),
        "fdv_usd": fdv,
        "market_cap_usd": market_cap,
        "mc_usd": mc,
        "price_usd": _f(attrs.get("base_token_price_usd")),
        "buyers5": _i(m5.get("buyers"), 0),
        "buys5": _i(m5.get("buys"), 0),
        "sells5": _i(m5.get("sells"), 0),
        "buyers15": _i(m15.get("buyers"), 0),
        "volume5_usd": _f((attrs.get("volume_usd") or {}).get("m5"), 0.0),
        "source": "gecko:new_pools",
    }


def fetch_new_pools(pages=None):
    """Ambil pool baru dari GeckoTerminal, halaman 1..pages."""
    pages = config.SCAN_PAGES if pages is None else pages
    out = []
    seen = set()
    errors = []
    for page in range(1, pages + 1):
        url = "%s/networks/%s/new_pools?page=%d" % (
            config.GECKO_BASE, config.GECKO_NETWORK, page
        )
        try:
            data = net.get_json(url, lim=GECKO)
        except net.SourceError as exc:
            errors.append(str(exc))
            continue
        for item in data.get("data") or []:
            pool = _pool_from_gecko(item)
            if not pool["pool"] or not pool["mint"] or pool["pool"] in seen:
                continue
            seen.add(pool["pool"])
            out.append(pool)
    if not out and errors:
        raise net.SourceError("; ".join(errors))
    return out, errors


def fetch_pool(pool_address):
    """Ambil data terbaru satu pool (untuk watchlist)."""
    if not pool_address:
        return None
    url = "%s/networks/%s/pools/%s" % (
        config.GECKO_BASE, config.GECKO_NETWORK, net.quote(pool_address)
    )
    data = net.get_json(url, lim=GECKO)
    item = data.get("data") if isinstance(data, dict) else None
    if not item:
        return None
    pool = _pool_from_gecko(item)
    if not pool["pool"] or not pool["mint"]:
        return None
    return pool


def _trade_from_gecko(item):
    attrs = item.get("attributes") or {}
    ts = parse_ts(attrs.get("block_timestamp"))
    return {
        "ts": ts,
        "kind": (attrs.get("kind") or "").lower(),
        "wallet": attrs.get("tx_from_address") or "",
        "tx": attrs.get("tx_hash") or "",
        "from_token": attrs.get("from_token_address") or "",
        "to_token": attrs.get("to_token_address") or "",
        "price_from_usd": _f(attrs.get("price_from_in_usd")),
        "price_to_usd": _f(attrs.get("price_to_in_usd")),
        "volume_usd": _f(attrs.get("volume_in_usd"), 0.0),
        "anomalous": bool(attrs.get("is_anomalous")),
    }


def trade_price(trade, mint):
    """Harga mint pada satu trade; alamat EVM dibandingkan tanpa peduli huruf."""
    if not trade or trade.get("anomalous"):
        return None
    mint = (mint or "").lower()
    to_token = (trade.get("to_token") or "").lower()
    from_token = (trade.get("from_token") or "").lower()
    if to_token == mint:
        price = trade.get("price_to_usd")
    elif from_token == mint:
        price = trade.get("price_from_usd")
    else:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def latest_trade_price(trades, mint, max_age_sec=180, now=None):
    """
    Harga dari trade terakhir yang wajar (bukan anomalous).

    Snapshot ``new_pools`` bisa tertinggal beberapa menit; trade terakhir
    lebih dekat ke harga yang benar-benar terjadi. Kalau tidak ada trade
    segar, kembalikan None supaya pemanggil memakai snapshot.
    """
    now = now or datetime.now(timezone.utc)
    best_ts = None
    best_price = None
    for trade in trades or []:
        price = trade_price(trade, mint)
        if price is None:
            continue
        ts = trade.get("ts")
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if age < -30:
            continue
        if max_age_sec is not None and age > max_age_sec:
            continue
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best_price = price
    return best_price


def fetch_trades(pool):
    """Trade terakhir untuk satu pool. Gecko membatasi jumlah baris."""
    url = "%s/networks/%s/pools/%s/trades" % (
        config.GECKO_BASE, config.GECKO_NETWORK, net.quote(pool)
    )
    data = net.get_json(url, lim=GECKO)
    trades = [_trade_from_gecko(x) for x in (data.get("data") or [])]
    return [t for t in trades if t["ts"] and t["wallet"]]


def fetch_ohlcv(pool, timeframe="minute", aggregate=1, limit=1000, before_ts=None):
    """
    Lilin OHLCV dari GeckoTerminal.

    Bentuk asli: data.attributes.ohlcv_list = [[ts, open, high, low, close, vol], ...]
    Dikembalikan urut naik sebagai list dict.
    """
    url = "%s/networks/%s/pools/%s/ohlcv/%s?aggregate=%d&limit=%d&currency=usd&token=base" % (
        config.GECKO_BASE, config.GECKO_NETWORK, net.quote(pool),
        timeframe, aggregate, max(1, min(int(limit), 1000)),
    )
    if before_ts:
        url += "&before_timestamp=%d" % int(before_ts)
    data = net.get_json(url, lim=GECKO)
    raw = ((data.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    candles = []
    for row in raw:
        if not isinstance(row, list) or len(row) < 6:
            continue
        candles.append({
            "ts": int(row[0]),
            "open": _f(row[1]),
            "high": _f(row[2]),
            "low": _f(row[3]),
            "close": _f(row[4]),
            "volume": _f(row[5]),
        })
    candles.sort(key=lambda c: c["ts"])
    return candles


_cache = {}


def fetch_goplus(mint):
    """Laporan keamanan GoPlus untuk satu token. None kalau belum terindeks."""
    mint = (mint or "").lower()
    if not mint:
        return None
    now = time.time()
    hit = _cache.get(mint)
    if hit and now - hit[0] < config.SECURITY_CACHE_SEC:
        return hit[1]
    url = "%s/token_security/%d?contract_addresses=%s" % (
        config.GOPLUS_BASE, config.CHAIN_ID, net.quote(mint)
    )
    try:
        data = net.get_json(url, lim=GOPLUS)
    except net.SourceError:
        data = None
    report = None
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        result = data["result"]
        report = result.get(mint) or result.get(mint.lower())
        if report is None and result:
            report = next(iter(result.values()))
        if not isinstance(report, dict):
            report = None
    _cache[mint] = (now, report)
    return report


def clear_cache():
    _cache.clear()


# ---------------------------------------------------------------- JSON-RPC
def rpc_call(method, params):
    """Panggil node Robinhood Chain, coba RPC cadangan kalau yang utama gagal."""
    urls = [config.RPC_URL] + [u for u in config.RPC_FALLBACKS if u != config.RPC_URL]
    last_error = None
    for url in urls:
        try:
            data = net.post_json(
                url,
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                lim=RPC,
                timeout=config.RPC_TIMEOUT,
                retries=1,
            )
            if not isinstance(data, dict):
                raise net.SourceError("rpc: respons bukan objek")
            if data.get("error"):
                raise net.SourceError("rpc: %s" % data["error"])
            return data.get("result")
        except net.SourceError as exc:
            last_error = exc
    raise last_error or net.SourceError("rpc: tidak ada endpoint yang menjawab")


def block_number():
    return int(rpc_call("eth_blockNumber", []), 16)


def _transfer_logs(mint, start, end):
    return rpc_call(
        "eth_getLogs",
        [{
            "address": mint,
            "topics": [TRANSFER_TOPIC],
            "fromBlock": hex(start),
            "toBlock": hex(end),
        }],
    )


def _log_address(topic):
    return "0x" + topic[-40:].lower()


def holders_from_logs(logs, supply, excludes=None):
    """
    Hitung saldo holder dari log Transfer. Fungsi murni, mudah diuji.

    ``supply`` adalah totalSupply dalam satuan terkecil. Persentase dihitung
    dari saldo/supply sehingga decimals token tidak perlu diketahui.
    """
    try:
        supply = int(supply)
    except (TypeError, ValueError):
        return None
    if supply <= 0:
        return None

    excluded = {a.lower() for a in (excludes or set())}
    excluded |= set(config.BURN_ADDRESSES)
    excluded.add(config.UNISWAP_V4_POOL_MANAGER.lower())

    balances = {}
    zero = "0x0000000000000000000000000000000000000000"
    for log in logs or []:
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        try:
            value = int(log.get("data") or "0x0", 16)
        except (TypeError, ValueError):
            continue
        src = _log_address(topics[1])
        dst = _log_address(topics[2])
        if src != zero:
            balances[src] = balances.get(src, 0) - value
        if dst != zero:
            balances[dst] = balances.get(dst, 0) + value

    kept = sorted(
        ((bal, addr) for addr, bal in balances.items() if bal > 0 and addr not in excluded),
        reverse=True,
    )
    top = kept[:10]
    top_pct = sum(bal for bal, _ in top) * 100.0 / supply
    return {
        "holders": len(kept),
        "top10_pct": round(top_pct, 4),
        "top": [
            {"address": addr, "pct": round(bal * 100.0 / supply, 4)}
            for bal, addr in top
        ],
        "supply": supply,
        "logs": len(logs or []),
    }


def total_supply(mint):
    raw = rpc_call("eth_call", [{"to": mint, "data": SUPPLY_SELECTOR}, "latest"])
    if not raw or raw == "0x":
        return None
    return int(raw, 16)


def fetch_holders(mint, excludes=None):
    """
    Holder ERC20 dari log Transfer, tanpa indexer.

    Kita memindai mundur maksimal beberapa potongan 10 juta blok (batas
    eth_getLogs di RPC Robinhood). Kalau log mint (transfer dari 0x0) belum
    ditemukan, data dianggap tidak lengkap dan dikembalikan None supaya
    filter tidak mengambil kesimpulan dari holder yang salah.
    """
    mint = (mint or "").lower()
    if not mint:
        return None

    latest = block_number()
    end = latest
    logs = []
    complete = False
    for _ in range(max(1, config.HOLDER_SCAN_MAX_CHUNKS)):
        start = max(0, end - config.HOLDER_SCAN_CHUNK_BLOCKS + 1)
        part = _transfer_logs(mint, start, end)
        if not isinstance(part, list):
            raise net.SourceError("eth_getLogs: respons bukan list")
        if len(logs) + len(part) > config.HOLDER_SCAN_MAX_LOGS:
            return None
        logs = part + logs
        zero = "0x" + "0" * 64
        if any((log.get("topics") or [None, None])[1:2] == [zero] for log in part):
            complete = True
            break
        if start == 0:
            complete = True
            break
        end = start - 1

    if not complete:
        return None
    if not logs:
        return {"holders": 0, "top10_pct": None, "top": [], "supply": None, "logs": 0}

    supply = total_supply(mint)
    result = holders_from_logs(logs, supply, excludes=excludes)
    if result is None:
        return None
    result["complete"] = complete
    return result


def fetch_lp_burned(pool):
    """
    Cadangan untuk pool Uniswap v2: persentase token LP yang dikirim ke
    alamat burn. Pool v4 memakai position NFT, jadi fungsi ini mengembalikan
    None untuk alamat pool 32 byte.
    """
    pool = (pool or "").lower()
    if len(pool) != 42 or not pool.startswith("0x"):
        return None
    try:
        supply = total_supply(pool)
        if not supply:
            return None
        burned = 0
        for addr in config.BURN_ADDRESSES:
            data = BALANCE_OF_SELECTOR + "0" * 24 + addr[2:].lower()
            raw = rpc_call("eth_call", [{"to": pool, "data": data}, "latest"])
            if raw and raw != "0x":
                burned += int(raw, 16)
        return min(100.0, burned * 100.0 / supply)
    except net.SourceError:
        return None
