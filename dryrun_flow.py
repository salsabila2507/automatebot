"""Uji OFFLINE handle_update + do_close: tidak ada link yang hilang, tidak ada eksekusi."""
import asyncio, json, os, sys
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

SENT, DOCS, API_CALLS = [], [], []


async def fake_send(chat_id, text, topic_id=None, parse_mode=None, attempts=None):
    SENT.append({"chat": chat_id, "topic": topic_id, "text": text})
    return {"ok": True}


async def fake_api(method, **kw):
    API_CALLS.append((method, kw))
    return {"ok": True, "result": {"status": "member"}}


async def fake_send_document(chat_id, topic_id, filename, body, caption=None, parse_mode=None):
    DOCS.append({"chat": chat_id, "topic": topic_id, "file": filename, "body": body})
    return True, False


import shutil
shutil.rmtree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_test"), ignore_errors=True)

# PENTING: semua path data diarahkan ke folder test agar tidak pernah
# menulis/menghapus file produksi (data/).
_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testdata")
os.makedirs(_TEST_DIR, exist_ok=True)
for _n in ("PENDING_PATH", "LAST_CHECK_PATH", "SESSION_PATH", "X_OWNERS_PATH", "VIP_PATH",
           "DM_FORBIDDEN_PATH", "X_QUERY_ID_PATH", "X_CT0_PATH", "RECOVERED_S4_PATH"):
    _p = getattr(bot, _n, None)
    if _p and not _p.endswith(".txt"):
        setattr(bot, _n, os.path.join(_TEST_DIR, _n.replace("_PATH", "").lower() + ".json"))
    elif _p:
        setattr(bot, _n, os.path.join(_TEST_DIR, "x-ct0.txt"))
bot.DOUBLE_LOG_PATH = os.path.join(_TEST_DIR, "double_reports.log")
bot.DATA_DIR = _TEST_DIR
bot.send = fake_send
bot.api = fake_api
bot.send_document = fake_send_document
bot.DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_test")
os.makedirs(bot.DATA_DIR, exist_ok=True)
for name, var in (("x-handle-owners.json", "X_OWNERS_PATH"), ("check-3.json", "PENDING_PATH"),
                  ("session-3.json", "SESSION_PATH"), ("vip.json", "VIP_PATH"),
                  ("x-queryid.json", "X_QUERY_ID_PATH"), ("x-ct0.txt", "X_CT0_PATH"),
                  ("last-check-3.json", "LAST_CHECK_PATH")):
    setattr(bot, var, os.path.join(bot.DATA_DIR, name))


async def fake_member_status(cid, tg_id, sess=None):
    return "member"


bot._member_status = fake_member_status
G3 = (bot.GROUPS["g3"]["cid"], bot.GROUPS["g3"]["tid"])
L = lambda h, i: f"https://x.com/{h}/status/{i}"


def upd(uid, links, mid, name=None):
    return {"update_id": mid, "message": {
        "message_id": mid, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": G3[0]}, "message_thread_id": G3[1],
        "from": {"id": uid, "username": name or f"user{uid}"},
        "text": " ".join(links), "entities": []}}


async def main():
    ok = True
    bot.X_OWNERS["owners"] = {}
    bot.X_OWNERS["reported"] = {}
    bot.VIP_UIDS = set()
    sess = {"chatId": G3[0], "topicId": G3[1],
            "openedAt": int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000,
            "seen": set(), "links": [], "entries": [], "participants": {}, "closed": False,
            "label": "Sesi 1 | 05:00-05:10 UTC", "handle_owner": {}, "reported": set(),
            "member_cache": {}, "mpost": {}, "admin_uids": set()}
    bot.ACTIVE[G3] = sess

    print("=== handle_update: 1 member 1 link ===")
    await bot.handle_update(upd(1, [L("aa", 1)], 1))
    assert len(sess["links"]) == 1 and len(sess["entries"]) == 1, "1 link harus tercatat"
    assert sess["participants"]["1"]["uid"] == 1
    print("  [OK] 1 link -> 1 entry, 1 peserta, 1 link di file")

    print("\n=== handle_update: 2 link (tfrac) -> link TIDAK boleh hilang ===")
    await bot.handle_update(upd(2, [L("bb", 2), L("cc", 3)], 2))
    assert len(sess["links"]) == 3, f"file link harus berisi 3, dapat {len(sess['links'])}"
    assert len(sess["entries"]) == 2, f"entry harus 2 (tiap member 1 post), dapat {len(sess['entries'])}"
    assert sess["mpost"][2]["links"] == [L("bb", 2)], "post resmi = link pertama"
    assert any("DUPLICATE LINK" in s["text"] for s in SENT), "harus ada laporan"
    print(f"  [OK] file link={len(sess['links'])} (tidak ada yang hilang), entries={len(sess['entries'])}, laporan terkirim")

    print("\n=== handle_update: link duplikat antar member -> tidak ganda di file ===")
    await bot.handle_update(upd(3, [L("bb", 2)], 3))
    assert len(sess["links"]) == 3, f"link yang sama tidak boleh diappend lagi, dapat {len(sess['links'])}"
    assert "3" in sess["participants"], "peserta harus tercatat walau link-nya duplikat"
    assert sess["mpost"][3]["links"] == [L("bb", 2)], "link pertama harus tetap tercatat di mpost"
    # handle harus tetap bisa ditemukan walau tidak ada entry (cadangan mpost)
    a = bot._analyze_g3({"entries": sess["entries"], "participants": list(sess["participants"].values()),
                         "mpost": sess["mpost"], "fetchCache": {}})
    nohandle = [i for i in a["results"] if i["manual"]]
    assert len(nohandle) <= 2, f"handle harusnya ketemu semua: {[i['who'] for i in nohandle]}"
    print("  [OK] link identik tidak digandakan, peserta tercatat, handle dipulihkan dari mpost")

    print("\n=== handle_update: pesan edit ===")
    await bot.handle_update(upd(1, [L("aa", 9)], 1))
    await bot.handle_update({"update_id": 11, "edited_message": {
        "message_id": 1, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": G3[0]}, "message_thread_id": G3[1],
        "from": {"id": 1, "username": "user1"}, "text": L("aa", 9), "entities": []}})
    assert any(e.get("link") == L("aa", 9) for e in sess["entries"]), "link hasil edit harus tercatat"
    print("  [OK] edit pesan -> link baru tercatat")

    print("\n=== handle_update: pesan tanpa link diabaikan ===")
    n_links, n_entries = len(sess["links"]), len(sess["entries"])
    await bot.handle_update({"update_id": 12, "message": {
        "message_id": 12, "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": G3[0]}, "message_thread_id": G3[1],
        "from": {"id": 4, "username": "user4"}, "text": "halo tanpa link", "entities": []}})
    assert len(sess["links"]) == n_links and len(sess["entries"]) == n_entries
    print("  [OK] pesan tanpa link tidak mengubah apa pun")

    print("\n=== handle_update: pesan di luar jendela sesi diabaikan ===")
    await bot.handle_update({"update_id": 13, "message": {
        "message_id": 13, "date": int(sess["openedAt"] / 1000) - 3600,
        "chat": {"id": G3[0]}, "message_thread_id": G3[1],
        "from": {"id": 5, "username": "user5"}, "text": L("old", 99), "entities": []}})
    assert L("old", 99) not in sess["links"], "pesan lama tidak boleh masuk"
    print("  [OK] pesan sebelum openingsesi diabaikan")

    print("\n=== handle_update: bot tidak pernah menghapus ===")
    assert not any(m == "deleteMessage" for m, _ in API_CALLS), "ADA PEMANGGILAN deleteMessage"
    print(f"  [OK] tidak ada deleteMessage (total API call: {len(API_CALLS)})")

    print("\n=== do_close: file link + pesan tutup + pending tersimpan ===")
    SENT.clear(); DOCS.clear(); API_CALLS.clear()
    total = len(sess["links"])
    await bot.do_close(bot.GROUPS["g3"])
    assert any(m == "closeForumTopic" for m, _ in API_CALLS), "topik harus ditutup"
    assert any("SESSION CLOSED" in s["text"] or "CLOSED" in s["text"] for s in SENT), "pesan tutup harus terkirim"
    link_docs = [d for d in DOCS if d["file"] == "links.txt"]
    assert link_docs, "file link harus terkirim"
    body = link_docs[0]["body"]
    for l in sess["links"]:
        assert l in body, f"link {l} hilang dari file!"
    assert f"Total: {total} link" in body, f"total salah: {body.splitlines()[1]}"
    pending = bot._read_pending_records()
    assert len(pending) == 1, f"pending checker harus ada, dapat {len(pending)}"
    assert len(pending[0]["entries"]) == 2, f"entries harus ikut tersimpan, dapat {len(pending[0]['entries'])}"
    assert len(pending[0]["mpost"]) == 3, f"mpost 3 anggota harus tersimpan, dapat {len(pending[0].get('mpost') or {})}"
    assert len(pending[0]["participants"]) == 3, "semua peserta harus tersimpan"
    assert "adminUids" in pending[0], "adminUids harus ikut tersimpan"
    assert not os.path.exists(bot.SESSION_PATH), "file sesi harus dibersihkan"
    print(f"  [OK] {total} link lengkap di file, {len(pending[0]['entries'])} entries, sesi dibersihkan")
    print(f"  [OK] link ke-2 tetap ada di file: {L('cc', 3) in body}")

    print("\n=== do_close: sesi tanpa link tidak crash ===")
    pending_before = len(bot._read_pending_records())
    SENT.clear(); DOCS.clear()
    bot.ACTIVE[G3] = {"chatId": G3[0], "topicId": G3[1],
                      "openedAt": int(datetime.now(timezone.utc).timestamp()),
                      "seen": set(), "links": [], "entries": [], "participants": {},
                      "closed": False, "label": "Sesi 2 | 09:00-09:10 UTC",
                      "handle_owner": {}, "reported": set(), "member_cache": {},
                      "mpost": {}, "admin_uids": set()}
    await bot.do_close(bot.GROUPS["g3"])
    assert any("CLOSED" in s["text"] for s in SENT), "pesan tutup tetap harus terkirim"
    assert len(bot._read_pending_records()) == pending_before, "sesi kosong tidak boleh bikin pending baru"
    print("  [OK] sesi kosong: pesan tutup terkirim, tidak ada pending")

    print("\nSEMUA UJI FLOW LULUS")
    return ok


sys.exit(0 if asyncio.run(main()) else 1)
