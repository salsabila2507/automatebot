"""Test call site _checker_fetch_slice (bot.py:1222-1238).

Robot ini yang sebelumnya crash: work() memakai `state` yang sebvernya lokal
dan belum di-assign, padahal argumennya sudah tersedia sebagai `cached_state`.
Semua path di sini diarahkan ke temp dir, tidak ada panggilan X sungguhan.
"""
import asyncio
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="dryrun_slice_")
os.environ["BOT_DATA_DIR"] = TMP
os.environ["CHECKER_DELAY_MIN"] = "0"
os.environ["CHECKER_DELAY_MAX"] = "0"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot
assert bot.PENDING_PATH.startswith(TMP), ("TEST BAHAYA: PENDING_PATH bukan temp!", bot.PENDING_PATH)

SAVED = []


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, *a, **k):
        raise AssertionError("test ini tidak boleh memanggil X sungguhan")


SEEN = []


async def fake_fetch(session, tweet_id, handle, resume=None, **kw):
    SEEN.append({"tweetId": tweet_id, "handle": handle, "resume": resume})
    return {"verified": True, "complete": True, "commenters": ["@a", "@b"],
            "pages": 3, "reason": ""}


bot._fetch_x_replies_robust = fake_fetch
bot.aiohttp.ClientSession = lambda *a, **k: FakeSession()
bot._save_pending_check = lambda p: SAVED.append(json.dumps(p)[:0] or "saved")

import json  # noqa: E402  (dipakai oleh lambda _save_pending_check)


def pending_with(resume):
    cache = {}
    if resume is not None:
        cache["111"] = {"state": bot.POST_PENDING, "attempts": 1, "nextAt": 0,
                        "commenters": [], "reason": "", "at": 0, "pages": 1,
                        "progress": resume}
    return {"sessionId": "S1", "sessionLabel": "Sesi T", "entries": [
        {"link": "https://x.com/handle_x/status/111", "who": "@u", "uid": 5}],
        "fetchCache": cache}


# 1. post baru: tidak ada resume, tidak boleh crash
SEEN.clear()
p = pending_with(None)
fetched, failed, wake = asyncio.run(bot._checker_fetch_slice(p, 10 ** 12, 60))
assert fetched == 1, (fetched, failed, wake)
assert failed == 0, (fetched, failed)
assert SEEN[0]["resume"] is None, SEEN
print("OK 1: post baru terbaca, resume=None, tidak crash")

# 2. resume yang tersimpan HARUS diteruskan ke fetcher (ini yang dulu rusak)
resume = {"commenters": ["@a"], "cursor": "CUR123", "pages": 1, "unresolved": 0}
SEEN.clear()
p = pending_with(resume)
fetched, failed, wake = asyncio.run(bot._checker_fetch_slice(p, 10 ** 12, 60))
assert fetched == 1, (fetched, failed, wake)
assert SEEN[0]["resume"] == resume, SEEN
print("OK 2: progress tersimpan diteruskan ke fetcher:", SEEN[0]["resume"])

# 3. progres jadi POST_OK + komentar terkumpul
st = p["fetchCache"]["111"]
assert st["state"] == bot.POST_OK, st
assert st["commenters"] == ["@a", "@b"], st
assert st["pages"] == 3, st
print("OK 3: state=ok commenters=%s pages=%s" % (st["commenters"], st["pages"]))

# 4. post yang sudah ok tidak di-fetch ulang
SEEN.clear()
fetched, failed, wake = asyncio.run(bot._checker_fetch_slice(p, 10 ** 12, 60))
assert fetched == 0 and SEEN == [], (fetched, SEEN)
print("OK 4: post yang sudah ok tidak di-fetch ulang")

# 5. CHECKER_SAMPLE_POSTS=1: hanya 1 post patokan per sesi, post lain TIDAK
#    ikut dibaca. Ini inti aturan "1 random post sebagai patokan".
assert bot.CHECKER_SAMPLE_POSTS == 1, bot.CHECKER_SAMPLE_POSTS
def pending_two():
    p = pending_with(None)
    p["entries"].append({"link": "https://x.com/handle_y/status/222",
                         "who": "@v", "uid": 6})
    return p

SEEN.clear()
p = pending_two()
fetched, failed, wake = asyncio.run(bot._checker_fetch_slice(p, 10 ** 12, 60))
assert fetched == 1, (fetched, failed)
assert len(SEEN) == 1, SEEN
assert len(p["fetchCache"]) == 1, p["fetchCache"]
print("OK 5: dari 2 post hanya 1 yang disampling ->", SEEN[0]["tweetId"], "(1 patokan per sesi)")

# 6. pending disimpan setiap post selesai
assert SAVED, "pending tidak disimpan"
print("OK 6: pending disimpan %s kali" % len(SAVED))

# 7. file produksi tidak berubah (dicek dari dalam test, bukan sesudahnya)
prod = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "check-3.json")
if os.path.exists(prod):
    before = (os.path.getmtime(prod), os.path.getsize(prod))
    SEEN.clear()
    asyncio.run(bot._checker_fetch_slice(pending_two(), 10 ** 12, 60))
    assert (os.path.getmtime(prod), os.path.getsize(prod)) == before, "file produksi berubah!"
    print("OK 7: data/check-3.json produksi tidak berubah (mtime + ukuran)")
else:
    print("OK 7: tidak ada file produksi untuk dibandingkan")

print("LULUS: dryrun_slice 7/7")
