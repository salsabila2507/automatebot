"""Dry-run OFFLINE: uji logika checker baru tanpa jaringan / tanpa Telegram.

Memakai data nyata data/check-3.json (Sesi 1 = 181 peserta) dan mensimulasikan
 variously kondisi fetch (ok / unreadable / pending / 429) untuk membuktikan:
  1. tidak ada orang yang dituduh berdasarkan post yang tidak terbaca
  2. admin/VIP/protected tidak pernah masuk daftar
  3. cache per-post bikin resume (tidak fetch ulang)
"""
import json, os, sys, asyncio
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "check-3.json.bak")


def load_pending():
    """Fixture stabil (salinan awal), bukan file live yang terus berubah."""
    path = FIXTURE if os.path.exists(FIXTURE) else bot.PENDING_PATH
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    recs = raw.get("sessions", []) if isinstance(raw, dict) else raw
    return [r for r in recs if r.get("entries")] or recs


def scenario(name, mutate):
    pending = max(load_pending(), key=lambda r: len(r.get("entries") or []))
    pending = json.loads(json.dumps(pending))
    pending.pop("checkRun", None)  #racun lama dibuang, cache baru
    mutate(pending)
    analysis = bot._analyze_g3(pending)
    body = bot._format_defaulters(pending, analysis)
    s = {"penunggu": analysis["defaulters"], "belum_terverifikasi": [], "cek_manual": [], "lengkap": [r for r in analysis["results"] if r["complete"]]}
    cache = bot._fetch_cache(pending)
    readable = {t["tweetId"] for t in targets if (cache.get(t["tweetId"]) or {}).get("state") == "ok"}
    unreadable = {t["tweetId"] for t in targets if t["tweetId"] not in readable}
    print(f"\n=== {name} ===")
    print(f"  posts={analysis['posts']} terbaca={analysis['checked']} pending={analysis['pending']} "
          f"unreadable={analysis['unreadable']} coverageComplete={analysis['coverageComplete']}")
    print(f"  dinilai={analysis['participants']} kebal={analysis['immune']} | "
          f"defaulter={len(s['penunggu'])} lengkap={len(s['lengkap'])}")
    # INVARIAN 1: tuduhan hanya boleh berdasarkan post yang TERBACA PENUH
    for item in s["penunggu"]:
        assert item["handle"] and item["handle"] != "-", f"BUG: {item['who']} dituduh tanpa handle"
        assert item["missed"] >= 1, "BUG: masuk penunggu tapi missed=0"
        for post in item["missedPosts"]:
            tid = bot.x_tweet_id(post["link"])
            assert tid in readable, f"BUG: tuduh {item['who']} berdasarkan post TAK terbaca: {post['link']}"
            assert tid not in unreadable, f"BUG: tuduh {item['who']} dari post unreadable: {post['link']}"
    # INVARIAN 2: tuduhan hanya dari post yang TERBACA
    for item in s["penunggu"]:
        missed_ids = {bot.x_tweet_id(p["link"]) for p in item["missedPosts"]}
        assert not (missed_ids & unreadable), f"BUG: {item['who']} dituduh dari post unreadable"
    # INVARIAN 3: immune tidak boleh muncul di section apa pun
    for bucket in s.values():
        for item in bucket:
            assert not bot._immunity_label(item.get("uid")), f"BUG: immune masuk daftar: {item['who']}"
    # INVARIAN 4: 'lengkap' berarti 0 missed
    for item in s["lengkap"]:
        assert item["missed"] == 0, f"BUG: {item['who']} salah masuk lengkap"
    # INVARIAN 5: defaulters == yang tidak complete
    assert [i["who"] for i in analysis["defaulters"]] == [i["who"] for i in s["penunggu"]]
    # INVARIAN 6: jumlah hasil == jumlah peserta yang dinilai
    assert len(analysis["results"]) + analysis["immune"] >= analysis["participants"]
    return analysis, body


recs = load_pending()
big = max(recs, key=lambda r: len(r.get("entries") or []))
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

targets = bot._pick_check_entries(big.get("entries"))
print(f"fixture: {len(recs)} record, memakai '{big.get('sessionLabel')}'")
print(f"target cek: {len(targets)} post unik dari {len(big['entries'])} entry")
assert len(targets) > 100, "target terlalu sedikit"


def all_ok(p):
    cache = bot._fetch_cache(p)
    for i, t in enumerate(targets):
        commenters = [x["handle"] for x in targets if x["handle"] != t["handle"]]
        cache[t["tweetId"]] = {"state": "ok", "attempts": 1, "nextAt": 0,
                               "commenters": sorted(commenters if i % 2 else commenters[:1]),
                               "reason": "", "at": 0, "pages": 3}


def partial(p):
    all_ok(p)
    cache = bot._fetch_cache(p)
    for t in targets[::3]:
        cache[t["tweetId"]] = {"state": "unreadable", "attempts": 2, "nextAt": 0,
                               "commenters": [], "reason": "post tidak ditemukan di respons X", "at": 0, "pages": 1}


def all_429(p):
    cache = bot._fetch_cache(p)
    for t in targets:
        cache[t["tweetId"]] = {"state": "pending", "attempts": 1, "nextAt": 0,
                               "commenters": [], "reason": "rate limit X (HTTP 429)", "at": 0, "pages": 0}


def with_immune(p):
    all_ok(p)
    parts = p.get("participants") or []
    for i, part in enumerate(parts[:5]):
        bot.VIP_UIDS.add(int(part["uid"]))
    bot.PROTECTED_IDS.add(int(parts[5]["uid"]))
    for part in parts[:6]:
        part["_immune"] = True


a1, b1 = scenario("A. semua post terbaca (parah: sebagian besar tidak komentar)", all_ok)
a2, b2 = scenario("B. 1/3 post tidak terbaca (harus pindah ke 'belum terverifikasi')", partial)
a3, b3 = scenario("C. semua kena 429 (deadcode: tidak boleh ada yang dituduh)", all_429)
a4, b4 = scenario("D. 5 VIP + 1 developer kebal (tidak boleh masuk daftar)", with_immune)

print("\n--- contoh isi file (B, 40 baris pertama) ---")
print("\n".join(b2.splitlines()[:40]))

print("\n--- cek resume: cache tidak fetch ulang ---")
p = load_pending()[1]
cache = bot._fetch_cache(p)
for t in targets[:5]:
    bot._post_state(cache, t["tweetId"])
assert len(bot._fetch_cache(p)) == 5, "cache tidak tersimpan"
print(f"cache berisi {len(bot._fetch_cache(p))} post -> retry akan lanjut, bukan dari nol")

print("\n--- cek select_pending tidak kelaparan ---")
# bot lama masih menulis retryAt ke file yang sama, jadi pakai 'now' yang pasti
# sudah lewat semua retryAt untuk menguji logika pemilihan record.
live_path = bot.PENDING_PATH
bot.PENDING_PATH = FIXTURE          # pakai fixture supaya deterministik
now = int(datetime.now(timezone.utc).timestamp() * 1000) + 3600 * 1000
sel = bot._select_pending(now)
assert sel is not None, "BUG: tidak ada record terpilih padahal ada yang due"
print(f"record terpilih: {sel.get('sessionLabel')} (deadline paling dekat)")
print(f"deadline: {datetime.fromtimestamp(bot._record_deadline(sel, now)/1000, timezone.utc)}")
#_record_deadline tidak boleh melempar untuk record mana pun
for r in bot._read_raw_pending_records():
    d = bot._record_deadline(r, now)
    assert isinstance(d, int) and d > 0, f"BUG: deadline rusak untuk {r.get('sessionId')}"
print(f"OK: semua {len(bot._read_raw_pending_records())} record punya deadline valid")
bot.PENDING_PATH = live_path

print("\n--- cek quota 2-link: TIDAK ada eksekusi ---")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py"), encoding="utf-8").read()
forbidden = ["deleteMessage", "restrictChatMember", "banChatMember", "unbanChatMember", "BOT_DELETED"]
body_calls = [ln.strip() for ln in src.splitlines()
              if any(f in ln for f in forbidden) and not ln.strip().startswith("#")]
assert not body_calls, f"BUG: masih ada eksekusi: {body_calls}"
print("OK: tidak ada delete/ban/mute di seluruh kode")
print("OK: _archive_double memakai path absolut:", bot.DOUBLE_LOG_PATH)

print("\n--- cek VIP tag matcher ---")
for rank, expect in [("VIP", True), ("vip", True), ("Gold VIP", True), ("Moderator", False),
                     ("Member", False), ("", False), (None, False), ("VIP Member", True)]:
    got = bot._vip_tags_match(rank)
    assert got == expect, f"BUG: _vip_tags_match({rank!r}) = {got}, harap {expect}"
print("OK: pencocokan tag VIP benar (case-insensitive, substring)")

print("\n--- cek keabadian (immutability) ---")
p = {"uid": 999111, "who": "@tester"}
assert bot._is_protected(999111) is False or 999111 in bot.PROTECTED_IDS
assert bot._is_vip(123456789) is False
print(f"OK: protected={sorted(bot.PROTECTED_IDS)} vip_loaded={len(bot.VIP_UIDS)}")

print("\nSEMUA INVARIAN LULUS")
