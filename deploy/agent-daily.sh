#!/usr/bin/env bash
#
# Kerjakan SATU item roadmap per hari, lalu commit, push, deploy, dan lapor
# ke Telegram. Dijadwalkan 02:00 UTC (09:00 WIB) lewat
# /etc/cron.d/robinhood-screener-agent.
#
# Alur:
#   1. pastikan repo bersih, ambil item pertama yang belum dicentang
#   2. jalankan `opencode run` headless dengan model gratis
#   3. test wajib lulus; kalau gagal, semua perubahan dibuang
#   4. centang roadmap, commit, push
#   5. rsync ke /opt, jalankan doctor.py
#   6. kalau doctor gagal, revert commit + deploy, lalu lapor
#
# Pemakaian:
#   deploy/agent-daily.sh --dry-run    # lihat item & prompt, tanpa memanggil model
#   deploy/agent-daily.sh              # jalankan sungguhan

set -uo pipefail

REPO=/home/ubuntu/robinhood-screener
PROD=/opt/robinhood-screener
MODEL=${ROADMAP_MODEL:-opencode/deepseek-v4.1-flash-free}
OPENCODE=${OPENCODE_BIN:-/home/ubuntu/.opencode/bin/opencode}
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/agent.log"
LOCK="$REPO/locks/agent.lock"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

mkdir -p "$LOG_DIR" "$REPO/locks"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG" >&2; }

notify() {
    local text=$1
    if [ "$DRY_RUN" = 1 ]; then
        log "NOTIF: $text"
        return 0
    fi
    printf '%s' "$text" | (cd "$PROD" && sudo -u screener python3 deploy/agent_notify.py) \
        >> "$LOG" 2>&1 || log "notifikasi Telegram gagal"
}

rollback_code() {
    git reset --hard "$PREV" > /dev/null 2>&1
    git clean -fdq > /dev/null 2>&1
}

sync_prod() {
    sudo rsync -a \
        --exclude .git --exclude data --exclude logs --exclude locks \
        --exclude __pycache__ --exclude .env \
        "$REPO/" "$PROD/" >> "$LOG" 2>&1
    sudo chown -R screener:screener "$PROD" >> "$LOG" 2>&1
}

doctor() {
    sudo -u screener bash -lc "cd $PROD && timeout 300 python3 doctor.py"
}

exec 9>"$LOCK"
if ! flock -n 9; then
    log "agent lain masih berjalan, keluar"
    exit 0
fi

cd "$REPO" || exit 1

if [ -n "$(git status --porcelain)" ]; then
    log "repo kotor, batal"
    notify "⚠️ Agent roadmap tidak jalan: repo kotor (ada perubahan belum di-commit)."
    exit 3
fi

ITEM=$(python3 - <<'PY'
from pathlib import Path

for line in Path("ROADMAP.md").read_text().splitlines():
    if line.startswith("- [ ] "):
        print(line[6:].strip())
        break
PY
)

if [ -z "$ITEM" ]; then
    log "semua item roadmap sudah selesai"
    notify "🎉 Semua item roadmap Robinhood Screener sudah selesai."
    exit 0
fi

PREV=$(git rev-parse HEAD)
PROMPT_FILE=$(mktemp)
AGENT_OUT=$(mktemp)
DOC_OUT=$(mktemp)
trap 'rm -f "$PROMPT_FILE" "$AGENT_OUT" "$DOC_OUT"' EXIT

{
    cat deploy/agent-prompt.md
    printf '\n\n## Item hari ini\n\n%s\n\n' "$ITEM"
    printf 'Kerjakan item ini sampai selesai, lalu tulis ringkasan akhir.\n'
} > "$PROMPT_FILE"

if [ "$DRY_RUN" = 1 ]; then
    log "dry-run: item = $ITEM"
    log "prompt = $(wc -l < "$PROMPT_FILE") baris, model = $MODEL"
    sed -n '1,6p' "$PROMPT_FILE" >> "$LOG"
    exit 0
fi

log "mulai: $ITEM"
timeout 3600 "$OPENCODE" run --auto -m "$MODEL" --title "roadmap: $ITEM" \
    "$(cat "$PROMPT_FILE")" > "$AGENT_OUT" 2>&1
RC=$?
cat "$AGENT_OUT" >> "$LOG"

# Agent kadang commit sendiri walau dilarang; lipat ke commit skrip.
if [ "$(git rev-parse HEAD)" != "$PREV" ]; then
    log "agent membuat commit sendiri, dilipat ke $PREV"
    git reset --soft "$PREV" > /dev/null 2>&1
fi

if [ -z "$(git status --porcelain)" ]; then
    log "tidak ada perubahan (rc=$RC)"
    notify "⚠️ Tidak ada perubahan untuk item: $ITEM. Item tidak dicentang, dicoba lagi besok."
    exit 5
fi

if ! { python3 -m py_compile ./*.py && python3 -m unittest discover -s tests -q; } \
        >> "$AGENT_OUT" 2>&1; then
    log "test/compile gagal, rollback"
    rollback_code
    notify "❌ Test gagal untuk item: $ITEM. Perubahan dibatalkan, dicoba lagi besok."
    exit 6
fi

TESTS=$(grep -oE "Ran [0-9]+ tests" "$AGENT_OUT" | tail -1)
TESTS=${TESTS:-"Ran ? tests"}

python3 deploy/roadmap_tick.py "$ITEM" >> "$LOG" 2>&1
git add -A
git -c user.name="roadmap-agent" -c user.email="roadmap-agent@users.noreply.github.com" \
    commit -qm "auto: $ITEM" >> "$LOG" 2>&1
COMMIT=$(git rev-parse --short HEAD)

if ! git push -q origin main >> "$LOG" 2>&1; then
    log "push gagal"
    notify "⚠️ Commit $COMMIT dibuat tapi push gagal. Item: $ITEM"
    exit 7
fi

sync_prod

if ! doctor > "$DOC_OUT" 2>&1; then
    log "doctor gagal, coba sekali lagi setelah 60 detik"
    sleep 60
    if ! doctor > "$DOC_OUT" 2>&1; then
        log "doctor tetap gagal, revert"
        cat "$DOC_OUT" >> "$LOG"
        git revert --no-edit HEAD >> "$LOG" 2>&1
        git push -q origin main >> "$LOG" 2>&1
        sync_prod
        notify "❌ Deploy dibatalkan: doctor gagal setelah item: $ITEM. Kode dikembalikan ke versi sebelumnya."
        exit 8
    fi
fi

DOC_LINE=$(grep -E "[0-9]+ gagal" "$DOC_OUT" | tail -1)
SUMMARY=$(grep -v '^[[:space:]]*$' "$AGENT_OUT" | tail -n 8 | cut -c1-300 | sed 's/[<>&]//g')

notify "✅ Roadmap hari ini selesai

Item: $ITEM
$SUMMARY

commit: $COMMIT · $TESTS · ${DOC_LINE:-doctor ok}"

log "selesai: $ITEM ($COMMIT)"
exit 0
