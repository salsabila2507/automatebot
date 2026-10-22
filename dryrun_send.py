"""Test /send. Tidak menulis ke path produksi sama sekali."""
import asyncio
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="dryrun_send_")
os.environ["BOT_DATA_DIR"] = TMP
os.environ["SEND_TARGETS"] = "5318526305"
os.environ["SEND_ALLOWED"] = "5650021727"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot
assert bot.PENDING_PATH.startswith(TMP), ("TEST BAHAYA: PENDING_PATH bukan temp!", bot.PENDING_PATH)

SENT = []


async def fake_send(chat_id, text, topic_id=None, parse_mode=None, attempts=None):
    SENT.append((chat_id, text))
    return {"ok": True}


bot.send = fake_send

assert bot.SEND_TARGETS == [5318526305], bot.SEND_TARGETS
assert bot.SEND_ALLOWED == {5650021727}, bot.SEND_ALLOWED


def msg(text, uid=5650021727, chat_type="private"):
    return {"message_id": 1, "date": 1, "chat": {"id": uid, "type": chat_type},
            "from": {"id": uid}, "text": text}


def run(m):
    SENT.clear()
    asyncio.run(bot._handle_send_command(m))
    return list(SENT)


# 1. isi diteruskan apa adanya ke customer
out = run(msg("/send Defaulters: Sesi 3\n1. @a\n2. @b"))
assert SENT[0][0] == 5318526305, SENT
assert SENT[0][1] == "Defaulters: Sesi 3\n1. @a\n2. @b", repr(SENT[0][1])
assert SENT[1][0] == 5650021727, SENT
print("OK 1: isi ke customer apa adanya + konfirmasi ke developer")

# 2. /send kosong tidak mengirim apa pun ke customer
out = run(msg("/send"))
assert all(c != 5318526305 for c, _ in SENT), SENT
assert "kosong" in SENT[0][1], SENT
print("OK 2: /send kosong tidak terkirim ke customer")

# 3. hanya baris pertama yang dipakai, sisa router lain tidak ikut
out = run(msg("/send baris1\nbaris2\nbaris3"))
assert SENT[0][1] == "baris1\nbaris2\nbaris3", repr(SENT[0][1])
print("OK 3: multi-line utuh")

# 4. perintah lain tidak tertangkap
assert run(msg("/start")) == []
assert run(msg("/vip @someone")) == []
assert run(msg("hello")) == []
print("OK 4: perintah lain tidak tertangkap")

# 5. dari grup diabaikan
assert run(msg("/send a", chat_type="group")) == []
print("OK 5: dari grup diabaikan")

# 6. orang lain di DM juga diabaikan
assert run(msg("/send a", uid=999999)) == []
print("OK 6: uid lain diabaikan")

# 7. isi panjang dipecah, tidak ada yang hilang
long_payload = "x" * 10000
out = run(msg("/send " + long_payload))
chunks = [t for c, t in SENT if c == 5318526305]
assert all(len(c) <= 4096 for c in chunks), [len(c) for c in chunks]
assert "".join(chunks) == long_payload, len("".join(chunks))
print("OK 7: %s karakter dipecah jadi %s potongan, utuh" % (len(long_payload), len(chunks)))

# 8. handle_update lewat DM tidak pernah menyentuh sesi/grup
SENT.clear()
asyncio.run(bot.handle_update({"update_id": 1, "message": msg("/send uji")}))
assert SENT[0][0] == 5318526305, SENT
print("OK 8: hook di handle_update jalan")

# 9. handle_update dari grup tidak memicu /send
SENT.clear()
asyncio.run(bot.handle_update({"update_id": 2, "message": msg("/send uji", chat_type="group")}))
assert SENT == [], SENT
print("OK 9: grup tidak memicu /send")

# 10. tidak ada file produksi yang tersentuh
assert not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "send.json"))
print("OK 10: tidak menulis ke path produksi")

print("OK 1-10: /send selesai")

# --- tambahan: preview /send masuk log ---------------------------------------
import logging as _lg

RECORDS = []


class Cap(_lg.Handler):
    def emit(self, record):
        RECORDS.append(record.getMessage())


_h = Cap()
bot.log.addHandler(_h)
bot.log.setLevel(_lg.INFO)

run(msg("/send Defaulters: Sesi 3\n1. @a\n2. @b"))
rec = [r for r in RECORDS if "/send diterima" in r]
assert rec, RECORDS
assert "sha=" in rec[0] and "char=30" in rec[0], rec[0]
assert "1. @a | 2. @b" in rec[0], rec[0]
print("OK 11: isi /send tercatat di log ->", rec[0].split("uid=5650021727: ")[-1])

# hash harus berubah kalau isi berubah, dan sama untuk isi sama
a = bot._send_preview("abc")
b = bot._send_preview("abc")
c = bot._send_preview("abd")
assert a == b and a != c, (a, b, c)
print("OK 12: hash stabil untuk isi sama, beda untuk isi beda")

# preview tidak bocorin >100 karakter pertama
long_payload = "z" * 500
pv = bot._send_preview(long_payload)
assert pv.count("z") <= 100, pv
assert "char=500" in pv, pv
print("OK 13: preview dipotong 100 karakter, char= dicatat penuh")

print("LULUS: dryrun_send 13/13")
