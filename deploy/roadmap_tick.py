#!/usr/bin/env python3
"""
Centang satu item di ROADMAP.md.

Dipakai oleh deploy/agent-daily.sh setelah test lulus. Item dicari berdasarkan
teks persisnya, supaya aman walau agent sempat mengubah urutan file.

    python3 deploy/roadmap_tick.py "Cek owner_change_balance ..." abc1234
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROADMAP = Path(__file__).resolve().parent.parent / "ROADMAP.md"


def main(argv):
    if len(argv) < 2:
        print("pakai: roadmap_tick.py <teks item> [commit]", file=sys.stderr)
        return 2
    item = argv[1].strip()
    commit = argv[2].strip() if len(argv) > 2 else ""

    lines = ROADMAP.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("- [ ] ") and line[6:].strip() == item:
            lines[index] = "- [x] " + line[6:]
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            note = "      selesai %s" % stamp + (" · `%s`" % commit if commit else "")
            lines.insert(index + 1, note)
            ROADMAP.write_text("\n".join(lines) + "\n")
            print("dicentang: %s" % item)
            return 0

    print("item tidak ditemukan (mungkin sudah dicentang): %s" % item, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
