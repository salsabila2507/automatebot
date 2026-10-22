"""Test file cek manual (kirim 40 menit sebelum sesi berikutnya buka).

Semua path diarahkan ke temp dir. Tidak ada panggilan Telegram sungguhan.
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

TMP = tempfile.mkdtemp(prefix="dryrun_mlist_")
os.environ["BOT_DATA_DIR"] = TMP
os.environ["MANUAL_LIST_TARGET"] = "5650021727"
os.environ["MANUAL_LIST_LEAD_MINUTES"] = "40"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot

assert bot.PENDING_PATH.startswith(TMP), ("TEST BAHAYA: PENDING_PATH bukan di temp!", bot.PENDING_PATH)
assert bot.MANUAL_LIST_ENABLED is True
assert bot.MANUAL_LIST_TARGET == [5650021727]
assert bot.MANUAL_LIST_LEAD_MINUTES == 40

SENT = []


async def fake_send_document(chat_id, topic_id, filename, body, caption=None, parse_mode=None):
    SENT.append({"chat_id": chat_id, "topic_id": topic_id, "filename": filename,
                 "body": body, "caption": caption})
    return True, False


bot.send_document = fake_send_document

WIB = timezone(timedelta(hours=7))
UTC = timezone.utc
G3_CID = bot.GROUPS["g3"]["cid"]
G3_TID = bot.GROUPS["g3"]["tid"]


def pend(label, closed_utc, n, day=26):
    base = datetime(2026, 9, day, *closed_utc, tzinfo=UTC)
    return {
        "sessionId": f"{int(base.timestamp() * 1000)}--1004398227454-868",
        "sessionLabel": label,
        "closedAt": int(base.timestamp() * 1000),
        "chatId": G3_CID,
        "topicId": G3_TID,
        "entries": [{"who": f"@u{i}", "uid": i, "link": f"https://x.com/h{i}/status/{200 + i}",
                     "atMs": int((base - timedelta(minutes=10)).timestamp() * 1000) + i * 60 * 1000}
                    for i in range(n)],
    }


def write(records):
    with open(os.path.join(TMP, "check-3.json"), "w", encoding="utf-8") as f:
        json.dump({"sessions": records}, f)


def run():
    SENT.clear()
    asyncio.run(bot.send_manual_list())
    return list(SENT)


# 1. tidak ada pending -> TIDAK kirim apa pun
write([])
assert run() == [], SENT
print("OK 1: tanpa sesi menunggu, tidak ada yang dikirim")

# 2. satu sesi -> terkirim ke developer, tanpa topic
write([pend("Sesi 4 | 18:00-18:10 UTC", (18, 10), 3)])
out = run()
assert len(out) == 1, out
assert out[0]["chat_id"] == 5650021727 and out[0]["topic_id"] is None, out
print("OK 2: terkirim ke 5650021727, tanpa topic")

# 3. TANGGAL wajib ada di header, nama file, dan caption
body, name, cap = out[0]["body"], out[0]["filename"], out[0]["caption"]
assert "# Sesi 4 | 18:00-18:10 UTC" in body, body
assert "# window: 26/09/2026 18:00-18:02 UTC / 27/09 01:00-01:02 WIB" in body, body
assert name == "SESI4-20260927-TELE-USERNAME-LINK.txt", name
assert cap == "Sesi 4 | 18:00-18:10 UTC = 27/09 01:00-01:02 WIB | 3 peserta (ASLI) - cek manual", cap
print("OK 3: tanggal ada di header + nama file + caption ->", name)

# 4. isi baris = username | link, persis seperti file yang disetujui
lines = [l for l in body.split("\n") if l and not l.startswith("#")]
assert lines == ["@u0 | https://x.com/h0/status/200",
                 "@u1 | https://x.com/h1/status/201",
                 "@u2 | https://x.com/h2/status/202"], lines
print("OK 4:", lines[0])

# 5. jumlah di header = jumlah baris
assert "# total: 3 peserta" in body, body
assert len(lines) == 3
print("OK 5: total di header cocok dengan jumlah baris")

# 6. beberapa pending -> yang paling baru tertutup yang dikirim
write([pend("Sesi 3 | 14:00-14:10 UTC", (14, 10), 2),
       pend("Sesi 4 | 18:00-18:10 UTC", (18, 10), 5),
       pend("Sesi 2 | 09:00-09:10 UTC", (9, 10), 9)])
out = run()
assert len(out) == 1, out
assert out[0]["filename"].startswith("SESI4-"), out[0]["filename"]
assert "Sesi 4" in out[0]["caption"], out[0]["caption"]
assert "# total: 5 peserta" in out[0]["body"], out[0]["body"]
print("OK 6: dari 3 pending, terkirim yang paling baru (Sesi 4, 5 peserta)")

# 7. sesi tanpa entry -> tidak kirim (lebih baik kosong daripada salah)
write([{"sessionId": "1--1004398227454-868", "sessionLabel": "Sesi 1 | 05:00-05:10 UTC",
        "closedAt": 1, "entries": []}])
assert run() == [], SENT
print("OK 7: sesi tanpa entry tidak dikirim")

# 8. label tanpa "Sesi" tidak bikin crash
write([{"sessionId": "2--x", "sessionLabel": "Manual", "chatId": G3_CID, "topicId": G3_TID, "closedAt": 1,
        "entries": [{"who": "@a", "link": "https://x.com/a/status/1", "atMs": 1000}]}])
out = run()
assert len(out) == 1, out
assert out[0]["filename"] == "SESI0-19700101-TELE-USERNAME-LINK.txt", out[0]["filename"]
print("OK 8: label tanpa nomor slot ->", out[0]["filename"])

# 9. tanpa atMs tidak crash, pakai closedAt
write([{"sessionId": "3--x", "sessionLabel": "Sesi 2 | 09:00-09:10 UTC", "chatId": G3_CID, "topicId": G3_TID, "closedAt": 1789000000000,
        "entries": [{"who": "@a", "link": "https://x.com/a/status/1"}]}])
out = run()
assert len(out) == 1, out
assert "# window:" in out[0]["body"], out[0]["body"]
print("OK 9: entry tanpa atMs tetap ada tanggalnya")

# 10. tidak menulis ke path produksi
prod = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "check-3.json")
before = os.path.getmtime(prod)
write([pend("Sesi 1 | 05:00-05:10 UTC", (5, 10), 1)])
run()
assert os.path.getmtime(prod) == before, "pending produksi berubah!"
print("OK 10: file pending produksi tidak disentuh")

# 11. jadwal: 40 menit sebelum tiap sesi g3 (05/09/14/18 UTC -> 04:20/08:20/13:20/17:20 UTC)
lead = [(oh * 60 + om - 40) % (24 * 60) for oh, om, _, _ in bot.GROUPS["g3"]["sch"]]
assert lead == [4 * 60 + 20, 8 * 60 + 20, 13 * 60 + 20, 17 * 60 + 20], lead
print("OK 11: jadwal kirim (UTC) =", [f"{m//60:02d}:{m%60:02d}" for m in lead],
      "= WIB", [f"{(m//60+7)%24:02d}:{m%60:02d}" for m in lead])

# 12. job benar-benar terdaftar di build()
import inspect
src = inspect.getsource(bot.build)
assert "g3_list" in src and "send_manual_list" in src, "job manual list tidak terdaftar"
print("OK 12: job g3_list terdaftar di build()")

print("LULUS: dryrun_manuallist 12/12")
