"""Uji OFFLINE pengiriman laporan checker: HANYA DM, tidak pernah ke topic."""
import asyncio, json, os, shutil, sys
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

# PENTING: semua path data diarahkan ke folder test agar tidak pernah
# menulis/menghapus file produksi (data/).
_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testdata")
os.makedirs(_TEST_DIR, exist_ok=True)
for _n in ("PENDING_PATH", "LAST_CHECK_PATH", "SESSION_PATH", "X_OWNERS_PATH", "VIP_PATH",
           "X_QUERY_ID_PATH", "X_CT0_PATH", "RECOVERED_S4_PATH"):
    _p = getattr(bot, _n, None)
    if _p and not _p.endswith(".txt"):
        setattr(bot, _n, os.path.join(_TEST_DIR, _n.replace("_PATH", "").lower() + ".json"))
    elif _p:
        setattr(bot, _n, os.path.join(_TEST_DIR, "x-ct0.txt"))
bot.DOUBLE_LOG_PATH = os.path.join(_TEST_DIR, "double_reports.log")
bot.DATA_DIR = _TEST_DIR
# do_check_g3() keluar duluan kalau CHECKER_ENABLED=0; test ini menguji
# jalannyaikos jalur pengiriman, jadi dinyalakan khusus di dalam test.
bot.CHECKER_ENABLED = True
# OFFLINE TOTAL
bot.X_AUTH_TOKEN = ""
bot.X_CT0 = ""
assert not bot._has_x_cookie(), "test harus offline"

SENT, DOCS = [], []
DM_OK = {"ok": True}


async def fake_send(chat_id, text, topic_id=None, parse_mode=None, attempts=None):
    SENT.append({"chat": chat_id, "topic": topic_id, "text": text})
    return {"ok": True}


async def fake_send_document(chat_id, topic_id, filename, body, caption=None, parse_mode=None):
    DOCS.append({"chat": chat_id, "topic": topic_id, "file": filename,
                 "caption": caption, "body": body, "ok": DM_OK["ok"]})
    return DM_OK["ok"], False


bot.send = fake_send
bot.send_document = fake_send_document

DMS = [5650021727, 5318526305]
NOW = int(datetime.now(timezone.utc).timestamp() * 1000)


def make_pending(n_posts=6, session_id="test-1"):
    entries = [{"link": f"https://x.com/h{i}/status/{100 + i}", "who": f"@tg{i}", "uid": 500 + i,
                "exempt": False, "atMs": NOW, "messageId": 100 + i} for i in range(n_posts)]
    return {"topicId": bot.GROUPS["g3"]["tid"], "chatId": bot.GROUPS["g3"]["cid"],
            "sessionName": "Sesi 3", "sessionLabel": "Sesi 3 | 14:00-14:10 UTC",
            "closedAt": NOW, "checkAt": NOW - 1000, "reportAt": NOW - 1000,
            "sessionId": session_id, "entries": entries,
            "participants": [{"uid": 500 + i, "who": f"@tg{i}", "username": f"tg{i}"} for i in range(n_posts)],
            "adminUids": [], "mpost": {}, "fetchCache": {}}


def fill_ok(pending):
    cache = bot._fetch_cache(pending)
    targets = bot._pick_check_entries(pending["entries"])
    pending["sampleTweetIds"] = [targets[0]["tweetId"]]
    others = [t["handle"] for t in targets if t["handle"] != targets[0]["handle"]]
    cache[targets[0]["tweetId"]] = {"state": "ok", "attempts": 1, "nextAt": 0,
                                     "commenters": sorted(others), "reason": "", "at": NOW, "pages": 3}


def clear_pending():
    with open(bot.PENDING_PATH, "w", encoding="utf-8") as f:
        f.write('{"sessions": []}')


def dm_docs():
    return [d for d in DOCS if d["chat"] in DMS]


def group_docs():
    return [d for d in DOCS if d["chat"] not in DMS]


async def main():
    print("=== 1. Laporan HANYA masuk DM, tidak pernah ke topic ===")
    clear_pending()
    p = make_pending()
    fill_ok(p)
    bot._save_pending_check(p)
    SENT.clear(); DOCS.clear()
    await bot.do_check_g3()
    assert dm_docs(), "file harus masuk DM"
    assert not group_docs(), f"tidak boleh ada kiriman ke grup/topic: {group_docs()}"
    assert all(d["topic"] is None for d in dm_docs()), "DM tidak boleh punya topic"
    assert not bot._read_pending_records(), "pending harus bersih setelah sukses"
    print(f"  [OK] file ke {sorted({d['chat'] for d in dm_docs()})}, 0 ke topic, pending bersih")
    assert not hasattr(bot, "CHECKER_REPORT_TOPIC"), "variabel CHECKER_REPORT_TOPIC harus dihapus"

    print("\n=== 2. DM gagal -> pending disimpan, dicoba lagi ===")
    clear_pending()
    p = make_pending()
    fill_ok(p)
    bot._save_pending_check(p)
    DM_OK["ok"] = False
    SENT.clear(); DOCS.clear()
    await bot.do_check_g3()
    pend = bot._read_pending_records()
    assert pend, "pending harus disimpan"
    assert int(pend[0].get("deliveryAttempts") or 0) >= 1, "percobaan harus dihitung"
    assert int(pend[0]["retryAt"]) > NOW, "retry harus dijadwalkan"
    print(f"  [OK] attempts={pend[0]['deliveryAttempts']}, retry dijadwal")

    print("\n=== 3. Setelah MAX percobaan -> backoff panjang, tetap disimpan ===")
    p = pend[0]
    p["deliveryAttempts"] = bot.CHECKER_MAX_DELIVERY_ATTEMPTS
    p["retryAt"] = 0
    bot._save_pending_check(p)
    await bot.do_check_g3()
    p2 = bot._read_pending_records()[0]
    wait_ms = int(p2["retryAt"]) - NOW
    assert wait_ms >= 29 * 60 * 1000, f"retry harus ~30 menit, dapat {wait_ms}ms"
    assert bot._read_pending_records(), "pending tidak boleh hilang"
    print(f"  [OK] backoff {round(wait_ms/60000)} menit, pending tersimpan")

    print("\n=== 4. DM 403 -> TETAP dicoba lagi (tidak di-blacklist) ===")
    clear_pending()
    DM_OK["ok"] = True
    p = make_pending(session_id="test-403a")
    fill_ok(p)
    bot._save_pending_check(p)
    DOCS.clear()
    await bot.do_check_g3()
    first = len(dm_docs())
    clear_pending()
    p = make_pending(session_id="test-403b")
    fill_ok(p)
    bot._save_pending_check(p)
    DM_OK["ok"] = False          # simulasi 403
    DOCS.clear()
    await bot.do_check_g3()
    second = len(dm_docs())
    assert second == len(DMS), f"harus tetap mencoba semua DM, dapat {second}"
    assert [r for r in bot._read_pending_records() if r["sessionId"] == "test-403b"], "pending harus disimpan"
    print(f"  [OK] percobaan 1: {first} file, percobaan 2 (DM 403): {second} file -> tetap mencoba")

    print("\n=== 5. Semua post 429 -> 0 tuduhan, tetap terkirim ===")
    clear_pending()
    DM_OK["ok"] = True
    p = make_pending(session_id="test-429")
    targets = bot._pick_check_entries(p["entries"])
    p["sampleTweetIds"] = [targets[0]["tweetId"]]
    cache = bot._fetch_cache(p)
    for t in targets:
        cache[t["tweetId"]] = {"state": "unreadable", "attempts": 2, "nextAt": 0, "commenters": [],
                               "reason": "rate limit X (HTTP 429)", "at": NOW, "pages": 0}
    bot._save_pending_check(p)
    SENT.clear(); DOCS.clear()
    await bot.do_check_g3()
    assert dm_docs(), "laporan tetap harus terkirim walau post tidak terbaca"
    import re
    body = dm_docs()[0]["body"]
    assert not [l for l in body.splitlines() if re.fullmatch(r"\d+\. .+", l)], "tidak boleh ada tuduhan"
    print("  [OK] terkirim, 0 nama tuduhan")

    print("\n=== 6. admin/VIP/protected tidak pernah masuk daftar ===")
    clear_pending()
    p = make_pending(session_id="test-immune")
    fill_ok(p)
    bot.PROTECTED_IDS.add(500)
    bot.VIP_UIDS = {501, 502}
    p["adminUids"] = ["503"]
    bot._save_pending_check(p)
    DOCS.clear()
    await bot.do_check_g3()
    a = bot._analyze_g3(p)
    assert a["immune"] == 4, f"harus 4 kebal, dapat {a['immune']}"
    listed = "\n".join(dm_docs()[0]["body"].splitlines())
    for who in ("@tg0", "@tg1", "@tg2", "@tg3"):
        assert who not in listed, f"{who} kebal tapi masuk daftar"
    print("  [OK] 4 kebal dikeluarkan")

    print("\n=== 7. Format file persis sesuai contoh ===")
    body = dm_docs()[0]["body"]
    ls = body.splitlines()
    assert ls[0].startswith("Defaulters: "), ls[0]
    assert ls[1].startswith("Check time: "), ls[1]
    assert ls[2] == "", repr(ls[2])
    import re
    for l in ls:
        if re.fullmatch(r"\d+\. .+", l):
            name = l.split(". ", 1)[1].replace(" (cek manual)", "")
            assert name.startswith("@") or name.startswith("uid") or name[0].isupper(), l
    assert "Proof link for example:" in ls
    i = ls.index("Proof link for example:")
    assert re.fullmatch(r"https://x\.com/[A-Za-z0-9_]+/status/\d+", ls[i + 1]), ls[i + 1]
    assert i + 1 == len(ls) - 1, "proof link harus baris terakhir"
    print("  [OK] judul, waktu, daftar bernomor, 1 proof link")

    print("\n=== 8. Tidak ada handle X di laporan ===")
    handles = {t["handle"] for t in bot._pick_check_entries(p["entries"])}
    for l in ls:
        if l.startswith("http"):
            continue
        for h in handles:
            assert h not in l, f"handle X bocor: {h} di {l!r}"
    print("  [OK] hanya username Telegram")

    print("\n=== 9. Tanpa cookie X -> tetap terkirim ===")
    clear_pending()
    p = make_pending(session_id="test-nocookie")
    bot._save_pending_check(p)
    DOCS.clear()
    await bot.do_check_g3()
    assert dm_docs(), "tanpa cookie laporan tetap terkirim"
    print("  [OK] terkirim")

    print("\nSEMUA UJI PENGIRIMAN (DM ONLY) LULUS")
    return True


sys.exit(0 if asyncio.run(main()) else 1)
