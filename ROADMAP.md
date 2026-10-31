# Roadmap

Daftar pekerjaan yang dikerjakan otomatis oleh `deploy/agent-daily.sh`, satu
item per hari, mulai 09:00 WIB (02:00 UTC).

Aturan main:

- Item dikerjakan **berurutan** — agent hanya mengambil baris `- [ ]` pertama.
- Satu item harus selesai dalam satu sesi. Kalau ternyata terlalu besar,
  pecah dulu di sini, jangan setengah jalan.
- Setiap item wajib: perubahan kode + unit test baru + seluruh test lulus.
- Centang dilakukan oleh skrip, bukan agent. Jangan centang sendiri.
- Kalau gagal, skrip membatalkan semua perubahan dan item dicoba lagi besok.

---

## 1. Field GoPlus yang belum dipakai

- [ ] **Cek `owner_change_balance`, `is_proxy`, `external_call`, `anti_whale_modifiable`, `personal_slippage_modifiable`, `transfer_tax`**

Tujuan: menutup lubang keamanan yang sekarang lolos tanpa dicek.
`owner_change_balance = 1` berarti owner bisa mengubah saldo wallet siapa pun —
ini risiko paling serius di daftar ini.

Yang harus ada:
- `filters.security_state()` membaca keenam field (None = belum diketahui).
- `check_security()` menolak kalau `owner_change_balance`, `is_proxy`, atau
  `external_call` bernilai True, dengan alasan yang jelas di log.
- `personal_slippage_modifiable` dan `anti_whale_modifiable` masuk
  `check_tax()` sebagai "pajak/slippage bisa diubah".
- `transfer_tax` dipakai sebagai pengganti `buy_tax`/`sell_tax` kalau keduanya
  kosong.
- Flag baru di `config.py` + `.env.example` + tabel filter di README.

Selesai bila: ada unit test untuk tiap field (True menolak, False lolos,
None tidak menolak), dan `doctor.py` tetap 0 gagal.

## 2. Heartbeat / watchdog

- [ ] **Kirim alert Telegram kalau tidak ada scan sukses lebih dari 30 menit**

Tujuan: sekarang kalau cron mati, tidak ada yang tahu.

Yang harus ada:
- Skrip `watchdog.py` yang membaca tabel `scans`, mencari `ts` terakhir, dan
  mengirim peringatan kalau umurnya > `HEARTBEAT_MAX_AGE_SEC` (default 1800).
- Tidak spam: pakai penanda di tabel `state` atau file, kirim maksimal sekali
  per 6 jam selama masih mati.
- Kirim pesan "pulih" sekali ketika scan jalan lagi.
- Entri cron baru tiap 10 menit + dokumentasi di README.

Selesai bila: unit test untuk kondisi sehat, mati, dan pulih; cron terpasang;
pesan uji benar-benar terkirim.

## 3. Snapshot config per alert

- [ ] **Simpan versi threshold di tiap alert supaya perubahan bisa dibandingkan**

Tujuan: kemarin threshold diketatkan, hasilnya tidak terbukti membaik, dan kita
tidak bisa memisahkan efek filter dari efek pasar. Jangan terulang.

Yang harus ada:
- Kolom `config_version` di tabel `alerts` (hash pendek dari nilai filter yang
  relevan) + migrasi aman untuk DB lama.
- `report.py` bisa mengelompokkan outcome per `config_version`.
- Perintah `python3 report.py --compare` yang menampilkan win rate dan median
  MFE per versi.

Selesai bila: alert baru punya versi, alert lama tetap terbaca, dan laporan
`--compare` jalan di data nyata.

## 4. Alarm keluar

- [ ] **Beri tahu saat LP ditarik, holder besar dump, atau harga jatuh −40% dalam 15 menit**

Tujuan: ini yang menyelamatkan uang. Sekarang hanya ada sinyal masuk.

Yang harus ada:
- Pemeriksaan lanjutan untuk alert yang masih berumur < 6 jam, dijalankan
  `track.py`.
- Tiga pemicu: `lp_status` berubah dari burned/locked ke unlocked; salah satu
  top-10 holder menjual > 50% saldo yang tercatat; harga turun ≥ 40% dari
  entry dalam 15 menit.
- Satu pesan per alert per pemicu (tidak berulang), dengan bahasa yang sama
  seperti alert masuk.
- Dokumentasi cara mematikan per pemicu lewat `.env`.

Selesai bila: unit test untuk tiap pemicu (termasuk kasus tidak memicu), dan
tidak ada pesan ganda.

## 5. Shadow tracking pool yang ditolak

- [ ] **Lacak outcome pool yang ditolak filter, tanpa mengirim alert**

Tujuan: satu-satunya cara tahu apakah filter membuang kandidat bagus.

Yang harus ada:
- Tabel `shadow` berisi mint, alasan ditolak, skor, harga saat ditolak.
- Outcome +5m/+30m/+1j memakai pipeline `track.py` yang sudah ada.
- Batas jumlah per hari supaya tidak membanjiri Gecko (default 50).
- Ringkasan di laporan harian: berapa yang ditolak, dan berapa di antaranya
  naik ≥ 50%.

Selesai bila: data shadow terkumpul minimal untuk satu putaran scan dan muncul
di `report.py --dry-run`.

## 6. Backtest threshold dari data shadow

- [ ] **Hitung dampak tiap threshold terhadap pool yang diterima dan ditolak**

Tujuan: mengganti feeling dengan angka sebelum menyetel filter lagi.

Yang harus ada:
- Skrip `backtest.py` yang membaca tabel `shadow` + `alerts`.
- Untuk kombinasi threshold yang diberikan, laporkan: jumlah lolos, win rate,
  median MFE, jumlah pemenang yang terbuang.
- Output teks rapi untuk Telegram dan `--telegram` untuk mengirim.

Selesai bila: jalan di data nyata dan hasilnya masuk akal (angka cocok dengan
hitungan manual untuk satu kombinasi).

## 7. Reputasi creator

- [ ] **Tolak token dari creator yang pernah membuat honeypot atau pool mati**

Tujuan: GoPlus hanya melihat token itu sendiri, bukan riwayat creator-nya.

Yang harus ada:
- Tabel `creators` berisi alamat, jumlah token, jumlah honeypot, jumlah pool
  mati, skor.
- Diisi setiap kali `check_security()` melihat `creator_address`.
- Filter baru: tolak kalau creator punya ≥ 2 honeypot atau skor di bawah ambang
  (`MIN_CREATOR_SCORE`, default bisa dimatikan).
- Ditampilkan di alert kalau creatornya punya riwayat buruk.

Selesai bila: unit test untuk creator bersih, creator buruk, dan data kosong.

## 8. Cross-check DexScreener

- [ ] **Bandingkan harga/likuiditas Gecko dengan DexScreener, tolak kalau jauh berbeda**

Tujuan: deteksi data basi atau wash trading.

Yang harus ada:
- Fungsi di `sources.py` untuk endpoint publik DexScreener (tanpa API key),
  dengan timeout pendek dan kegagalan yang tidak memblokir scan.
- Tolak kalau selisih likuiditas > 50% atau harga > 30%, tapi hanya kalau
  DexScreener punya data untuk pool itu.
- Flag `DEXSCREENER_CHECK` di `.env` (default mati sampai terbukti stabil).

Selesai bila: unit test dengan respons palsu (cocok, berbeda jauh, kosong) dan
scan tetap jalan saat DexScreener tidak bisa diakses.

## 9. Deteksi bundle / sniper

- [ ] **Tandai kalau banyak wallet pembeli awal didanai satu alamat**

Tujuan: pola khas EVM yang tidak terlihat dari metrik holder biasa.

Yang harus ada:
- Ambil 20 pembeli pertama dari daftar trade, lalu telusuri funding wallet
  lewat RPC (dibatasi jumlah panggilan).
- Hitung berapa pembeli yang berasal dari sumber sama; simpan di tabel
  `evaluations` sebagai `bundle_pct`.
- Tampilkan di alert, dan tolak kalau `bundle_pct` > `MAX_BUNDLE_PCT`
  (default mati dulu, cukup ditampilkan).
- Kalau RPC tidak mendukung, gagal dengan tenang dan isi `None`.

Selesai bila: unit test dengan data palsu, dan scan tidak melambat lebih dari
2 detik per kandidat.

## 10. Perintah Telegram

- [ ] **Balasan perintah `/status`, `/filters`, `/pause`, `/resume`**

Tujuan: kontrol tanpa SSH.

Yang harus ada:
- `telegram.py` membaca `getUpdates` dengan offset tersimpan (tanpa library).
- Hanya melayani `TELEGRAM_CHAT_ID` yang terdaftar; pesan lain diabaikan.
- `/status` ringkas (scan terakhir, antrean, alert 24 jam), `/filters` nilai
  aktif, `/pause 60` menghentikan alert sementara, `/resume` mengaktifkan.
- Dijalankan dari cron tiap menit, bukan loop panjang.

Selesai bila: unit test untuk parsing perintah, otorisasi chat, dan pause;
tidak ada pesan dobel saat offset salah.

## 11. Perbaikan holder & LP

- [ ] **Perluas jendela scan holder dan kurangi `LP: unknown`**

Tujuan: dua keterbatasan yang paling sering muncul di alert.

Yang harus ada:
- Scan holder memakai `eth_getLogs` bertahap sampai 90 juta blok dengan batas
  waktu, bukan langsung menyerah di 3 chunk.
- Simpan cache holder per mint supaya tidak memindai ulang tiap putaran.
- Untuk Uniswap v3/v4, coba baca posisi LP lewat `balanceOf` position manager
  kalau alamatnya diketahui; kalau tidak, tetap `unknown`.
- Ukur dan catat waktu scan holder di log.

Selesai bila: waktu scan tetap < 5 detik untuk pool normal, dan ada test untuk
logika chunk serta cache.
