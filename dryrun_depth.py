"""Uji OFFLINE kedalaman baca komentar + simpan progres per halaman.

X di-mock penuh, tidak ada jaringan sungguhan.
"""
import asyncio, os, sys
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "0:dryrun")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

_TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_testdata")
os.makedirs(_TEST_DIR, exist_ok=True)
bot.DATA_DIR = _TEST_DIR

TID = "2103717907863654672"
HANDLE = "muriscofficial"
TOTAL_PAGES = 40          # thread dalam = 40 halaman
CT0 = "fake-ct0"
QID = "fake-query-id"

STATE = {"429_at_page": None, "served": [], "cursor_expired": False, "hits": 0}


def make_page(page_no, total_pages, authors_on_page):
    """Bentuk respons X: entries + cursor Bottom (None di halaman terakhir)."""
    entries = []
    if page_no == 1:
        entries.append({"entryId": f"tweet-{TID}", "sortIndex": "0",
                        "content": {"entryType": "TimelineTimelineItem",
                                    "itemContent": {"itemType": "TimelineTweet",
                                                    "tweet_results": {"result": {
                                                        "rest_id": TID,
                                                        "legacy": {"full_text": "post patokan",
                                                                   "in_reply_to_status_id_str": None},
                                                        "core": {"user_results": {"result": {
                                                            "legacy": {"screen_name": HANDLE}}}}}}}}})
    for i, a in enumerate(authors_on_page):
        entries.append({"entryId": f"tweet-{TID}-{page_no}-{i}", "sortIndex": str(i + 1),
                        "content": {"entryType": "TimelineTimelineItem",
                                    "itemContent": {"itemType": "TimelineTweet",
                                                    "tweet_results": {"result": {
                                                        "rest_id": f"{TID}{page_no:02d}{i:02d}",
                                                        "legacy": {"in_reply_to_status_id_str": TID},
                                                        "core": {"user_results": {"result": {
                                                            "legacy": {"screen_name": a}}}}}}}}})
    entry = {"entryId": "cursor-bottom", "content": {"entryType": "TimelineTimelineCursor",
                                                     "value": f"CURSOR-PAGE-{page_no}",
                                                     "cursorType": "Bottom"}}
    if page_no >= total_pages:
        entries = entries  # tanpa cursor -> thread habis
    else:
        entries.append(entry)
    return {"data": {"threaded_conversation": {"instructions": entries}}}


def authors_for(page_no, total_pages, all_authors):
    """Setiap halaman punya 5 penulis; spam ada di halaman paling bawah."""
    start = (page_no - 1) * 5
    page = all_authors[start:start + 5]
    if page_no == total_pages:                      # spam di ekor
        page = page + [f"spam_bott_{k}" for k in range(4)]
    return page


class FakeSession:
    def __init__(self, all_authors, total_pages):
        self.all = all_authors
        self.total = total_pages
        self.served = []
        self.hits = 0

    def _page_from_cursor(self, cursor):
        return int(str(cursor).rsplit("PAGE-", 1)[1])

    def get(self, url, **kw):
        self.hits += 1
        STATE["hits"] += 1
        cur = None
        # cursor ada di dalam variabel variables yang di-percent-encode
        import re as _re
        m = _re.search(r'cursor%22%3A%22([^%]+)%22', url) or _re.search(r'"cursor":"([^"]+)"', url)
        if m:
            cur = m.group(1)
        page_no = 1 if cur is None else self._page_from_cursor(cur) + 1
        self.served.append(page_no)
        resp = self._make(page_no, cur)

        class _Ctx:
            def __init__(self, r):
                self.status = r.status
                self._payload = r.payload
                self.headers = {"Retry-After": "2"}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def json(self, content_type=None):
                return self._payload
        return _Ctx(resp)

    def _make(self, page_no, cur):
        if page_no > self.total:
            if STATE["cursor_expired"]:
                STATE["cursor_expired"] = False
                class R: status = 200; payload = {"data": {"threaded_conversation": {"instructions": []}}}
                return R
            raise AssertionError("halaman di luar jangkauan")
        if STATE["429_at_page"] is not None and page_no == STATE["429_at_page"]:
            class R: status = 429; payload = {}
            return R
        return type("R", (), {"status": 200, "payload": make_page(page_no, self.total,
                                                                 authors_for(page_no, self.total, self.all))})()


async def run(all_authors, total_pages, resume=None):
    s = FakeSession(all_authors, total_pages)
    return await bot._fetch_x_replies_once(s, TID, CT0, QID, 0, HANDLE, resume), s


async def main():
    total_authors = [f"user{i:03d}" for i in range(195)]   # 39 halaman x 5 + 1
    print("=== 1. Baca sampai habis: 40 halaman, spam di ekor ikut terbaca ===")
    res, s = await run(total_authors, TOTAL_PAGES)
    assert res["verified"] is True, res
    assert res["pages"] == TOTAL_PAGES, f"harus {TOTAL_PAGES} halaman, dapat {res['pages']}"
    assert res["complete"] is True, f"harus complete, dapat {res}"
    assert s.served == list(range(1, TOTAL_PAGES + 1)), f"halaman tidak dibaca semua: {s.served}"
    spam = [c for c in res["commenters"] if c.startswith("spam_bott_")]
    assert len(spam) == 4, f"komentar spam di ekor harus ikut terbaca, dapat {len(spam)}"
    assert len(res["commenters"]) == 195 + 4, f"total komentar {len(res['commenters'])}"
    print(f"  [OK] {res['pages']} halaman, {len(res['commenters'])} komentar (4 spam ekor terbaca), complete=True")

    print("\n=== 2. Tidak berhenti walau semua handle cepat ditemukan ===")
    small = [f"u{i}" for i in range(30)]      # 6 halaman x 5 penulis, tiap halaman terisi
    res2, s2 = await run(small, 6)
    assert res2["complete"] is True and res2["pages"] == 6, res2
    assert s2.served == [1, 2, 3, 4, 5, 6], s2.served
    print(f"  [OK] semua handle ada di halaman awal, tetap baca 6 halaman sampai habis")

    print("\n=== 3. 429 di tengah -> progres tersimpan, lanjut dari halaman itu ===")
    STATE["429_at_page"] = 8
    s = FakeSession(total_authors, TOTAL_PAGES)
    first = await bot._fetch_x_replies_once(s, TID, CT0, QID, 0, HANDLE, None)
    assert first.get("rateLimited") is True, first
    prog = first.get("resume")
    assert isinstance(prog, dict) and prog.get("cursor"), f"progres harus tersimpan, dapat {first}"
    assert prog["pages"] == 7, f"progres harus di halaman 7 (sebelum kena 429), dapat {prog['pages']}"
    assert prog["commenters"], "komentar yang sudah terkumpul harus tersimpan"
    STATE["429_at_page"] = None
    s2 = FakeSession(total_authors, TOTAL_PAGES)
    second = await bot._fetch_x_replies_once(s2, TID, CT0, QID, 0, HANDLE, prog)
    assert second["complete"] is True, second
    assert s2.served[0] == 8, f"harus lanjut dari halaman 8, mulai dari {s2.served[0]}"
    assert 1 not in s2.served, "tidak boleh ulang ke halaman 1"
    assert len(second["commenters"]) == 195 + 4, f"komentar akhir tidak lengkap: {len(second['commenters'])}"
    print(f"  [OK] halaman {s2.served[0]}..{s2.served[-1]} (tanpa ulang ke 1), total {len(second['commenters'])} komentar")

    print("\n=== 4. Cursor kedaluwarsa -> ulang dari awal, tidak ditandai lengkap ===")
    prog_ok = {"commenters": [f"u{i}" for i in range(20)], "cursor": "CURSOR-PAGE-30",
               "pages": 30, "unresolved": 0}
    s3 = FakeSession(total_authors, 3)      # cursor 30 tidak berlaku -> di luar jangkauan
    STATE["cursor_expired"] = True          # X balas tanpa data = cursor sudah kedaluwarsa
    r4 = await bot._fetch_x_replies_once(s3, TID, CT0, QID, 0, HANDLE, prog_ok)
    assert r4.get("restart") is True, f"harus restart, dapat {r4}"
    assert r4["complete"] is False, "hasil restart tidak boleh complete"
    assert r4["resume"]["cursor"] is None and r4["resume"]["pages"] == 0, r4["resume"]
    print(f"  [OK] restart=TRUE, complete=False, progres direset")

    print("\n=== 5. _apply_post_result menyimpan & memakai progres ===")
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    st = bot._post_state({}, "999")
    r = {"verified": True, "commenters": ["a", "b"], "pages": 5, "complete": False,
         "resume": {"commenters": ["a", "b"], "cursor": "C1", "pages": 5, "unresolved": 0}}
    bot._apply_post_result(st, r, now)
    assert st["state"] == bot.POST_PENDING, st["state"]
    assert st["progress"]["cursor"] == "C1" and st["progress"]["pages"] == 5, st["progress"]
    assert st["nextAt"] > now, "harus dijadwalkan ulang"
    r2 = {"verified": True, "commenters": ["a", "b", "c"], "pages": 9, "complete": True,
          "resume": {"commenters": ["a", "b", "c"], "cursor": None, "pages": 9, "unresolved": 0}}
    bot._apply_post_result(st, r2, now)
    assert st["state"] == bot.POST_OK and st["progress"] is None, st
    print("  [OK] progres tersimpan saat parsial, dibuang saat selesai")

    print("\n=== 6. 429 tidak menghapus progres ===")
    st2 = bot._post_state({}, "998")
    st2["progress"] = {"commenters": ["z"], "cursor": "C9", "pages": 9, "unresolved": 0}
    bot._apply_post_result(st2, {"verified": False, "rateLimited": True, "reason": "rate limit X (HTTP 429)"}, now)
    assert st2["progress"] and st2["progress"]["cursor"] == "C9", st2["progress"]
    assert st2["state"] == bot.POST_PENDING
    print("  [OK] progres tetap ada setelah 429")

    print("\n=== 7. Batas atas halaman -> tidak lengkap, tidak jadi bukti ===")
    bot.CHECKER_MAX_PAGES = 5
    s4 = FakeSession(total_authors, TOTAL_PAGES)
    r5 = await bot._fetch_x_replies_once(s4, TID, CT0, QID, 0, HANDLE, None)
    assert r5["pages"] == 5 and r5["complete"] is False, r5
    assert r5["truncated"] is True, r5
    bot.CHECKER_MAX_PAGES = 160
    print("  [OK] kena batas -> complete=False (tidak dipakai sebagai bukti tuduh)")

    print("\nSEMUA UJI KEDALAMAN & PROGRES LULUS")
    return True


sys.exit(0 if asyncio.run(main()) else 1)
