# Robinhood Pool Screener

Screener pool baru **Robinhood Chain** (chain id 4663). Tugasnya satu:
menemukan token yang lolos filter, lalu mengirim satu alert ke Telegram.
**Tidak memegang private key dan tidak melakukan swap.**

Ini adalah versi Robinhood Chain dari
[screener Solana](https://github.com/lyan88/solana-pool-screener). Arsitektur,
antrean alert, watchlist, dan pelacakan hasilnya sama; bagian yang berbeda
adalah sumber data keamanan dan cara menghitung holder, karena EVM tidak
punya mint/freeze authority dan Uniswap v4 memakai position NFT.

## Filter

| Filter | Nilai default | Sumber |
|---|---|---|
| Honeypot | wajib bersih | GoPlus |
| Kontrak verified | wajib | GoPlus |
| Mintable | wajib tidak | GoPlus |
| Hidden owner / take-back / pausable / blacklist | wajib tidak | GoPlus |
| Owner holding | < 10% | GoPlus (balance / total supply) |
| Creator holding | < 10% | GoPlus |
| Buy/sell tax | ≤ 5% dan tidak bisa diubah | GoPlus |
| Top 10 holder | < 30% (di luar PoolManager v4, pool, dan burn; minimal 10 holder dan 5% supply) | RPC `eth_getLogs` |
| LP burned / locked | ≥ 99% kalau diketahui | GoPlus / cek burn pool v2 |
| Market cap / FDV | $8.000 – $100.000 | GeckoTerminal |
| Likuiditas | ≥ $5.000 | GeckoTerminal |
| Umur pool | < 60 menit | GeckoTerminal |
| Unique buyer | ≥ 30 dalam 5 menit | GeckoTerminal trades |

Semua angka bisa diubah di `.env` (lihat `.env.example`).

## Kenapa berbeda dari versi Solana

| Hal | Solana | Robinhood Chain |
|---|---|---|
| Keamanan token | Rugcheck: mint/freeze, top holder, LP | GoPlus: honeypot, mintable, tax, owner |
| Holder | indexer Rugcheck | dihitung sendiri dari log Transfer ERC20 |
| LP | token LP / position NFT Meteora | position NFT Uniswap v4, fallback burn pool v2 |
| Umur pool default | 10 menit | 60 menit (pool RH lebih lambat matang) |
| Chain | `solana` | `robinhood` (id 4663) |

## Cara kerja satu putaran

1. Ambil 2 halaman `new_pools` GeckoTerminal (±40 pool).
2. Saring murah: umur, likuiditas, MC, dan `buyers` m5 sebagai prefilter.
3. Untuk kandidat yang tersisa, ambil laporan GoPlus: honeypot, mintable,
   tax, owner, daftar pool, dan posisi LP.
4. Hitung top holder langsung dari rantai: `eth_getLogs` topik `Transfer`,
   lalu saldo dijumlahkan dan PoolManager Uniswap v4, alamat pool, serta
   alamat burn dibuang. Ini tidak menunggu indexer.
5. Hanya kalau lolos semua, ambil daftar trade pool dan hitung **unique
   wallet** yang membeli dalam 300 detik terakhir. Harga alert diambil dari
   trade terakhir yang wajar (bukan snapshot `new_pools` yang bisa tertinggal).
6. Kalau lolos, alert masuk **antrean berprioritas** lalu dikirim sesuai
   kuota Telegram. Kandidat yang hampir lolos masuk **watchlist** dan
   dievaluasi ulang tiap 2 menit sampai umurnya 60 menit.

## Sumber data

| Data | Sumber | Endpoint |
|---|---|---|
| Pool baru | GeckoTerminal | `/networks/robinhood/new_pools` |
| Trade & OHLCV | GeckoTerminal | `/pools/{addr}/trades`, `/ohlcv/...` |
| Keamanan kontrak | GoPlus | `/token_security/4663?contract_addresses=...` |
| Holder & supply | RPC Robinhood | `eth_getLogs`, `eth_call` |
| Harga/likuiditas cadangan | DexScreener | `/latest/dex/tokens/{ca}` |

Blockscout (`robinhoodchain.blockscout.com`) berada di belakang Cloudflare
dan sering menolak permintaan dari VPS, jadi tidak dipakai sebagai sumber
utama. Tautan explorer di alert tetap mengarah ke sana.

## Pasang

```bash
git clone <repo> robinhood-screener
cd robinhood-screener
cp .env.example .env
nano .env                  # isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID
python3 doctor.py          # cek database, API, RPC, Telegram
python3 scanner.py --once --dry-run --verbose
```

Tidak ada dependensi luar; hanya Python 3.8+ dan stdlib.

## Cron

```cron
# scan tiap 2 menit
*/2 * * * * cd /opt/robinhood-screener && flock -n locks/scan.lock python3 scanner.py >> logs/scan.log 2>&1
# tracker hasil +5m/+30m/+1j/+6j
*/5 * * * * cd /opt/robinhood-screener && flock -n locks/track.lock python3 track.py >> logs/track.log 2>&1
# laporan harian 07:00 UTC
0 7 * * * cd /opt/robinhood-screener && python3 report.py --telegram >> logs/report.log 2>&1
```

Atau pasang otomatis:

```bash
sudo ./deploy/install.sh
```

## Perintah

```bash
python3 scanner.py --once --dry-run --verbose   # lihat alasan penolakan
python3 scanner.py --once --mint 0x...          # evaluasi satu token
python3 scanner.py --test-telegram              # pesan uji
python3 track.py --status                       # ringkasan alert/outcome
python3 track.py                                # ukur hasil alert
python3 report.py --dry-run                     # laporan harian
python3 doctor.py                               # diagnosa
python3 -m unittest discover -s tests -v        # 83 unit test
```

## Batasan yang perlu diketahui

- **LP Uniswap v4** berupa position NFT. GoPlus hanya melihatnya setelah
  token terindeks; selama belum, alert menulis `LP: unknown`. Kalau mau
  menolak pool seperti itu, set `LP_REQUIRE_KNOWN=true` (siap-siap alert
  hampir tidak pernah keluar untuk pool v4 baru).
- **Holder dihitung dari log Transfer** maksimal 30 juta blok ke belakang
  (±35 hari). Token yang lebih tua dari itu akan ditolak karena data holder
  dianggap tidak lengkap.
- **GoPlus belum tentu mengenal token yang baru beberapa menit**; kalau
  honeypot tidak diketahui, token ditolak (tidak menebak).
- Angka MC memakai `market_cap_usd`, atau FDV kalau market cap kosong.
- Screener ini hanya memberi sinyal. Selalu cek kontrak dan pool sendiri
  sebelum membeli.

## Bahasa alert

`ALERT_LANG` di `.env` punya tiga mode:

Alert selalu **satu bahasa** per pesan. Screener-nya sendiri tersedia dalam
dua bahasa, dipilih lewat `.env`:

| Nilai | Hasil di Telegram |
|---|---|
| `id` | alert bahasa Indonesia (dipakai di produksi) |
| `en` | alert bahasa Inggris |

Pesan uji (`--test-telegram`) dan laporan harian mengikuti pilihan yang sama,
termasuk banner keterlambatan kalau alert baru terkirim beberapa menit
kemudian.

> Nilai `both` masih tersedia di kode untuk uji tampilan dua bahasa sekaligus,
> tapi tidak dipakai di produksi karena alert seharusnya satu bahasa.

## Autosync ke GitHub

VPS ini menyimpan sumber proyek di `/home/ubuntu/robinhood-screener` dan
menjalankan `deploy/git-sync.sh` tiap 15 menit lewat
`/etc/cron.d/robinhood-screener-git`. Skrip itu hanya commit + push kalau:

1. ada perubahan (termasuk file baru),
2. **83 unit test lulus**,
3. tidak ada `.env`, `*.db`, atau `data/` yang ter-track.

Folder produksi `/opt/robinhood-screener` tidak pernah ikut disinkronkan, jadi
token Telegram dan database tetap hanya ada di VPS.

Pasang sendiri:

```bash
sudo install -m 0644 deploy/robinhood-screener-git.cron /etc/cron.d/robinhood-screener-git
./deploy/git-sync.sh        # uji manual
```

Log: `/home/ubuntu/robinhood-screener-git.log`.

## Lisensi

MIT — lihat `LICENSE`.
