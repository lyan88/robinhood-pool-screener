# Instruksi agent harian

Kamu mengerjakan **satu item** dari `ROADMAP.md` di repo `robinhood-pool-screener`,
lalu berhenti. Skrip `deploy/agent-daily.sh` yang menjalankan kamu: dia sudah
memilih item, dan dia yang akan commit, push, deploy, dan mencentang roadmap.
Tugasmu hanya menulis kode yang benar beserta test-nya.

## Konteks proyek

Screener pool baru Robinhood Chain (chain id 4663) yang mengirim alert ke
Telegram. Baca dulu:

- `README.md` — filter, arsitektur, cara jalan.
- `config.py` — semua threshold dan default.
- `filters.py` — filter murah, keamanan, holder, LP, skor.
- `sources.py` — GeckoTerminal, GoPlus, RPC.
- `telegram.py` + `i18n.py` — format alert dan teks dua bahasa.
- `db.py` — skema SQLite dan migrasi.
- `tests/` — 100 test yang harus tetap lulus.

## Aturan keras

1. **Hanya stdlib Python.** Tidak ada dependency baru. Tidak ada `pip install`.
2. **Kompatibel Python 3.8.** CI menguji 3.8, 3.10, 3.12. Jangan pakai
   `match`, `X | Y` di anotasi, atau `dict | dict`.
3. **Jangan sentuh `.env`, `data/`, `logs/`, `locks/`.** Rahasia tidak boleh
   masuk repo.
4. **Jangan commit, jangan push, jangan deploy.** Jangan jalankan `git commit`,
   `git push`, `rsync`, atau `sudo`. Biarkan perubahan di working tree.
5. **Jangan mengubah `ROADMAP.md`.** Skrip yang mencentang.
6. **Jangan mengubah threshold** (`TOP10_MAX_PCT`, `MIN_UNIQUE_BUYERS`, dan
   kawan-kawan) kecuali itemnya memang tentang itu. Perubahan threshold tanpa
   data sudah terbukti tidak membantu.
7. **Jangan menambah dependency jaringan baru** ke layanan berbayar.
8. **Gagal dengan tenang.** Kalau API tidak memberi data, isi `None` dan
   lanjutkan — jangan melempar exception yang menghentikan satu putaran scan.

## Gaya kode

- Komentar, docstring, dan pesan log **bahasa Indonesia**, seperti kode yang
  sudah ada. Nama variabel/fungsi bahasa Inggris.
- Ikuti pola yang sudah ada: fungsi kecil, tanpa kelas kalau tidak perlu,
  `%`-formatting seperti kode sekitarnya (bukan f-string, supaya konsisten).
- Setiap pesan yang dilihat pengguna harus lewat `i18n.py` dan punya versi
  `en` **dan** `id`.
- Jangan menulis ulang file besar. Edit seperlunya.

## Yang harus kamu hasilkan

1. Perubahan kode untuk item tersebut.
2. **Unit test baru** di `tests/` yang membuktikan perilaku baru, termasuk
   kasus gagal/kosong. Tanpa jaringan — pakai data palsu.
3. Kalau ada yang terlihat pengguna (alert, laporan, konfigurasi), perbarui
   `README.md` dan `.env.example`.
4. Jalankan seluruh test sampai lulus:

   ```
   python3 -m unittest discover -s tests -q
   ```

   Kalau ada test lama yang gagal karena perubahanmu, perbaiki kodenya —
   jangan melemahkan test lama kecuali test itu memang menguji perilaku yang
   sengaja diubah (jelaskan di ringkasan).

## Kriteria selesai

- Item di roadmap terpenuhi seluruhnya, bukan sebagian.
- `python3 -m unittest discover -s tests -q` lulus semua.
- `python3 -m py_compile *.py` bersih.
- Tidak ada kredensial, token, atau path `/opt` yang masuk kode.

## Ringkasan akhir

Setelah selesai, tulis ringkasan **maksimal 10 baris** dalam bahasa Indonesia:
apa yang diubah, file mana, dan test apa yang ditambahkan. Skrip akan
memasukkan ringkasan ini ke notifikasi Telegram, jadi tulis untuk manusia yang
tidak membaca kode.
