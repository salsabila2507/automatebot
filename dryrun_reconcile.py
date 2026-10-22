"""Uji OFFLINE reconcile link (anti 'link terlewat') + proteksi data produksi."""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testdata")
os.makedirs(_TEST_DIR, exist_ok=True)
bot.DATA_DIR = _TEST_DIR
bot.SESSION_PATH = os.path.join(_TEST_DIR, "session-3.json")
bot.DOUBLE_LOG_PATH = os.path.join(_TEST_DIR, "double_reports.log")
# reconcile_g3_links menulis pending; arahkan ke test dir supaya data/ produksi
# tidak pernah disentuh,哪怕 isi tidak berubah.
bot.PENDING_PATH = os.path.join(_TEST_DIR, "check-3.json")
bot.LAST_CHECK_PATH = os.path.join(_TEST_DIR, "last-check-3.json")

NOW = int(datetime.now(timezone.utc).timestamp() * 1000)
G3 = (bot.GROUPS["g3"]["cid"], bot.GROUPS["g3"]["tid"])


class FakeMsg:
    def __init__(self, i, text, uid, ms, caption=None):
        self.id = i; self.text = text; self.caption = caption
        self.sender_id = uid; self.date = datetime.fromtimestamp(ms / 1000, timezone.utc)


class FakeClient:
    def __init__(self, msgs):
        self.msgs = msgs; self.entity_calls = 0
    async def get_input_entity(self, cid):
        return cid
    def iter_messages(self, ent, reply_to=None, limit=None):
        async def gen():
            for m in self.msgs:
                yield m
        return gen()
    async def get_entity(self, uid):
        self.entity_calls += 1
        class U:
            username = f"u{uid}"; first_name = f"N{uid}"
        return U()


def new_sess():
    return {"chatId": G3[0], "topicId": G3[1], "openedAt": NOW - 600_000,
            "seen": set(), "links": [], "entries": [], "participants": {}, "closed": False,
            "label": "Sesi 1", "handle_owner": {}, "reported": set(), "member_cache": {},
            "mpost": {}, "admin_uids": set()}


async def main():
    ok = True
    saved = []
    bot._save_g3_session = lambda s: saved.append(1)

    print("=== reconcile: link yang hilang dari update tetap dipulihkan ===")
    sess = new_sess()
    bot.ACTIVE[G3] = sess
    msgs = [FakeMsg(5, "https://x.com/baru1/status/1", 11, NOW - 300_000),
            FakeMsg(4, "https://x.com/lama1/status/2", 12, NOW - 900_000)]
    bot.WATCHDOG = FakeClient(msgs)
    await bot.reconcile_g3_links()
    assert sess["links"] == ["https://x.com/baru1/status/1"], sess["links"]
    e = sess["entries"][0]
    assert e["who"] == "@u11" and e["uid"] == 11 and e["backfilled"] is True and e["messageId"] == 5
    assert "11" in sess["participants"] and saved, "harus simpan sesi"
    print("  [OK] link baru dipulihkan (dengan uid, nama, messageId) & sesi disimpan")

    print("\n=== reconcile: idempotent (tidak menimpa) ===")
    n_saved = len(saved)
    bot.WATCHDOG = FakeClient(msgs)
    await bot.reconcile_g3_links()
    assert sess["links"] == ["https://x.com/baru1/status/1"], f"dobel: {sess['links']}"
    assert len(sess["entries"]) == 1, f"entry dobel: {sess['entries']}"
    assert len(saved) == n_saved, "tidak perlu simpan ulang kalau tidak ada perubahan"
    print("  [OK] jalan kedua tidak menggandakan link/entry")

    print("\n=== reconcile: berhenti di awal sesi (tidak menarik pesan lama) ===")
    sess2 = new_sess()
    sess2["openedAt"] = NOW - 100_000      # sesi baru: semua pesan di bawah ini lama
    bot.ACTIVE[G3] = sess2
    bot.WATCHDOG = FakeClient(msgs)
    await bot.reconcile_g3_links()
    assert sess2["links"] == [], f"pesan lama harus diabaikan, dapat {sess2['links']}"
    print("  [OK] pesan sebelum awal sesi tidak ditarik sama sekali")
    # dan pesan tepat di dalam jendela tetap diambil
    sess2b = new_sess()
    sess2b["openedAt"] = NOW - 600_000
    bot.ACTIVE[G3] = sess2b
    bot.WATCHDOG = FakeClient([FakeMsg(7, "https://x.com/dalam/status/4", 21, NOW - 60_000),
                               FakeMsg(6, "https://x.com/luar/status/5", 22, NOW - 700_000)])
    await bot.reconcile_g3_links()
    assert sess2b["links"] == ["https://x.com/dalam/status/4"], sess2b["links"]
    print("  [OK] hanya pesan di dalam jendela sesi yang diambil")

    print("\n=== reconcile: link|caption X juga tertangkap ===")
    sess3 = new_sess()
    bot.ACTIVE[G3] = sess3
    bot.WATCHDOG = FakeClient([FakeMsg(9, "lihat foto", 13, NOW - 100_000,
                                       caption="https://x.com/cap1/status/3")])
    await bot.reconcile_g3_links()
    assert sess3["links"] == ["https://x.com/cap1/status/3"], sess3["links"]
    print("  [OK] link di caption (foto) ikut terkumpul")

    print("\n=== reconcile: tidak jalan tanpa sesi aktif / tanpa session user ===")
    sess4 = new_sess(); sess4["closed"] = True
    bot.ACTIVE[G3] = sess4
    bot.WATCHDOG = None
    await bot.reconcile_g3_links()
    assert sess4["links"] == [], "tidak boleh ada perubahan"
    print("  [OK] dilewati dengan aman")

    print("\n=== proteksi: test tidak pernah menulis ke data/ produksi ===")
    prod = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    # Rekam sidik jari produksi SEBELUM, lalu BANCIH semua akses tulis ke sana.
    prod_before = {f: (os.path.getmtime(os.path.join(prod, f)), os.path.getsize(os.path.join(prod, f)))
                   for f in sorted(os.listdir(prod))}
    real_pending, real_last = bot.PENDING_PATH, bot.LAST_CHECK_PATH

    class _NoProdWrite(Exception):
        pass

    def _forbidden(path, *a, **k):
        if os.path.abspath(str(path)).startswith(os.path.abspath(prod) + os.sep):
            raise _NoProdWrite(f"TEST MENYENTUH PATH PRODUKSI: {path}")
        return real_atomic_write(path, *a, **k)

    real_atomic_write = bot._atomic_write
    bot._atomic_write = _forbidden
    try:
        bot.PENDING_PATH = os.path.join(_TEST_DIR, "check-3.json")
        p = {"topicId": G3[1], "chatId": G3[0], "sessionName": "Sesi T", "sessionId": "pytest-1",
             "entries": [{"link": "https://x.com/a/status/1", "who": "@a", "uid": 1, "exempt": False}],
             "participants": [], "adminUids": [], "mpost": {}, "fetchCache": {}}
        bot._save_pending_check(p)
        bot._clear_pending_check("pytest-1")
    finally:
        bot._atomic_write = real_atomic_write
        bot.PENDING_PATH, bot.LAST_CHECK_PATH = real_pending, real_last

    prod_after = {f: (os.path.getmtime(os.path.join(prod, f)), os.path.getsize(os.path.join(prod, f)))
                  for f in sorted(os.listdir(prod))}
    assert prod_after == prod_before, (
        f"file produksi berubah: {set(prod_before.items()) ^ set(prod_after.items())}")
    for f in os.listdir(_TEST_DIR):
        assert "pytest-1" not in open(os.path.join(_TEST_DIR, f), encoding="utf-8", errors="ignore").read(), \
            f"record test lingering di {f}"
    print("  [OK] produksi tidak berubah sama sekali (mtime + ukuran), tidak ada record test di mana pun")

    print("\nSEMUA UJI RECONCILE LULUS")
    return ok


sys.exit(0 if asyncio.run(main()) else 1)
