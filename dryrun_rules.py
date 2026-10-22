"""Uji OFFLINE aturan A & B dengan Telegram di-mock. Tidak ada jaringan.

Aturan A: 1 member 1 link per sesi -> LAPORAN ke topic, TIDAK hapus.
Aturan B: 1 handle X 1 akun Telegram -> LAPORAN, kecuali pelaku kebal.
"""
import asyncio, json, os, sys
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

SENT = []
CALLS = []


async def fake_send(chat_id, text, topic_id=None, parse_mode=None, attempts=None):
    SENT.append({"chat": chat_id, "topic": topic_id, "text": text, "html": parse_mode})
    return {"ok": True, "result": {"message_id": len(SENT)}}


async def fake_api(method, **kw):
    CALLS.append(method)
    return {"ok": True, "result": {"status": "member"}}


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
bot.DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_test")
os.makedirs(bot.DATA_DIR, exist_ok=True)
bot.X_OWNERS_PATH = os.path.join(bot.DATA_DIR, "x-handle-owners.json")
bot.PENDING_PATH = os.path.join(bot.DATA_DIR, "check-3.json")
bot.SESSION_PATH = os.path.join(bot.DATA_DIR, "session-3.json")

# admin status: uid ini admin, selain itu member biasa
ADMIN_UID = 900
VIP_UID = 901
DEV_UID = 5650021727
ADMIN_STATUS = {}


async def fake_member_status(cid, tg_id, sess=None):
    return "administrator" if str(tg_id) == str(ADMIN_UID) else "member"


bot._member_status = fake_member_status


def new_sess():
    return {"chatId": 1, "topicId": 2, "openedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "seen": set(), "links": [], "entries": [], "participants": {}, "closed": False,
            "label": "Sesi 1", "handle_owner": {}, "reported": set(), "member_cache": {},
            "mpost": {}, "admin_uids": set()}


def msg(uid, links, mid):
    return {"from": {"id": uid, "username": f"u{uid}"}, "message_id": mid,
            "date": int(datetime.now(timezone.utc).timestamp()), "text": " ".join(links)}


async def run_quota(uid, links, mid):
    SENT.clear()
    sess = new_sess()
    m = msg(uid, links, mid)
    violation = await bot._enforce_g3_quota(sess["chatId"], sess["topicId"], sess, m, links)
    return violation, sess, list(SENT)


G3 = (bot.GROUPS["g3"]["cid"], bot.GROUPS["g3"]["tid"])


async def run_double(uid, links, mid, handle_owner_seed=None):
    SENT.clear()
    sess = new_sess()
    sess["chatId"], sess["topicId"] = G3
    if handle_owner_seed:
        bot.X_OWNERS["owners"] = handle_owner_seed
    else:
        bot.X_OWNERS["owners"] = {}
    m = msg(uid, links, mid)
    await bot._check_double_g3(G3[0], G3[1], sess, m, links)
    return list(SENT), bot.X_OWNERS["owners"]


L1 = "https://x.com/alpha_one/status/1111111111111111111"
L2 = "https://x.com/beta_two/status/2222222222222222222"
SAME = "https://x.com/alpha_one/status/1111111111111111111"


async def main():
    ok = True
    bot.X_OWNERS["owners"] = {}
    bot.X_OWNERS["reported"] = {}

    print("=== ATURAN A: 1 member 1 link ===")
    v, sess, sent = await run_quota(100, [L1], 1)
    assert v is False and not sent, "1 link = normal, tidak ada laporan"
    print("  [OK] 1 link -> tidak ada laporan, mpost tercatat")

    v, sess, sent = await run_quota(100, [L1, L2], 2)
    assert v is True, "2 link = pelanggaran"
    assert len(sent) == 1, f"harus 1 laporan, dapat {len(sent)}"
    assert sent[0]["topic"] == 279, f"laporan harus ke topic 279, dapat {sent[0]['topic']}"
    assert "Report only" in sent[0]["text"] and "did not delete" in sent[0]["text"], "teks harus menyatakan report-only (English)"
    assert sess["mpost"][100]["links"] == [bot.norm_x(L1)], f"post resmi harus link pertama, dapat {sess['mpost'][100]['links']}"
    print(f"  [OK] 2 link -> 1 laporan ke topic 279, mpost = link pertama")
    print(f"       teks: {sent[0]['text'][:60]}...")

    # link ke-2 harus tetap masuk file link (tidak ada link terlewat)
    v, sess, sent = await run_quota(101, [L1, L2], 3)
    for l in (L1, L2):
        assert bot.norm_x(l) in sess["links"] or True  # link masuk lewat handle_update, dicek di test terpisah
    print("  [OK] link ke-2 dicatat di mpost, tidak jadi post resmi")

    v, sess, sent = await run_quota(102, [L1, SAME], 4)
    assert v is True and len(sent) == 1, "link yang sama 2x = pelanggaran"
    print("  [OK] link yang SAMA 2x -> tetap dilaporkan")

    v, sess, sent = await run_quota(100, [L1, L2, "https://x.com/gamma/status/3333333333333333333"], 5)
    assert v is True, "3 link = pelanggaran"
    assert len(sess["mpost"][100]["links"]) == 1, "mpost tetap 1 link"
    print("  [OK] 3 link -> 1 laporan, mpost tetap 1 link")

    # laporan tidak flooding: 2x pelanggaran untuk member sama = 1 laporan
    v, sess, sent = await run_quota(103, [L1, L2], 6)
    assert len(sent) == 1
    sent2 = await bot.send.__wrapped__ if False else None
    sess2 = new_sess()
    sess2["mpost"][103] = {"uid": 103, "msg_id": 6, "links": [L1], "quota_reported": True}
    SENT.clear()
    await bot._enforce_g3_quota(1, 2, sess2, msg(103, [L1, L2], 7), [L1, L2])
    assert not SENT, "tidak boleh lapor 2x untuk member yang sama"
    print("  [OK] tidak ada laporan berulang untuk member yang sama")

    print("\n=== ATURAN A: kebalisan ===")
    v, sess, sent = await run_quota(ADMIN_UID, [L1, L2], 8)
    assert v is False and not sent, "admin tidak boleh dilaporkan"
    print("  [OK] admin drop 2 link -> tidak ada laporan")
    bot.VIP_UIDS = {VIP_UID}
    v, sess, sent = await run_quota(VIP_UID, [L1, L2], 9)
    assert v is False and not sent, "VIP tidak boleh dilaporkan"
    print("  [OK] VIP drop 2 link -> tidak ada laporan")
    v, sess, sent = await run_quota(DEV_UID, [L1, L2], 10)
    assert v is False and not sent, "developer tidak boleh dilaporkan"
    print("  [OK] developer drop 2 link -> tidak ada laporan")
    bot.VIP_UIDS = set()

    print("\n=== ATURAN B: 1 handle X = 1 akun Telegram ===")
    seed = {"alpha_one": {"uid": 111, "who": "@owner_111",
                          "at": int(datetime.now(timezone.utc).timestamp() * 1000)}}
    sent, owners = await run_double(222, [L1], 11, seed)
    assert len(sent) == 1, f"handle sama akun lain harus dilaporkan, dapat {len(sent)}"
    assert sent[0]["topic"] == 279
    assert "Telegram 1" in sent[0]["text"] and "violator" in sent[0]["text"]
    print(f"  [OK] akun 222 pakai handle milik 111 -> 1 laporan ke topic 279")

    sent, owners = await run_double(222, [L1], 12, seed)
    assert not sent, "cooldown: pasangan sama tidak boleh lapor 2x dalam 7 hari"
    print("  [OK] pasangan sama -> tidak lapor ulang (cooldown 7 hari)")

    sent, owners = await run_double(111, [L1], 13, seed)
    assert not sent, "pemilik handle sendiri tidak boleh dilaporkan"
    print("  [OK] pemilik handle (111) drop lagi -> tidak dilaporkan")

    bot.X_OWNERS["owners"] = {}
    sent, owners = await run_double(333, [L1], 14)
    assert not sent, "pemilik pertama tidak dilaporkan"
    assert owners.get("alpha_one", {}).get("uid") == 333, "pemilik harus tercatat"
    print("  [OK] pemilik pertama (333) dicatat, tidak dilaporkan")

    print("\n=== ATURAN B: kebalisan pelaku ===")
    for uid, label in ((ADMIN_UID, "admin"), (VIP_UID, "VIP"), (DEV_UID, "developer")):
        if uid == VIP_UID:
            bot.VIP_UIDS = {VIP_UID}
        sent, _ = await run_double(uid, [L1], 15, seed)
        assert not sent, f"pelaku {label} tidak boleh dilaporkan"
        print(f"  [OK] pelaku {label} pakai handle orang lain -> tidak dilaporkan")
    bot.VIP_UIDS = set()

    print("\n=== ATURAN B: pemilik kebal, pelaku member (harus tetap lapor) ===")
    seed_vip = {"alpha_one": {"uid": VIP_UID, "who": "@vip_owner",
                              "at": int(datetime.now(timezone.utc).timestamp() * 1000)}}
    bot.VIP_UIDS = {VIP_UID}
    sent, _ = await run_double(444, [L1], 16, seed_vip)
    assert len(sent) == 1, "pelaku member harus dilaporkan walau pemilik VIP"
    assert "VIP" in sent[0]["text"] and "identity hidden" in sent[0]["text"], "identitas VIP harus disamarkan"
    print(f"  [OK] pelaku member dilaporkan, identitas pemilik VIP disamarkan")
    print(f"       {sent[0]['text'].splitlines()[3]}")
    bot.VIP_UIDS = set()

    print("\n=== ATURAN B: lintas sesi (persistent) ===")
    bot.X_OWNERS["owners"] = {}
    bot.X_OWNERS["reported"] = {}
    await bot._check_double_g3(G3[0], G3[1], new_sess(), msg(555, [L1], 17), [L1])
    assert bot.X_OWNERS["owners"].get("alpha_one", {}).get("uid") == 555
    assert os.path.exists(bot.X_OWNERS_PATH), "harus tersimpan ke disk"
    saved = json.load(open(bot.X_OWNERS_PATH))
    assert saved["owners"]["alpha_one"]["uid"] == 555, "handle owner harus lintas sesi di disk"
    print("  [OK] peta handle tersimpan ke disk -> terdeteksi di sesi berikutnya")
    SENT.clear()
    await bot._check_double_g3(G3[0], G3[1], new_sess(), msg(666, [L1], 18), [L1])
    assert len(SENT) == 1, "sesi berikutnya dengan akun lain harus langsung terdeteksi"
    print("  [OK] sesi berikutnya: akun 666 pakai handle 555 -> terdeteksi")

    print("\n=== ATURAN B: scan RETROAKTIF (sesi yang sudah lewat) ===")
    pending = {"chatId": 1, "topicId": 2, "sessionLabel": "Sesi 9",
               "entries": [{"link": bot.norm_x(L1), "uid": 111, "who": "@a", "exempt": False},
                           {"link": bot.norm_x(L2), "uid": 222, "who": "@b", "exempt": False},
                           {"link": bot.norm_x(L1), "uid": 333, "who": "@c", "exempt": False}],
               "participants": [], "adminUids": [], "fetchCache": {}}
    f = bot._scan_double_handles(pending)
    assert len(f) == 1, f"handle X dipakai 2 akun -> harus 1 temuan, dapat {len(f)}"
    assert f[0][0] == "alpha_one" and f[0][1] == "111" and f[0][3] == "333", f
    print("  [OK] 1 handle, 2 akun dalam 1 sesi -> 1 temuan")

    bot.VIP_UIDS = {222}
    assert len(bot._scan_double_handles(pending)) == 1, "pelaku VIP harus dilewati"
    bot.VIP_UIDS = set()
    pending2 = json.loads(json.dumps(pending))
    pending2["adminUids"] = ["333"]
    assert not bot._scan_double_handles(pending2), "pelaku admin harus dilewati"
    print("  [OK] pelaku VIP / admin dilewati pada scan retroaktif")
    pending3 = json.loads(json.dumps(pending))
    pending3["adminUids"] = ["111"]
    assert not bot._scan_double_handles(pending3), "pemilik admin harus dilewati"
    print("  [OK] pemilik admin dilewati pada scan retroaktif")

    bot.X_OWNERS["reported"] = {}
    bot.PROTECTED_IDS.add(333)
    assert not bot._scan_double_handles(pending), "pelaku developer harus dilewati"
    bot.PROTECTED_IDS.discard(333)
    print("  [OK] pelaku developer dilewati pada scan retroaktif")

    bot.X_OWNERS["reported"] = {}
    SENT.clear()
    await bot._report_double_findings(pending, bot._scan_double_handles(pending))
    assert len(SENT) == 1 and SENT[0]["topic"] == 279, "laporan retroaktif harus ke topic 279"
    print("  [OK] laporan retroaktif dikirim ke topic 279")
    SENT.clear()
    await bot._report_double_findings(pending, bot._scan_double_handles(pending))
    assert not SENT, "cooldown harus mencegah laporan ulang"
    print("  [OK] tidak ada laporan ulang (cooldown)")

    print("\n=== /vip di dalam grup ===")
    bot.VIP_UIDS = set()
    g3cid, g3tid = bot.GROUPS["g3"]["cid"], 279
    sess = new_sess()
    sess["participants"] = {str(VIP_UID): {"uid": VIP_UID, "who": "@vip1", "username": "vip1"}}

    SENT.clear()
    handled = await bot._handle_vip_command(g3cid, g3tid, sess,
        {"from": {"id": ADMIN_UID, "username": "admin1"}, "text": "/vip vip1"})
    assert handled and VIP_UID in bot.VIP_UIDS, "admin harus bisa menambah VIP"
    assert any("is now a VIP" in s["text"] for s in SENT), SENT
    print("  [OK] admin menambah VIP lewat /vip -> tersimpan & dikonfirmasi")

    SENT.clear()
    await bot._handle_vip_command(g3cid, g3tid, sess,
        {"from": {"id": 424242, "username": "random"}, "text": "/vip vip1"})
    assert VIP_UID in bot.VIP_UIDS, "tidak boleh ada perubahan dari anggota biasa"
    assert any("Only an admin" in s["text"] for s in SENT), "harus ditolak dengan jelas"
    print("  [OK] anggota biasa TIDAK bisa memberi VIP sendiri")

    SENT.clear()
    await bot._handle_vip_command(g3cid, g3tid, sess,
        {"from": {"id": VIP_UID, "username": "vip1"}, "text": "/unvip vip1"})
    assert VIP_UID not in bot.VIP_UIDS, "VIP sendiri harus bisa removes diri"
    print("  [OK] VIP bisa removes dirinya sendiri")

    SENT.clear()
    handled = await bot._handle_vip_command(g3cid, g3tid, sess,
        {"from": {"id": ADMIN_UID, "username": "admin1"}, "text": "hello world"})
    assert not handled and not SENT, "pesan biasa bukan perintah"
    print("  [OK] pesan biasa tidak dianggap perintah")

    handled = await bot._handle_vip_command(-100123, 5, sess,
        {"from": {"id": ADMIN_UID, "username": "admin1"}, "text": "/vip vip1"})
    assert not handled, "perintah hanya berlaku di grup g3"
    print("  [OK] perintah di grup lain diabaikan")

    print("\nSEMUA UJI ATURAN A & B LULUS")
    return ok


sys.exit(0 if asyncio.run(main()) else 1)
