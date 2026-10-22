import os, asyncio, json, logging, random, re, aiohttp, time, hashlib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import ChannelParticipantsAdmins


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value[1:-1]
        os.environ[key] = value


def _env_int(name, default, minimum=0):
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name, default, minimum=0.0):
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


_load_dotenv(os.path.join(BASE_DIR, ".env"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if re.fullmatch(r"[0-9]+", x.strip())]
X_AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
X_CT0 = os.environ.get("X_CT0", "")
X_QUERY_ID = os.environ.get("X_QUERY_ID", "xOhkmRac04YFZmOzU9PJHg")
CHECKER_ENABLED = os.environ.get("CHECKER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
CHECKER_LEAD_MINUTES = _env_int("CHECKER_LEAD_MINUTES", 40)
CHECKER_SAMPLE_POSTS = _env_int("CHECKER_SAMPLE_POSTS", 0, 0)
CHECKER_REPLY_CAP = _env_int("CHECKER_REPLY_CAP", 0)
CHECKER_MAX_PAGES = _env_int("CHECKER_MAX_PAGES", 500, 1)
CHECKER_CONCURRENCY = _env_int("CHECKER_CONCURRENCY", 3, 1)
CHECKER_MAX_RUN_MINUTES = _env_int("CHECKER_MAX_RUN_MINUTES", 30, 1)
CHECKER_REQUIRE_FULL_COVERAGE = _env_int("CHECKER_REQUIRE_FULL_COVERAGE", 1, 0) == 1
CHECKER_MAX_DELIVERY_ATTEMPTS = _env_int("CHECKER_MAX_DELIVERY_ATTEMPTS", 3, 1)
CHECKER_DELAY_MIN = _env_float("CHECKER_DELAY_MIN", 1.0)
CHECKER_DELAY_MAX = _env_float("CHECKER_DELAY_MAX", 3.0)
CHECKER_PAGE_DELAY = _env_float("CHECKER_PAGE_DELAY", 1.5)
CHECKER_RATE_LIMIT_RETRIES = _env_int("CHECKER_RATE_LIMIT_RETRIES", 5, 0)
CHECKER_RATE_LIMIT_BASE_SECONDS = _env_float("CHECKER_RATE_LIMIT_BASE_SECONDS", 10.0)
X_RATE_LIMIT_UNTIL = 0.0
CHECKER_DELIVERY_IDS = [int(x.strip()) for x in os.environ.get("CHECKER_DELIVERY_IDS", "").split(",") if re.fullmatch(r"[0-9]+", x.strip())]
CHECKER_REPORT_TARGET = os.environ.get("CHECKER_REPORT_TARGET", "dm").strip().lower()
if CHECKER_REPORT_TARGET not in {"dm", "topic"}:
    CHECKER_REPORT_TARGET = "dm"
# CHECKER_REPORT_TOPIC dihapus: laporan checker hanya DM, tidak pernah ke topic.
DATA_DIR = os.path.abspath(os.environ.get("BOT_DATA_DIR", os.path.join(BASE_DIR, "data")))
PENDING_PATH = os.path.join(DATA_DIR, "check-3.json")
SESSION_PATH = os.path.join(DATA_DIR, "session-3.json")
RECOVERED_S4_PATH = os.path.join(DATA_DIR, "session-4-recovered.json")
LAST_CHECK_PATH = os.path.join(DATA_DIR, "last-check-3.json")
READY_PATH = os.path.join(BASE_DIR, ".ready")
MISSED_LOOKBACK_MIN = _env_int("MISSED_LOOKBACK_MIN", 180, 1)
MISSED_GRACE_MIN = _env_int("MISSED_GRACE_MIN", 6, 1)
# Pending checker menumpuk tanpa batas selama checker nonaktif (pernah 8 MB+).
# Sesi yang lebih tua dari ini dipangkas; manual-list g3 hanya butuh sesi baru.
PENDING_KEEP_DAYS = _env_int("PENDING_KEEP_DAYS", 14, 1)
# Jaring pengaman file cek manual g3: catat tiap kirim manual-list yang sukses
# per sesi, supaya kirim yang terlewat (mis. bot mati pas jam kirim) bisa
# dideteksi dan dikirim ulang, tanpa mengirim dua kali.
MANUAL_LEDGER_PATH = os.path.join(DATA_DIR, "manual-ledger.json")
# Pause buka/tutup sesi untuk grup tertentu. Contoh: PAUSED_GROUPS=g3
# Grup yang di-pause: tidak dibuka/di-tutup oleh cron, tidak dibuka oleh
# reconcile, dan tidak di-resume saat bot start. Kosongkan untuk lanjut lagi.
PAUSED_GROUPS = {x.strip().lower() for x in os.environ.get("PAUSED_GROUPS", "").split(",") if x.strip()}
X_QUERY_ID_PATH = os.path.join(DATA_DIR, "x-queryid.json")
X_CT0_PATH = os.path.join(DATA_DIR, "x-ct0.txt")
CHECKING = False

# --- Kebalisan (report-only, tanpa eksekusi) -----------------------------------
PROTECTED_IDS = {int(x.strip()) for x in os.environ.get("PROTECTED_IDS", "5650021727").split(",") if re.fullmatch(r"-?[0-9]+", x.strip())}
VIP_RANK_TAGS = tuple(t.strip().lower() for t in os.environ.get("VIP_RANK_TAGS", "vip").split(",") if t.strip())
VIP_PATH = os.path.join(DATA_DIR, "vip.json")
VIP_SCAN_LIMIT = _env_int("VIP_SCAN_LIMIT", 4000, 1)
VIP_SCAN_MINUTES = _env_int("VIP_SCAN_MINUTES", 30, 1)
X_OWNERS_PATH = os.path.join(DATA_DIR, "x-handle-owners.json")
X_OWNER_TTL_DAYS = _env_int("X_OWNER_TTL_DAYS", 30, 1)
DOUBLE_COOLDOWN_DAYS = _env_int("DOUBLE_COOLDOWN_DAYS", 7, 0)
DOUBLE_LOG_PATH = os.path.join(BASE_DIR, "double_reports.log")
# --- /lb: TOP 10 member g2 yang AKTIF dan TIDAK PERNAH kena /warn -----------
# Data ditarik job latar (refresh_lb_g2) dan disimpan ke LB_PATH. /lb hanya
# membaca file itu, jadi tidak pernah menarik data Telegram saat dipanggil.
LB_PATH = os.path.join(DATA_DIR, "lb-g2.json")
LB_WINDOW_DAYS = _env_int("LB_WINDOW_DAYS", 7, 1)
LB_SCAN_LIMIT = _env_int("LB_SCAN_LIMIT", 40000, 100)
LB_WARN_TOPIC = _env_int("LB_WARN_TOPIC", 844, 1)
LB_NOT_READY = "\u23f3 /lb: data not ready, nothing shown."
LB_CMD_RE = re.compile(r"^/lb\s*$", re.IGNORECASE)
LB_WARN_RE = re.compile(r"^/warn\s+@?([A-Za-z0-9_]{3,32})", re.IGNORECASE)
LB_LOCK = asyncio.Lock()
# /send: developer kirim isi defaulter -> diteruskan apa adanya ke customer.
SEND_TARGETS = [int(x.strip()) for x in os.environ.get("SEND_TARGETS", "5318526305").split(",") if re.fullmatch(r"-?[0-9]+", x.strip())]
SEND_ALLOWED = {int(x.strip()) for x in os.environ.get("SEND_ALLOWED", "5650021727").split(",") if re.fullmatch(r"-?[0-9]+", x.strip())}
# Kirim file "telegram username | link post" ke developer, 40 menit sebelum
# sesi berikutnya buka, supaya dicek manual. Tanggal WAJIB ada di file,
# nama file, dan caption -SESSION SLOT ("Sesi 3") saja tidak unik per hari.
MANUAL_LIST_ENABLED = os.environ.get("MANUAL_LIST_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
MANUAL_LIST_TARGET = [int(x.strip()) for x in os.environ.get("MANUAL_LIST_TARGET", "5650021727").split(",") if re.fullmatch(r"-?[0-9]+", x.strip())]
MANUAL_LIST_LEAD_MINUTES = _env_int("MANUAL_LIST_LEAD_MINUTES", 40, 1)
WIB = ZoneInfo("Asia/Jakarta")
TG_RETRY_ATTEMPTS = _env_int("TG_RETRY_ATTEMPTS", 4, 1)
TG_RETRY_BASE = _env_float("TG_RETRY_BASE", 2.0)
TG_TIMEOUT = _env_float("TG_TIMEOUT", 30.0)
CHECKER_SLICE_SECONDS = _env_int("CHECKER_SLICE_SECONDS", 240, 20)
CHECKER_DEADLINE_MARGIN = _env_int("CHECKER_DEADLINE_MARGIN", 5, 0) * 60 * 1000
CHECKER_POST_BACKOFF_MIN = _env_float("CHECKER_POST_BACKOFF_MIN", 7.0, 0.5)
CHECKER_RECOVERY_MINUTES = _env_int("CHECKER_RECOVERY_MINUTES", 90, 1)
# Batas jumlah pesan yang ditarik _sweep_g3_links dari history topic g3.
# Sesi g3 5 menit; 400 pesan pernah jadi ceiling. Kalau kena batas ini, sweep
# berhenti di pesan tertua dan log memberi peringatan supaya tidak diam-diam.
G3_SWEEP_LIMIT = _env_int("G3_SWEEP_LIMIT", 2000, 100)
# Toleransi (ms) untuk selisih jam server vs jam Telegram pada batas atas
# sweep, supaya link yang drop 1-2 detik sebelum tutup tidak terlewat.
G3_SWEEP_GRACE_MS = 5000

# uid -> rank tag "vip". Diisi dari session user (MTProto) karena Bot API tidak punya rank.
VIP_UIDS = set()
# False = reader rank tidak berfungsi (akun session user bukan admin grup).
VIP_READER_OK = False
# handle X -> {uid, who, at} lintas sesi, plus cooldown laporan.
X_OWNERS = {"owners": {}, "reported": {}}
WATCHDOG = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Error Telegram yang tidak akan pernah berhasil bila diulang (403/400 permanen).
# PENTING: dicek SETELAH retry_after, karena flood 429 kadang ikut membawa 403.
TG_PERMANENT = (
    "bot can't initiate conversation with a user",
    "bot can't send messages",
    "bot was blocked by the user",
    "user is deactivated",
    "chat not found",
    "kicked from the supergroup",
    "bot was kicked",
    "not enough rights",
    "have no rights to send",
    "message thread not found",
    "topic_deleted",
    "TOPIC_CLOSED",
    "message to delete not found",
    "message can't be deleted",
    "MESSAGE_ID_INVALID",
    "message is not modified",
)


def _tg_permanent(payload):
    desc = str((payload or {}).get("description") or "").lower()
    if any(marker.lower() in desc for marker in TG_PERMANENT):
        return True
    return int((payload or {}).get("error_code") or 0) in (400, 403)


async def _tg_post(path, build, timeout=None, attempts=None):
    """POST ke Bot API: hormati retry_after (flood), retry error jaringan,
    tapi JANGAN ulangi error permanen. Return (payload, permanent)."""
    limit = max(1, int(attempts if attempts is not None else TG_RETRY_ATTEMPTS))
    wait = max(0.5, float(TG_RETRY_BASE))
    last = {"ok": False, "description": "tidak ada respons"}
    for attempt in range(1, limit + 1):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{API}/{path}", timeout=aiohttp.ClientTimeout(total=timeout or TG_TIMEOUT), **build()) as r:
                    try:
                        payload = await r.json(content_type=None)
                    except (ValueError, aiohttp.ClientError) as e:
                        payload = {"ok": False, "description": f"respons bukan JSON: {e}"}
            if not isinstance(payload, dict):
                payload = {"ok": False, "description": f"respons aneh: {type(payload).__name__}"}
            if payload.get("ok"):
                return payload, False
            last = payload
            try:
                retry_after = float(((payload.get("parameters") or {}).get("retry_after")) or 0)
            except (TypeError, ValueError):
                retry_after = 0.0
            if retry_after > 0:
                sleep_for = min(max(retry_after, 1.0), 60.0)
                log.warning("TG %s throttle (%s) percobaan=%s/%s tunggu=%.1fs", path, payload.get("description"), attempt, limit, sleep_for)
                await asyncio.sleep(sleep_for)
                wait = min(wait * 2, 30.0)
                continue
            if _tg_permanent(payload):
                return payload, True
            return payload, False
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            last = {"ok": False, "description": f"{type(e).__name__}: {e}"}
            log.warning("TG %s jaringan gagal percobaan=%s/%s: %s", path, attempt, limit, e)
            if attempt >= limit:
                break
            await asyncio.sleep(wait)
            wait = min(wait * 2, 30.0)
    return last, False


async def api(method, client_timeout=None, attempts=None, **kw):
    # `timeout` di dalam body = parameter Bot API (long polling getUpdates).
    # Waktu tunggu sisi client dipisah dengan nama client_timeout supaya tidak
    # bentrok (dulu membuat getUpdates gagal total:TypeError).
    body = {k: v for k, v in kw.items() if v is not None}
    d, _ = await _tg_post(method, lambda: {"json": body}, client_timeout or TG_TIMEOUT, attempts)
    if not d.get("ok"):
        log.error("API %s gagal: %s", method, d.get("description", d))
    return d


async def send(chat_id, text, topic_id=None, parse_mode=None, attempts=None):
    kw = {"chat_id": chat_id, "text": text}
    if topic_id:
        kw["message_thread_id"] = topic_id
        kw["is_topic_message"] = True
    if parse_mode:
        kw["parse_mode"] = parse_mode
    d, _ = await _tg_post("sendMessage", lambda: {"json": kw}, TG_TIMEOUT, attempts)
    if not d.get("ok"):
        log.error("sendMessage gagal chat=%s topic=%s: %s", chat_id, topic_id, d.get("description", d))
    return d

# Topik khusus laporan double-account (grup yang sama, thread 279)
DOUBLE_REPORT = {"cid": -1004398227454, "tid": 279}

ACTIVE = {}

# Watcher Telethon (userbot) utk deteksi pesan link yg dihapus member sendiri.
OXY_SESSION_FILE = "/home/ubuntu/outputs/oxyas_string.txt"
OXY_API_ID = _env_int("OXY_API_ID", 0)
OXY_API_HASH = os.environ.get("OXY_API_HASH", "")

X_RE = re.compile(r"https?://(?:www\.)?(?:mobile\.)?(?:x|twitter)\.com/(\d+|[^/]+)/status/(\d+)", re.IGNORECASE)


def is_x_post(url):
    return bool(url and X_RE.match(str(url)))


def norm_x(url):
    m = X_RE.match(str(url or ""))
    if not m:
        return str(url or "").strip()
    return f"https://x.com/{m.group(1).lower()}/status/{m.group(2)}"


def parse_x_handle(url):
    m = X_RE.match(str(url or ""))
    if not m:
        return None
    return m.group(1).lower()


def x_tweet_id(url):
    m = X_RE.match(str(url or ""))
    return m.group(2) if m else None


def _utf16_slice(text, offset, length):
    data = str(text).encode("utf-16-le")
    return data[int(offset) * 2:(int(offset) + int(length)) * 2].decode("utf-16-le", "ignore")


def extract_links(msg):
    out = []
    def scan(text, ents):
        if not text:
            return
        for e in ents or []:
            t = e.get("type")
            if t == "url":
                out.append(_utf16_slice(text, e.get("offset", 0), e.get("length", 0)))
            elif t == "text_link":
                out.append(e.get("url"))
    scan(msg.get("text"), msg.get("entities"))
    scan(msg.get("caption"), msg.get("caption_entities"))
    for text in (msg.get("text"), msg.get("caption")):
        if text:
            out.extend(m.group(0) for m in X_RE.finditer(str(text)))
    return list(dict.fromkeys(u for u in out if is_x_post(u)))

def _link_already_recorded(sess, message_id, link):
    """True kalau link ini sudah masuk file link UNTUK pesan yang sama.

    Dipakai supaya edit pesan tidak menambah baris dobel. Dedup antar-member
    TIDAK terjadi: link identik dari member berbeda tetap ditulis 2x.
    """
    if message_id is None:
        return False
    return f"{message_id}|{link}" in (sess.get("_linkKeys") or ())


def _record_link(sess, message_id, link):
    keys = sess.setdefault("_linkKeys", set())
    if message_id is not None:
        keys.add(f"{message_id}|{link}")
        return
    # Tanpa message_id: pakai penanda unik supaya tetap tercatat.
    keys.add(f"nomsg|{len(sess.get('links', []))}|{link}")


def _drop_edited_g3_entry(sess, msg):
    msg_id = msg.get("message_id")
    if not msg_id:
        return
    old = [entry for entry in sess.get("entries", []) if entry.get("messageId") == msg_id]
    if not old:
        return
    sess["entries"] = [entry for entry in sess.get("entries", []) if entry.get("messageId") != msg_id]
    # Link yang SUDAH di-drop TIDAK PERNAH dicabut dari `links`, walaupun
    # pesannya lalu diedit. Aturan: semua link yang di-drop member wajib
    # masuk file link saat sesi ditutup. Edit hanya mengubah post yang dicek,
    # bukan daftar link.
    remaining_links = {e.get("link") for e in sess["entries"] if e.get("link")}
    sess["seen"] = set(sess["links"]) | remaining_links
    sender = msg.get("from") or {}
    uid = str(sender.get("id")) if sender.get("id") is not None else None
    if uid and not any(str(entry.get("uid")) == uid for entry in sess["entries"]):
        if not sess.get("mpost", {}).get(sender.get("id")):
            sess.get("participants", {}).pop(uid, None)
            sess.get("mpost", {}).pop(sender.get("id"), None)


# --- Kebalisan: PROTECTED (developer) + admin/creator + VIP (rank tag) ---------

def _vip_tags_match(rank):
    r = str(rank or "").strip().lower()
    if not r:
        return False
    return any(tag and tag in r for tag in VIP_RANK_TAGS)


def _is_protected(uid):
    try:
        return int(uid) in PROTECTED_IDS
    except (TypeError, ValueError):
        return False


def _is_vip(uid):
    try:
        return int(uid) in VIP_UIDS
    except (TypeError, ValueError):
        return False


def _immunity_label(uid):
    if _is_protected(uid):
        return "protected"
    if _is_vip(uid):
        return "vip"
    return ""


def _esc_html(text):
    """Escape &, <, > untuk pesan yang dikirim dengan parse_mode=HTML.

    Nama member dan isi pesan member adalah teks bebas. Tanpa escape, satu
    karakter `&` membuat Telegram balas 400 "can't parse entities" dan
    laporan hilang tanpa retry.
    """
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_text(text, limit=1500):
    """Bersihkan teks bukti: HTMLspecialchar & potong biar tidak bikin parse_mode gagal."""
    s = str(text or "").replace("\r", "")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(s) > limit:
        s = s[:limit] + "..."
    return s or "(no text)"


def _archive_double(cid, tid, note):
    try:
        with open(DOUBLE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} cid={cid} tid={tid} {note}\n")
    except OSError as e:
        log.warning("double log gagal: %s", e)


async def _is_immune(cid, uid, sess=None):
    """True = tidak boleh dilaporkan/ditegur (protected, admin/creator, atau VIP)."""
    if _is_protected(uid):
        return True
    if _is_vip(uid):
        return True
    try:
        st = await _member_status(cid, uid, sess) if sess is not None else "unknown"
    except Exception as e:
        log.warning("cek status uid=%s gagal: %s", uid, e)
        st = "unknown"
    if st in ("administrator", "creator"):
        if sess is not None:
            sess.setdefault("admin_uids", set()).add(str(uid))
        return True
    return False


# --- VIP dari rank tag (MTProto / session user) -------------------------------

def _load_vip_cache():
    global VIP_UIDS
    try:
        with open(VIP_PATH, encoding="utf-8") as f:
            data = json.load(f)
        vips = data.get("vips")
        if isinstance(vips, list):
            VIP_UIDS = {int(u) for u in vips if re.fullmatch(r"-?[0-9]+", str(u).strip())}
            log.info("VIP dimuat dari cache: %d orang", len(VIP_UIDS))
    except (OSError, ValueError, TypeError) as e:
        log.warning("gagal baca cache VIP: %s", e)


def _save_vip_cache(vips):
    try:
        _atomic_write(VIP_PATH, json.dumps({"vips": sorted(int(u) for u in vips),
                                            "savedAt": int(datetime.now(timezone.utc).timestamp() * 1000)},
                                           ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError) as e:
        log.warning("gagal simpan cache VIP: %s", e)


async def refresh_vips(client=None):
    """Tarik rank tag member grup via MTProto (butuh hak admin di grup).

    Kalau akun session user tidak punya hak admin, Telegram hanya menyingkap
    sebagian kecil member dan TIDAK mengirim rank -> hasilnya tidak berguna.
    Dalam kasus itu VIP tetap dikelola lewat /vip di dalam grup, dan kegagalan
    ini dilaporkan keras supaya tidak ada yang mengira VIP sudah terlindungi.
    """
    global VIP_UIDS, VIP_READER_OK
    c = client or WATCHDOG
    if c is None:
        log.error("VIP: session user belum siap - tag VIP TIDAK bisa dibaca")
        return VIP_UIDS
    try:
        ent = await c.get_input_entity(GROUPS["g3"]["cid"])
        try:
            perms = await c.get_permissions(ent, "me")
            can_view = bool(getattr(perms, "view_members", False) or getattr(perms, "change_info", False))
        except Exception:
            can_view = True
        vips = set()
        count = 0
        with_rank = 0
        async for part in c.iter_participants(ent, limit=VIP_SCAN_LIMIT):
            count += 1
            rank = getattr(part, "rank", None)
            if rank:
                with_rank += 1
            if _vip_tags_match(rank):
                uid = getattr(part, "user_id", None)
                if uid:
                    vips.add(int(uid))
        total = None
        try:
            full = await c.get_entity(GROUPS["g3"]["cid"])
            total = getattr(full, "participants_count", None)
        except Exception:
            pass
        # Gagal keras kalau rank tidak pernah terkirim (kemungkinan besar tidak
        # punya hak admin) -> JANGAN dianggap "tidak ada VIP".
        if with_rank == 0:
            VIP_READER_OK = False
            log.error("VIP: TIDAK ADA rank tag yang terbaca (%s/%s member, hak=%s). "
                      "Akun session user butuh hak ADMIN di grup '%s' agar tag VIP bisa dibaca. "
                      "Selama ini VIP hanya dari /vip di dalam grup.",
                      count, total if total else "?", can_view,
                      GROUPS["g3"].get("name", "g3"))
            return VIP_UIDS
        VIP_READER_OK = True
        if vips:
            VIP_UIDS = VIP_UIDS | vips
            _save_vip_cache(VIP_UIDS)
        log.info("VIP refreshed: %d tag VIP dari %s member (rank terbaca: %s, total grup: %s)",
                 len(vips), count, with_rank, total if total else "?")
    except Exception as e:
        VIP_READER_OK = False
        log.error("VIP: refresh gagal (pakai cache): %s", e)
    return VIP_UIDS


# --- /vip di dalam grup: cara utama mendaftarkan VIP --------------------------

VIP_CMD_RE = re.compile(r"^/(vip|unvip)\s+@?([A-Za-z0-9_]{3,32})\s*$", re.IGNORECASE)


async def _resolve_tg_username(name, cid, sess):
    """Username -> uid. Coba dari cache participants sesi, lalu MTProto."""
    target = name.lstrip("@").lower()
    for participant in ((sess or {}).get("participants") or {}).values():
        if isinstance(participant, dict) and str(participant.get("username") or "").lower() == target:
            return participant.get("uid")
    if WATCHDOG is not None:
        try:
            entity = await WATCHDOG.get_entity(target)
            return getattr(entity, "id", None)
        except Exception as e:
            log.info("resolusi @%s via MTProto gagal: %s", target, e)
    return None


async def _handle_vip_command(cid, tid, sess, msg):
    """/vip @user dan /unvip @user di grup g3 (atau topik mana pun).

    Hanya admin/creator/VIP/protected yang boleh menambah atau removes VIP,
    jadi anggota biasa tidak bisa memakai alasan Escape.
    """
    if cid != GROUPS["g3"]["cid"]:
        return False
    text = str(msg.get("text") or msg.get("caption") or "").strip()
    m = VIP_CMD_RE.match(text)
    if not m:
        return False
    sender = msg.get("from") or {}
    sid = sender.get("id")
    if not sid or sender.get("is_bot"):
        return False
    action, name = m.group(1).lower(), m.group(2)
    try:
        st = await _member_status(cid, sid, sess) if sess is not None else "unknown"
    except Exception:
        st = "unknown"
    if not (_is_protected(sid) or _is_vip(sid) or st in ("administrator", "creator")):
        await send(cid, "❌ Only an admin / creator / VIP can add or remove VIPs.", tid)
        return True
    uid = await _resolve_tg_username(name, cid, sess)
    if not uid:
        await send(cid, f"❌ @{name} was not found (or has never chatted in this group).", tid)
        return True
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        await send(cid, f"❌ @{name} is not valid.", tid)
        return True
    if action == "vip":
        VIP_UIDS.add(uid)
        _save_vip_cache(VIP_UIDS)
        note = f"✅ @{name} ({uid}) is now a VIP - will never be reported or warned."
    else:
        VIP_UIDS.discard(uid)
        _save_vip_cache(VIP_UIDS)
        note = f"✅ @{name} ({uid}) is no longer a VIP - can now appear in reports."
    log.info("VIP daftar diubah oleh uid=%s: %s", sid, note)
    await send(cid, note, tid)
    return True


# --- /send: developer -> customer, apa adanya --------------------------------

SEND_CMD_RE = re.compile(r"^/send\b([\s\S]*)$", re.IGNORECASE)
TG_TEXT_LIMIT = 4096


def _send_payload(text):
    """Pisahkan jadi potongan <= batas Telegram, TANPA memotong isi."""
    return [text[i:i + TG_TEXT_LIMIT] for i in range(0, len(text), TG_TEXT_LIMIT)] or [""]


def _send_preview(text, limit=100):
    """Ringkasan isi /send supaya bisa diperiksa tanpa membuka chat customer."""
    flat = " | ".join(text.splitlines())
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return f"sha={digest} char={len(text)} preview={flat[:limit]}"


def _latest_pending_session():
    """Pending g3 yang paling baru ditutup."""
    records = [r for r in _read_pending_records() if isinstance(r, dict)]
    if not records:
        return None
    return max(records, key=lambda r: _pending_time_ms(r))


def _manual_list_file(pending):
    """(filename, body, caption) file cek manual. Tanggal WAJIB ada di
    semua tiga tempat: header file, nama file, dan caption."""
    entries = [e for e in (pending.get("entries") or []) if isinstance(e, dict)]
    stamps = [int(e["atMs"]) for e in entries if e.get("atMs")]
    lo, hi = (min(stamps), max(stamps)) if stamps else (
        int(pending.get("closedAt") or 0), int(pending.get("closedAt") or 0))
    utc_lo, utc_hi = datetime.fromtimestamp(lo / 1000, timezone.utc), datetime.fromtimestamp(hi / 1000, timezone.utc)
    wib_lo, wib_hi = datetime.fromtimestamp(lo / 1000, WIB), datetime.fromtimestamp(hi / 1000, WIB)
    label = pending.get("sessionLabel") or "Session"
    total = len(entries)
    header = (f"# {label}\n"
              f"# window: {utc_lo:%d/%m/%Y %H:%M}-{utc_hi:%H:%M} UTC"
              f" / {wib_lo:%d/%m %H:%M}-{wib_hi:%H:%M} WIB\n"
              f"# total: {total} peserta\n")
    body = "".join(f"{e.get('who') or ('uid' + str(e.get('uid')))} | {e.get('link')}\n" for e in entries)
    match = re.search(r"Sesi\s+(\d+)", str(label))
    slot = int(match.group(1)) if match else 0
    filename = f"SESI{slot}-{wib_lo:%Y%m%d}-TELE-USERNAME-LINK.txt"
    caption = f"{label} = {wib_lo:%d/%m %H:%M}-{wib_hi:%H:%M} WIB | {total} peserta (ASLI) - cek manual"
    return filename, header + body, caption


async def send_manual_list(pending=None):
    """Kirim file cek manual ke developer. Tidak mengirim apa pun kalau tidak
    ada sesi yang menunggu - lebih baik tidak kirim daripada kirim yang salah.
    Kalau `pending` diberikan, kirim sesi itu (dipakai guard untuk sesi yang
    terlewat). Idempoten: sesi yang sudah tercatat terkirim dilewati."""
    if not MANUAL_LIST_TARGET:
        log.error("manual list: MANUAL_LIST_TARGET kosong")
        return False
    if pending is None:
        pending = _latest_pending_session()
    if not pending:
        log.warning("manual list: tidak ada sesi menunggu, tidak ada yang dikirim")
        return False
    key = _manual_session_key(pending)
    if key:
        prev = _read_manual_ledger().get(key)
        if isinstance(prev, dict) and prev.get("sentAt"):
            log.info("manual list: sesi %s sudah pernah terkirim, dilewati",
                     pending.get("sessionLabel"))
            return True
    filename, body, caption = _manual_list_file(pending)
    if not body.strip():
        log.warning("manual list: sesi %s tidak punya entry, tidak ada yang dikirim",
                    pending.get("sessionLabel"))
        return False
    sent_any = False
    for target in MANUAL_LIST_TARGET:
        ok, _ = await send_document(target, None, filename, body, caption)
        if ok:
            sent_any = True
            log.info("manual list terkirim ke %s: %s (%s byte, %s baris)",
                     target, filename, len(body), body.count("\n"))
        else:
            log.error("manual list GAGAL ke %s: %s", target, filename)
    if sent_any:
        _record_manual_sent(pending)
    return sent_any



async def _handle_send_command(msg):
    """/send <isi defaulter> -> dikirim apa adanya ke customer.

    Hanya dari DM developer (SEND_ALLOWED). Isi tidak diubah, tidak disaring,
    tidak difilter ulang - persis yang ditulis developer.
    """
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return False
    sender = msg.get("from") or {}
    uid = sender.get("id")
    if uid not in SEND_ALLOWED:
        return False
    body = (msg.get("text") or "").strip()
    if not SEND_CMD_RE.match(body):
        return False
    payload = SEND_CMD_RE.match(body).group(1).strip()
    if not payload:
        await send(uid, "/send kosong - tidak ada yang dikirim ke customer.")
        return True
    if not SEND_TARGETS:
        log.error("/send: SEND_TARGETS kosong, tidak ada customer tujuan")
        await send(uid, "/send gagal: customer tujuan tidak ada di config.")
        return True
    # Dicatat SEBELUM kirim: isi utuh tersimpan walau pengiriman gagal.
    log.info("/send diterima dari uid=%s: %s", uid, _send_preview(payload))
    results = []
    for target in SEND_TARGETS:
        ok = True
        for chunk in _send_payload(payload):
            res = await send(target, chunk)
            if not res.get("ok"):
                ok = False
        results.append((target, ok))
    gagal = [t for t, ok in results if not ok]
    if gagal:
        log.error("/send gagal ke %s", gagal)
        await send(uid, f"/send GAGAL ke customer {gagal}. Data tidak berubah, kirim ulang.")
    else:
        log.info("/send diteruskan uid=%s ke %s (%s karakter)", uid, SEND_TARGETS, len(payload))
        await send(uid, f"/send terkirim ke customer {SEND_TARGETS} ({len(payload)} karakter).")
    return True


# --- Cross-session owner X handle (anti double telegram) ---------------------

def _seed_reported_from_log():
    """Baca double_reports.log ->{cases yang SUDAH pernah dilaporkan diisi ke
    cooldown, supaya laporan lama tidak diulang ke topic 279."""
    pattern = re.compile(r"handle=@([A-Za-z0-9_]+)\s+owner=(-?\d+)\S*\s+violator=(-?\d+)")
    seeded = 0
    try:
        with open(DOUBLE_LOG_PATH, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = pattern.search(line)
                if not m:
                    continue
                key = f"{m.group(1).lower()}|{m.group(2)}|{m.group(3)}"
                X_OWNERS.setdefault("reported", {}).setdefault(key, int(datetime.now(timezone.utc).timestamp() * 1000))
                seeded += 1
    except OSError as e:
        log.warning("gagal seed laporan lama: %s", e)
    if seeded:
        log.info("cooldown anti-double diisi dari log: %s kasus", seeded)


def _load_x_owners():
    global X_OWNERS
    fresh = not os.path.exists(X_OWNERS_PATH)
    try:
        with open(X_OWNERS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            X_OWNERS = {"owners": data.get("owners") if isinstance(data.get("owners"), dict) else {},
                        "reported": data.get("reported") if isinstance(data.get("reported"), dict) else {}}
    except (OSError, ValueError, TypeError) as e:
        log.warning("gagal baca x-owners: %s", e)
    if fresh:
        _seed_reported_from_log()
        _save_x_owners()
    _prune_x_owners()


def _save_x_owners():
    try:
        _atomic_write(X_OWNERS_PATH, json.dumps(X_OWNERS, ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError) as e:
        log.warning("gagal simpan x-owners: %s", e)


def _prune_x_owners():
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    owner_ttl = X_OWNER_TTL_DAYS * 86400 * 1000
    cd_ttl = DOUBLE_COOLDOWN_DAYS * 86400 * 1000
    changed = False
    for h, rec in list(X_OWNERS.get("owners", {}).items()):
        if now - int(rec.get("at", 0)) > owner_ttl:
            X_OWNERS["owners"].pop(h, None)
            changed = True
    for k, ts in list(X_OWNERS.get("reported", {}).items()):
        if now - int(ts) > cd_ttl:
            X_OWNERS["reported"].pop(k, None)
            changed = True
    if changed:
        _save_x_owners()


def _owner_recorded(handle):
    rec = X_OWNERS.get("owners", {}).get(handle)
    return rec if isinstance(rec, dict) else None


def _record_owner(handle, uid, who):
    X_OWNERS.setdefault("owners", {})[handle] = {"uid": int(uid), "who": who,
                                                 "at": int(datetime.now(timezone.utc).timestamp() * 1000)}
    _save_x_owners()


def _double_already_reported(handle, owner_uid, violator_uid):
    key = f"{handle}|{owner_uid}|{violator_uid}"
    last = X_OWNERS.get("reported", {}).get(key)
    if last is None:
        return False
    cd = DOUBLE_COOLDOWN_DAYS * 86400 * 1000
    return int(datetime.now(timezone.utc).timestamp() * 1000) - int(last) < cd


def _mark_double_reported(handle, owner_uid, violator_uid):
    key = f"{handle}|{owner_uid}|{violator_uid}"
    X_OWNERS.setdefault("reported", {})[key] = int(datetime.now(timezone.utc).timestamp() * 1000)
    _save_x_owners()


def _display_identity(uid, who):
    """Kalau orangnya kebal (VIP/protected), jangan sebut identitas aslinya di laporan."""
    label = _immunity_label(uid)
    if label:
        return f"{who} ({label.upper()}, identity hidden)"
    return who


async def handle_update(upd):
    for key in ("message", "edited_message", "channel_post"):
        msg = upd.get(key)
        if not msg:
            continue
        cid = msg.get("chat", {}).get("id")
        tid = msg.get("message_thread_id")
        # /send hanya dari DM developer, bukan dari grup.
        try:
            if await _handle_send_command(msg):
                continue
        except Exception as e:
            log.warning("perintah /send gagal: %s", e)
        sess = ACTIVE.get((cid, tid))
        # /vip & /unvip boleh dipakai kapan saja (bukan cuma saat sesi aktif).
        try:
            if await _handle_vip_command(cid, tid, sess, msg):
                continue
        except Exception as e:
            log.warning("perintah VIP gagal: %s", e)
        # /lb (leaderboard g2) juga boleh kapan saja - dibaca dari file hasil
        # tarikan job latar, jadi tidak menarik data Telegram di sini.
        try:
            if await _handle_lb_command(cid, tid, msg):
                continue
        except Exception as e:
            log.warning("perintah /lb gagal: %s", e)
        if not sess or sess["closed"]:
            continue
        msg_date = msg.get("date")
        if msg_date and sess.get("openedAt") and int(msg_date) * 1000 < int(sess["openedAt"]) - 2000:
            continue
        links = extract_links(msg)
        sender = msg.get("from") or {}
        g3 = _is_g3_session(cid, tid)
        if g3 and key == "edited_message":
            _drop_edited_g3_entry(sess, msg)
        who = f"@{sender['username']}" if sender.get("username") else (sender.get("first_name") or (f"id{sender['id']}" if sender.get("id") is not None else "anonymous"))
        quota_violation = False
        if g3 and links:
            quota_violation = await _enforce_g3_quota(cid, tid, sess, msg, links)
            try:
                _save_g3_session(sess)
            except OSError as e:
                log.warning("g3 quota state save failed: %s", e)
        uid = sender.get("id")
        if g3 and links and uid is not None and not sender.get("is_bot"):
            # Semua orang yang drop link = peserta (termasuk admin/VIP;
            # penyaringan kebalisan dilakukan di analisis, satu titik tunggal).
            participants = sess.setdefault("participants", {})
            participants.setdefault(str(uid), {"uid": uid, "who": who,
                                               "username": sender.get("username"),
                                               "firstName": sender.get("first_name")})
        edited = key == "edited_message"
        # Edit "balik ke link lama" = semua link di pesan itu sudah pernah
        # tercatat. Hanya kasus ini yang membangun ulang postnya; kalau ada
        # link baru di dalamnya, jalur normal yang berlaku (tanpa perubahan).
        all_recorded = bool(links) and all(
            _link_already_recorded(sess, msg.get("message_id"), norm_x(l)) for l in links)
        for l in links:
            if sender.get("is_bot"):
                continue
            k = norm_x(l)
            # TANPA DEDUP antar-member: setiap link yang di-drop masuk file link
            # tanpa terkecuali, termasuk link identik milik member berbeda.
            # Yang di-dedup HANYA (pesan yang sama, link yang sama) supaya edit
            # tidak menggandakan baris. `seen` tetap diisi untuk logika lain.
            sess["seen"].add(k)
            already = _link_already_recorded(sess, msg.get("message_id"), k)
            if already:
                # Link ini sudah pernah masuk daftar link. Untuk pesan yang
                # DIEDIT ke link lamanya, postnya tetap harus dibangun ulang dari
                # isi terbaru: member tidak boleh hilang dari file cek manual.
                # Link di `links` tidak ditambah dua kali.
                rebuilt = (edited and g3 and all_recorded and not quota_violation
                           and not any(e.get("messageId") == msg.get("message_id")
                                       for e in sess.get("entries", [])))
                if not rebuilt:
                    continue
            else:
                _record_link(sess, msg.get("message_id"), k)
                sess["links"].append(k)
            # Entry (post) hanya untuk link PERTAMA milik member. Kalau kena
            # pelanggaran kuota, link ke-2 tetap masuk file link tapi bukan
            # post resminya (sudah dicatat di mpost).
            if g3 and not sender.get("is_bot") and not quota_violation:
                at_ms = (msg.get("date") or int(datetime.now(timezone.utc).timestamp())) * 1000
                sess.setdefault("entries", []).append({
                    "link": k,
                    "who": who,
                    "uid": sender.get("id"),
                    "exempt": bool(sender.get("id") is None or str(sender.get("id")) in sess.get("admin_uids", set())),
                    "atMs": at_ms,
                    "messageId": msg.get("message_id"),
                })
        if g3 and quota_violation and uid is not None and not sender.get("is_bot"):
            # Pelanggaran 1-link: tetap daftarkan link PERTAMA sebagai post resminya
            # supaya orangnya tetap dicek (tidak jadi "handle tidak diketahui").
            first = norm_x(links[0]) if links else None
            if first and not any(e.get("link") == first for e in sess.get("entries", [])):
                sess.setdefault("entries", []).append({
                    "link": first,
                    "who": who,
                    "uid": uid,
                    "exempt": False,
                    "atMs": (msg.get("date") or int(datetime.now(timezone.utc).timestamp())) * 1000,
                    "messageId": msg.get("message_id"),
                })
        if (g3 and (links or key == "edited_message")) or (not g3 and links):
            try:
                if g3:
                    _save_g3_session(sess)
                else:
                    _save_other_session(sess)
            except OSError as e:
                log.warning("session state save failed: %s", e)
        # Anti-double X-handle: HANYA grup 3, HANYA report (tanpa delete/mute/filter)
        await _check_double_g3(cid, tid, sess, msg, links)
        if g3:
            try:
                _save_g3_session(sess)
            except OSError as e:
                log.warning("g3 report state save failed: %s", e)


def _is_g3_session(cid, tid):
    try:
        g3 = GROUPS.get("g3")
    except NameError:
        return False
    return bool(g3) and cid == g3["cid"] and tid == g3["tid"]


def _fmt_acc(u):
    tid = u.get("id")
    uname = u.get("username")
    name = (u.get("first_name") or "user").strip()
    if uname:
        disp = f"@{uname}" + (f" ({name})" if name and name.lower() != uname.lower() else "")
    else:
        disp = name
    if tid:
        return f'<a href="tg://user?id={tid}">{_esc_html(disp)}</a>'
    return _esc_html(disp)


async def _member_status(cid, tg_id, sess):
    if not tg_id:
        return "unknown"
    cache = sess.setdefault("member_cache", {})
    if tg_id in cache:
        return cache[tg_id]
    try:
        d = await api("getChatMember", chat_id=cid, user_id=tg_id)
        if d.get("ok"):
            st = (d.get("result") or {}).get("status", "unknown")
            label = {"restricted": "restricted/muted", "kicked": "banned"}.get(st, st)
        else:
            label = "unknown"
    except Exception as e:
        log.warning("getChatMember failed: %s", e)
        label = "unknown"
    cache[tg_id] = label
    return label


async def _check_double_g3(cid, tid, sess, msg, links):
    """DIMATIKAN atas permintaan: tidak ada lagi laporan 1 handle X = 1 akun.

    Fungsi tetap dipanggil (tidak ada jalur laporan lain yang tersesat), tapi
    tidak pernah mengirim apa pun ke topic 279. Link tetap masuk file link.
    """
    return

async def _enforce_g3_quota(cid, tid, sess, msg, links):
    """1 member = 1 link per session (grup 3, topic sesi).

    REPORT-ONLY: bot tidak pernah menghapus / mute / ban. Pelanggaran hanya
    dilaporkan ke topic 279. Return True bila pesan ini kelebihan link (link
    ke-2 tidak dihitung sebagai post member, tapi tetap masuk file link)."""
    sender = msg.get("from") or {}
    if sender.get("is_bot") or not sender.get("id"):
        return False
    uid = sender["id"]
    if await _is_immune(cid, uid, sess):
        log.info("G3 quota dilewati (kebal) uid=%s links=%d", uid, len(links))
        return False
    # Link yang DITULIS (mentah) dihitung, jadi link sama yang ditulis 2x pun
    # tetap pelanggaran. uniq hanya untuk laporan & post resmi.
    raw = [n for n in (norm_x(l) for l in links) if n]
    uniq = list(dict.fromkeys(raw))
    if not uniq:
        return False
    msg_id = msg.get("message_id")
    mpost = sess.setdefault("mpost", {})
    rec = mpost.get(uid)
    # Edit pesan pertama yg sama: update catatan, tetap valid selama isinya masih 1 link.
    if rec and rec.get("msg_id") == msg_id:
        rec["text"] = msg.get("text") or msg.get("caption") or ""
        rec["links"] = uniq
        if len(raw) <= 1:
            return False
    if not rec and len(raw) == 1:
        mpost[uid] = {"uid": uid, "msg_id": msg_id, "links": uniq,
                      "text": msg.get("text") or msg.get("caption") or "",
                      "uname": sender.get("username"),
                      "fname": (sender.get("first_name") or "user").strip(),
                      "quota_reported": False}
        return False
    # Pelanggaran: link ke-2 (sama/beda) ATAU 2+ link dalam satu pesan.
    # TIDAK ada deleteMessage / restrict / ban di sini. Laporan saja.
    vuser = {"id": uid, "username": sender.get("username"),
             "first_name": sender.get("first_name")}
    first = uniq[0]
    extra = raw[1:]
    links_block = "\n".join(f"{i}. {_esc_html(l)}" for i, l in enumerate(raw, 1))
    txt = (f"⚠️ DUPLICATE LINK IN ONE SESSION\n\n"
           f"User: {_fmt_acc(vuser)}\n"
           f"Rule: only 1 link per member per session.\n"
           f"Extra link(s): {len(extra)}\n\n"
           f"Link(s):\n{links_block}\n\n"
           f"Original message:\n"
           f"{_safe_text(msg.get('text') or msg.get('caption') or '(no text)')}\n\n"
           f"(Report only. The bot did not delete the message, did not mute and did not ban anyone.)")
    _archive_double(cid, tid, f"tag=G3_1LINK uid={uid} msg_id={msg_id} links={','.join(raw)}")
    # Report cukup sekali per member per sesi (anti banjir 279).
    if rec is None:
        # Post resminya = link PERTAMA agar orangnya tetap bisa dicek.
        rec = {"uid": uid, "msg_id": msg_id, "links": [first],
               "text": msg.get("text") or msg.get("caption") or "",
               "uname": sender.get("username"),
               "fname": (sender.get("first_name") or "user").strip(),
               "quota_reported": False}
        mpost[uid] = rec
    if not rec.get("quota_reported"):
        result = await send(DOUBLE_REPORT["cid"], txt, DOUBLE_REPORT["tid"], parse_mode="HTML")
        if result.get("ok"):
            rec["quota_reported"] = True
        else:
            log.warning("quota report not delivered: %s", result.get("description", "unknown"))
    return True

async def _handle_deleted_link(mid):
    """Member menghapus link-nya sendiri setelah drop -> KECURANGAN -> report 279.
    Report-only: bot tidak pernah menghapus pesan anyone's."""
    g3 = GROUPS["g3"]
    sess = ACTIVE.get((g3["cid"], g3["tid"]))
    if not sess or sess["closed"]:
        return
    for uid, rec in (sess.get("mpost") or {}).items():
        if rec.get("msg_id") != mid or rec.get("deleted_reported"):
            continue
        rec["deleted_reported"] = True
        lnk = (rec.get("links") or [None])[0]
        vuser = {"id": uid, "username": rec.get("uname"), "first_name": rec.get("fname")}
        txt = (f"🚫 LINK REMOVED AFTER DROP (CHEATING)\n\n"
               f"User: {_fmt_acc(vuser)}\n"
               f"Link: {lnk}\n\n"
               f"Original message (evidence stored by bot):\n"
               f"{_esc_html(rec.get('text') or '(no text)')}\n\n"
               f"The member deleted their own link after dropping it, to hide participation in this session.")
        _archive_double(g3["cid"], g3["tid"],
                        f"tag=G3_DEL uid={uid} msg_id={mid} link={lnk}")
        result = await send(DOUBLE_REPORT["cid"], txt, DOUBLE_REPORT["tid"], parse_mode="HTML")
        if not result.get("ok"):
            log.warning("deleted report not delivered: %s", result.get("description", "unknown"))
        return

async def _setup_watchdog():
    with open(OXY_SESSION_FILE) as f:
        sess = f.read().strip()
    g3cid = GROUPS["g3"]["cid"]
    client = TelegramClient(StringSession(sess), OXY_API_ID, OXY_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("oxyas session not authorized")
    ent = await client.get_input_entity(g3cid)
    me = await client.get_me()
    log.info("Watchdog ready as id=%s @%s", me.id, me.username)

    @client.on(events.MessageDeleted(chats=ent))
    async def on_msg_deleted(event):
        for mid in event.deleted_ids or []:
            await _handle_deleted_link(mid)
    return client

async def poll_updates():
    global LAST_OFFSET
    offset = None
    while True:
        try:
            kw = {"timeout": 30}
            if offset is not None:
                kw["offset"] = offset
            # Client timeout > server long-poll timeout, else respons selalu
            # basket di sisi client (bug "poll error:" kosong).
            d = await api("getUpdates", client_timeout=max(TG_TIMEOUT, kw["timeout"] + 20), **kw)
            if d.get("ok"):
                for upd in d.get("result", []):
                    uid_upd = upd.get("update_id")
                    try:
                        await handle_update(upd)
                    except Exception as e:
                        # Satu update rusak tidak boleh membekukan offset (sebelumnya
                        # offset tidak naik -> update yang sama diproses selamanya).
                        log.exception("handle_update gagal update_id=%s: %s", uid_upd, e)
                    if uid_upd is not None:
                        offset = int(uid_upd) + 1
                        LAST_OFFSET = offset
            elif "webhook" in str(d.get("description", "")).lower():
                await api("deleteWebhook")
        except Exception as e:
            log.warning("poll error: %s", e or type(e).__name__)
        await asyncio.sleep(0.5)

def session_label(g, session_number=None):
    if session_number is not None:
        i = int(session_number) - 1
        oh, om, ch, cm = g["sch"][i]
        return f"Sesi {i+1} | {oh:02d}:{om:02d}-{ch:02d}:{cm:02d} UTC"
    now = datetime.now(timezone.utc)
    for i, (oh, om, ch, cm) in enumerate(g["sch"]):
        if (now.hour, now.minute) == (oh, om):
            return f"Sesi {i+1} | {oh:02d}:{om:02d}-{ch:02d}:{cm:02d} UTC"
    return "Sesi"

async def send_document(chat_id, topic_id, filename, body, caption=None, parse_mode=None):
    """Kirim file .txt. Return (ok, permanent).

    permanent=True berarti error yang tidak akan pernah berhasil bila diulang
    (mis. 'bot can't initiate conversation with a user') -> jangan dicoba lagi.
    """
    def build():
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        if topic_id:
            data.add_field("message_thread_id", str(topic_id))
        if caption:
            data.add_field("caption", str(caption)[:1024])
            if parse_mode:
                data.add_field("parse_mode", parse_mode)
        data.add_field("document", body.encode() if isinstance(body, str) else body,
                       filename=filename, content_type="text/plain")
        return {"data": data}
    d, permanent = await _tg_post("sendDocument", build, max(TG_TIMEOUT, 45.0))
    if d.get("ok"):
        return True, False
    log.error("sendDocument gagal chat=%s topic=%s: %s", chat_id, topic_id, d.get("description", d))
    return False, permanent


async def send_link_file(chat_id, topic_id, label, links):
    lines = [f"{i}. {l}" for i, l in enumerate(links, 1)]
    header = (f"{label} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
              f"\nTotal: {len(lines)} link\n\n")
    body = header + "\n".join(lines)
    ok, _ = await send_document(chat_id, topic_id, "links.txt", body)
    return ok

async def _checker_recipients(chat_id):
    if CHECKER_DELIVERY_IDS:
        return list(dict.fromkeys(CHECKER_DELIVERY_IDS))
    if ADMIN_IDS:
        return list(dict.fromkeys(ADMIN_IDS))
    try:
        result = await api("getChatAdministrators", chat_id=chat_id)
        if result.get("ok"):
            return list(dict.fromkeys(
                m.get("user", {}).get("id")
                for m in (result.get("result") or [])
                if m.get("user") and not m["user"].get("is_bot") and m["user"].get("id") is not None
            ))
    except Exception as e:
        log.warning("checker admin lookup failed: %s", e)
    return []


def _pick_check_entries(entries):
    """Target cek: satu entri unik per tweet id (link X valid)."""
    seen = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        link = norm_x(entry.get("link", ""))
        tweet_id = x_tweet_id(link)
        handle = parse_x_handle(link)
        if not link or not tweet_id or not handle:
            continue
        seen.setdefault(str(tweet_id), {"tweetId": str(tweet_id), "link": link, "handle": handle.lower()})
    return list(seen.values())


# --- Checker: cache per-post (resume), deadline keras, report only ------------

POST_OK = "ok"
POST_PENDING = "pending"
POST_UNREADABLE = "unreadable"


def _fetch_cache(pending):
    cache = pending.get("fetchCache")
    if not isinstance(cache, dict):
        cache = {}
        pending["fetchCache"] = cache
    return cache


def _post_state(cache, tweet_id):
    key = str(tweet_id)
    state = cache.get(key)
    if not isinstance(state, dict):
        state = {"state": POST_PENDING, "attempts": 0, "nextAt": 0,
                 "commenters": [], "reason": "", "at": 0, "pages": 0}
        cache[key] = state
    return state


def _post_backoff_ms(state):
    attempts = max(1, int(state.get("attempts") or 1))
    return int(min(CHECKER_POST_BACKOFF_MIN * (2 ** (attempts - 1)), 60.0) * 60 * 1000)


def _apply_post_result(state, result, now_ms):
    """Nilai satu post. HANYA 'ok' (terbaca penuh) yang boleh jadi bukti tuduh.

    Progres per halaman (cursor + komentar yang sudah terkumpul) ikut disimpan
    supaya percobaan berikutnya melanjutkan, bukan mengulang dari halaman 1.
    """
    result = result if isinstance(result, dict) else {}
    state["attempts"] = int(state.get("attempts") or 0) + 1
    state["at"] = int(now_ms)
    state["reason"] = str(result.get("reason") or "")[:200]
    try:
        state["pages"] = int(result.get("pages") or 0)
    except (TypeError, ValueError):
        state["pages"] = 0
    # progres: hanya Accepted kalau result verified (jadi_komentaris valid)
    progress = result.get("resume")
    if isinstance(progress, dict) and result.get("verified"):
        state["progress"] = {"commenters": sorted({str(c).lower() for c in (progress.get("commenters") or [])}),
                             "cursor": progress.get("cursor"),
                             "pages": int(progress.get("pages") or 0),
                             "unresolved": int(progress.get("unresolved") or 0)}
    if result.get("restart"):
        # cursor lama tidak berlaku -> mulai dari nol, jangan pakai progres lama
        state["progress"] = {"commenters": [], "cursor": None, "pages": 0, "unresolved": 0}
        state["commenters"] = []
        state["state"] = POST_PENDING
        state["nextAt"] = 0
        log.info("checker: cursor lama tidak berlaku, post dibaca ulang dari awal (%s)", state.get("reason"))
        return
    if result.get("verified"):
        state["commenters"] = sorted({str(c).lower() for c in (result.get("commenters") or [])})
        if result.get("complete"):
            state["state"] = POST_OK
            state["nextAt"] = 0
            state["progress"] = None
        else:
            # Balasan belum terbaca penuh -> tidak boleh jadi bukti (tuduh salah).
            state["state"] = POST_PENDING
            state["nextAt"] = int(now_ms) + _post_backoff_ms(state)
        return
    # gagal: jangan buang progres yang sudah terkumpul
    transient = bool(result.get("rateLimited") or result.get("authFail")
                     or result.get("staleQueryId") or result.get("networkError"))
    if transient or int(state["attempts"]) < 2:
        state["state"] = POST_PENDING
        state["nextAt"] = int(now_ms) + _post_backoff_ms(state)
    else:
        # Post hilang / tidak bisa dibaca -> masuk bagian "tidak terverifikasi".
        state["state"] = POST_UNREADABLE
        state["nextAt"] = 0
        state["progress"] = None


def _next_wake_ms(cache, targets, now_ms):
    soonest = None
    for target in targets:
        state = cache.get(str(target["tweetId"])) or {}
        if state.get("state") in (POST_OK, POST_UNREADABLE):
            continue
        nxt = int(state.get("nextAt") or 0)
        if nxt <= now_ms:
            return int(now_ms)
        soonest = nxt if soonest is None else min(soonest, nxt)
    return int(soonest if soonest is not None else now_ms)


def _sample_targets(pending, targets):
    """Post patokan: dipilih SEKALI lalu disimpan di record, jadi retry
    lanjut di post yang sama (kalau tiap tick ambil acak, tidak akan
    pernah selesai). Kalau CHECKER_SAMPLE_POSTS=0 -> semua post."""
    n = CHECKER_SAMPLE_POSTS
    if n <= 0 or n >= len(targets):
        return targets
    by_id = {t["tweetId"]: t for t in targets}
    saved = pending.get("sampleTweetIds")
    if isinstance(saved, list) and saved:
        chosen = [by_id[str(t)] for t in saved if str(t) in by_id]
        if chosen:
            return chosen
    picked = random.SystemRandom().sample(list(by_id), min(n, len(by_id)))
    pending["sampleTweetIds"] = picked
    try:
        _save_pending_check(pending)
    except (OSError, ValueError) as e:
        log.warning("simpan post patokan gagal: %s", e)
    log.info("post patokan sesi ini: %s", ", ".join(by_id[t]["link"] for t in picked))
    return [by_id[t] for t in picked]


def _in_scope_tweet_ids(pending):
    """Tweet id yang jadi bagian cek ini. Kalau sampling aktif, hanya post
    patokan; post lain di luar cakupan dan tidak boleh jadi tuduhan."""
    saved = pending.get("sampleTweetIds")
    if isinstance(saved, list) and saved:
        return {str(t) for t in saved}
    return None


async def _checker_fetch_slice(pending, now_ms, budget_s):
    """Satu irisan kerja; disimpan per post supaya retry LANJUT, bukan dari nol.

    Parallel (CHECKER_CONCURRENCY) + jeda pendek: 1 post hanya butuh ~1-7 detik
    request asli, jadi jeda lama/jalur serial membuat pengecekan 4x lebih
    lambat dari perlu dan memicu rate limit."""
    cache = _fetch_cache(pending)
    targets = _sample_targets(pending, _pick_check_entries(pending.get("entries")))
    queue = []
    for target in targets:
        state = cache.get(str(target["tweetId"]))
        status = (state or {}).get("state")
        if status in (POST_OK, POST_UNREADABLE):
            continue
        if now_ms < int((state or {}).get("nextAt") or 0):
            continue
        queue.append((target, state))
    fetched = failed = 0
    if queue:
        started = time.monotonic()
        semaphore = asyncio.Semaphore(max(1, CHECKER_CONCURRENCY))
        done_results = []

        async def work(target, cached_state, x_session):
            async with semaphore:
                result = await _fetch_x_replies_robust(x_session, target["tweetId"],
                                                       target["handle"],
                                                       (cached_state.get("progress") or None) if isinstance(cached_state, dict) else None)
            # entri cache dibuat saat benar-benar dicoba -> len(cache) = post yg
            # sudah dicoba (bukan placeholder untuk semua target)
            state = cached_state if isinstance(cached_state, dict) else _post_state(cache, target["tweetId"])
            _apply_post_result(state, result, now_ms)
            done_results.append(state)
            try:
                _save_pending_check(pending)
            except (OSError, ValueError) as e:
                log.warning("simpan cache post gagal: %s", e)
            if CHECKER_DELAY_MAX > 0:
                await asyncio.sleep(random.SystemRandom().uniform(
                    CHECKER_DELAY_MIN, max(CHECKER_DELAY_MIN, CHECKER_DELAY_MAX)))

        try:
            async with aiohttp.ClientSession(max_line_size=262144, max_field_size=65536) as x_session:
                tasks = []
                for target, cached_state in queue:
                    if time.monotonic() - started > budget_s:
                        break
                    tasks.append(asyncio.ensure_future(work(target, cached_state, x_session)))
                for task in tasks:
                    try:
                        await task
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
                        log.warning("fetch post gagal (lanjut): %s", e)
            fetched = len(done_results)
            failed = sum(1 for st in done_results if st.get("state") != POST_OK)
            log.info("checker irisis: %d/%d post selesai dalam %.0fs (gagal %d)",
                     fetched, len(queue), time.monotonic() - started, failed)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            log.warning("irisan checker terputus (progress tersimpan): %s", e)
            fetched = len(done_results)
    return fetched, failed, _next_wake_ms(cache, targets, now_ms)


def _record_deadline(pending, now_ms):
    for key in ("reportAt", "checkAt"):
        value = pending.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return int(now_ms) + 30 * 60 * 1000


def _select_pending(now_ms):
    """Record yang paling dekat deadline-nya -> tidak ada yang kelaparan."""
    due = []
    for record in _read_pending_records():
        if not record.get("entries"):
            continue
        check_at = record.get("checkAt")
        if isinstance(check_at, (int, float)) and not isinstance(check_at, bool) and now_ms < int(check_at):
            continue
        retry_at = record.get("retryAt")
        if isinstance(retry_at, (int, float)) and not isinstance(retry_at, bool) and now_ms < int(retry_at):
            continue
        due.append(record)
    if not due:
        return None
    due.sort(key=lambda r: (_record_deadline(r, now_ms), int(r.get("closedAt") or 0)))
    return due[0]


def _defer_pending(pending, now_ms, reason, delay_minutes=5):
    pending["retryAt"] = int(now_ms + max(0.0, float(delay_minutes)) * 60 * 1000)
    pending["lastError"] = str(reason)[:300]
    try:
        _save_pending_check(pending)
    except (OSError, ValueError) as e:
        log.warning("could not defer pending checker: %s", e)


def _has_x_cookie():
    return bool(X_AUTH_TOKEN and (X_CT0 or _read_cached_ct0()))


async def _deliver_checker_report(pending, body, caption, summary, filename):
    """Laporan checker HANYA ke DM. TIDAK PERNAH ke topic.

    Kalau DM ditolak (mis. 403 karena penerima belum /start ke bot), bot
    TETAP mencoba lagi di DM yang sama pada percobaan berikutnya - tidak
   =blacklist, tidak pindah ke topic."""
    recipients = await _checker_recipients(DOUBLE_REPORT["cid"])
    if not recipients:
        log.error("checker: tidak ada penerima DM di config")
        return False
    delivered = []
    for recipient in recipients:
        ok, _ = await send_document(recipient, None, filename, body, caption)
        if ok:
            delivered.append(recipient)
        else:
            log.warning("checker: DM ke %s gagal, akan dicoba lagi di percakapan yang sama", recipient)
    if not delivered:
        return False
    for recipient in delivered:
        await send(recipient, summary)
    return True


def _scan_double_handles(pending):
    """Anti-double RETROAKTIF: 1 handle X dipakai >1 akun Telegram dalam satu
    sesi. Live detection bisa terlewat (bot mati, atau drop-nya di sesi
    berbeda), jadi sesi yang sudah lewat tetap dipindai saat report dibuat.
    Report-only, menghormati kebalisan + cooldown."""
    immune = _session_immune_uids(pending)
    by_handle = {}
    for entry in (pending.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        handle = parse_x_handle(entry.get("link", ""))
        uid = entry.get("uid")
        if not handle or uid is None:
            continue
        by_handle.setdefault(handle.lower(), {}).setdefault(str(uid), entry.get("who") or f"id{uid}")
    findings = []
    for handle, uids in by_handle.items():
        if len(uids) < 2:
            continue
        items = list(uids.items())
        owner_uid, owner_who = items[0]
        try:
            if int(owner_uid) in immune:
                continue
        except (TypeError, ValueError):
            pass
        for violator_uid, violator_who in items[1:]:
            try:
                if int(violator_uid) in immune:
                    continue
            except (TypeError, ValueError):
                continue
            if _double_already_reported(handle, owner_uid, violator_uid):
                continue
            findings.append((handle, owner_uid, owner_who, violator_uid, violator_who))
    return findings


async def _report_double_findings(pending, findings):
    for handle, owner_uid, owner_who, violator_uid, violator_who in findings:
        txt = (f"⚠️ DUPLICATE X HANDLE DETECTED\n\n"
               f"X handle: @{handle}\n"
               f"Telegram 1: {_display_identity(owner_uid, owner_who)}\n"
               f"Telegram 2 (violator): {violator_who}\n"
               f"Session: {pending.get('sessionLabel') or pending.get('sessionName') or '-'}\n\n"
               f"One person is possibly using 2 Telegram accounts. Admins, please review.\n"
               f"(Report-only: no messages were deleted / muted / banned by the bot.)")
        log.info("DOUBLE retroaktif handle=@%s owner=%s violator=%s", handle, owner_uid, violator_uid)
        _archive_double(pending.get("chatId"), pending.get("topicId"),
                        f"tag=G3_DOUBLE_RETRO handle=@{handle} owner={owner_uid} violator={violator_uid}")
        result = await send(DOUBLE_REPORT["cid"], txt, DOUBLE_REPORT["tid"], parse_mode="HTML")
        if result.get("ok"):
            _mark_double_reported(handle, owner_uid, violator_uid)


async def do_check_g3():
    global CHECKING
    if not CHECKER_ENABLED or CHECKING:
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    pending = _select_pending(now_ms)
    if not pending:
        return
    deadline = _record_deadline(pending, now_ms)
    cutoff = deadline - CHECKER_DEADLINE_MARGIN
    CHECKING = True
    try:
        has_cookie = _has_x_cookie()
        if not _pick_check_entries(pending.get("entries")):
            # Tidak ada satu pun link X valid -> tidak ada yang bisa dicek.
            # Diarsipkan tanpa mengirim laporan kosong ke topic.
            log.error("checker: %s tidak punya link X valid, dilewati (arsip last-check)",
                      pending.get("sessionLabel"))
            _atomic_write(LAST_CHECK_PATH, json.dumps(
                dict(pending, checkedAt=now_ms, checkedCount=0, defaulters=[],
                     proofLink="-", coverageComplete=False, noValidLinks=True),
                ensure_ascii=False, indent=2))
            _clear_pending_check(pending.get("sessionId"))
            return
        fetched = failed = 0
        wake = now_ms
        if has_cookie:
            fetched, failed, wake = await _checker_fetch_slice(pending, now_ms, CHECKER_SLICE_SECONDS)
        else:
            log.warning("checker: tidak ada cookie X, report hanya bisa menandai tidak terverifikasi")
        analysis = _analyze_g3(pending)
        remaining = analysis["pending"]
        if remaining and has_cookie:
            late = now_ms >= cutoff
            # Mode pemulihan: deadline sudah lewat (mis. bot sempat mati).
            # Mengirim report dengan 5% post terbaca = tidak ada yang bisa
            # disimpulkan, jadi lebih baik selesaikan sampai cakupannya
            # berguna, dengan batas keras supaya PASTI terkirim.
            recovery_deadline = None
            if late:
                started_at = pending.get("recoveryStartedAt")
                if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
                    started_at = now_ms
                    pending["recoveryStartedAt"] = started_at
                    _defer_pending(pending, now_ms, "mode pemulihan: deadline sudah lewat", 0)
                recovery_deadline = int(started_at) + CHECKER_RECOVERY_MINUTES * 60 * 1000
            if not late:
                wait_min = max(0.0, min((wake - now_ms) / 60000.0, 10.0))
                if fetched == 0:
                    # Tidak ada yang bisa dikerjakan sekarang (semua post masih
                    # backoff) -> jangan cek ulang tiap 20 detik.
                    wait_min = max(wait_min, 2.0)
                _defer_pending(pending, now_ms,
                               f"progres {fetched} post, sisa {remaining} menunggu", wait_min)
                return
            if recovery_deadline and now_ms < recovery_deadline:
                wait_min = max(0.0, min((wake - now_ms) / 60000.0, 10.0))
                if fetched == 0:
                    wait_min = max(wait_min, 2.0)
                _defer_pending(pending, now_ms,
                               f"pemulihan: {analysis['checked']}/{analysis['posts']} post terbaca, "
                               f"sisa {remaining} (batas {CHECKER_RECOVERY_MINUTES}m)", wait_min)
                return
            if recovery_deadline:
                log.warning("checker: batas pemulihan habis, kirim apa adanya "
                            "(%s/%s post terbaca)", analysis["checked"], analysis["posts"])
        if analysis["posts"] and not analysis["checked"]:
            # 0 dari N post terbaca = tidak ada satu pun bukti yang bisa
            # disimpulkan. JANGAN kirim laporan apa pun: file "no defaulters"
            # dengan 0 post terbaca pernah terkirim ke customer. Record ditahan,
            # bukan dihapus, supaya datanya tidak hilang.
            log.error("checker: %s 0/%s post terbaca - laporan DIBATALKAN, tidak dikirim",
                      pending.get("sessionLabel"), analysis["posts"])
            _defer_pending(pending, now_ms, "0 post terbaca, laporan dibatalkan", 60)
            return
        body = _format_defaulters(pending, analysis)
        caption = _checker_caption(pending, analysis)
        summary = _checker_summary(pending, analysis)
        safe_session = re.sub(r"[^A-Za-z0-9_-]+", "-", str(pending.get("sessionName") or "session"))
        filename = f"defaulters-{safe_session}.txt"
        # Anti-double retroactive: DIMATIKAN atas permintaan (tidak ada lagi
        # laporan 1 handle X = 1 akun ke topic 279).
        delivered = await _deliver_checker_report(pending, body, caption, summary, filename)
        if not delivered:
            attempts = int(pending.get("deliveryAttempts") or 0) + 1
            pending["deliveryAttempts"] = attempts
            wait = 30 if attempts >= CHECKER_MAX_DELIVERY_ATTEMPTS else 2
            log.error("checker report gagal terkirim (percobaan %s), coba lagi dalam %s menit",
                      attempts, wait)
            _defer_pending(pending, now_ms, "pengiriman report gagal", wait)
            return
        # fetchCache tidak ikut diarsipkan (besar, tidak perlu_disimpan ulang).
        archive = {k: v for k, v in pending.items() if k != "fetchCache"}
        archive["checkedAt"] = now_ms
        archive["checkedCount"] = analysis["checked"]
        archive["defaulters"] = analysis["defaulters"]
        archive["proofLink"] = analysis["proofLink"]
        archive["coverageComplete"] = analysis["coverageComplete"]
        _atomic_write(LAST_CHECK_PATH, json.dumps(archive, ensure_ascii=False, indent=2))
        _clear_pending_check(pending.get("sessionId"))
        log.info("CHECK report terkirim label=%s defaulters=%s participants=%s "
                 "posts_checked=%s/%s immune=%s",
                 pending.get("sessionLabel"), len(analysis["defaulters"]),
                 analysis["participants"], analysis["checked"], analysis["posts"],
                 analysis["immune"])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        _defer_pending(pending, now_ms, e, 5)
        log.exception("checker gagal: %s", e)
    finally:
        CHECKING = False


def _atomic_write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _valid_pending(value):
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        return False
    try:
        if int(value.get("chatId")) != GROUPS["g3"]["cid"]:
            return False
        if int(value.get("topicId")) != GROUPS["g3"]["tid"]:
            return False
    except (TypeError, ValueError):
        return False
    if not isinstance(value.get("sessionId"), str) or not value["sessionId"]:
        return False
    participants = value.get("participants", [])
    if not isinstance(participants, (dict, list)):
        return False
    participant_values = list(participants.values()) if isinstance(participants, dict) else participants
    if any(not isinstance(participant, dict) for participant in participant_values):
        return False
    if any(not isinstance(entry, dict) or not isinstance(entry.get("link"), str) or not entry.get("link") for entry in value["entries"]):
        return False
    if value.get("checkAt") is not None and (isinstance(value["checkAt"], bool) or not isinstance(value["checkAt"], (int, float))):
        return False
    if value.get("reportAt") is not None and (isinstance(value["reportAt"], bool) or not isinstance(value["reportAt"], (int, float))):
        return False
    if value.get("retryAt") is not None and (isinstance(value["retryAt"], bool) or not isinstance(value["retryAt"], (int, float))):
        return False
    return True


def _read_raw_pending_records():
    """Record TANPA validasi (dipakai saat menyimpan, supaya record yang
    bermasalah tidak ikut terhapus dari disk)."""
    try:
        with open(PENDING_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    records = raw.get("sessions", []) if isinstance(raw, dict) and "sessions" in raw else raw
    if isinstance(records, dict):
        records = [records]
    return records if isinstance(records, list) else []


def _read_pending_records():
    valid = []
    for record in _read_raw_pending_records():
        try:
            if _valid_pending(record):
                valid.append(record)
            else:
                # JANGAN dibuang diam-diam: record yang hilang = sesi hilang.
                log.error("pending record tidak valid, DILEWATI (bukan dihapus): %s",
                          (record or {}).get("sessionId") if isinstance(record, dict) else type(record).__name__)
        except (TypeError, ValueError) as e:
            log.error("pending record rusak, DILEWATI: %s", e)
    return valid


def _pending_time_ms(record):
    """Waktu sesi pending (closedAt/openedAt) sebagai int ms; 0 kalau tidak
    valid - satu record rusak tidak boleh mematikan proses."""
    try:
        return int(record.get("closedAt") or record.get("openedAt") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _prune_pending_records(records, now_ms):
    """Buang sesi pending yang lebih tua dari PENDING_KEEP_DAYS. Tanpa ini
    pending menumpuk tanpa batas selama checker nonaktif."""
    cutoff = now_ms - PENDING_KEEP_DAYS * 24 * 60 * 60 * 1000
    kept = []
    for r in records:
        if not isinstance(r, dict):
            continue
        closed = _pending_time_ms(r)
        # Waktu tak terbaca (0) -> JANGAN dipangkas (lebih baik simpan).
        if closed == 0 or closed >= cutoff:
            kept.append(r)
    return kept


def _prune_pending_file():
    """Pangkas file pending sekali saat start (kalau sudah menumpuk)."""
    try:
        raw = _read_raw_pending_records()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        kept = _prune_pending_records(raw, now_ms)
        if len(kept) != len(raw):
            _atomic_write(PENDING_PATH, json.dumps({"sessions": kept}, ensure_ascii=False, indent=2))
            log.info("pending check dipangkas: %d -> %d sesi", len(raw), len(kept))
    except Exception as e:
        log.warning("pangkas pending check gagal: %s", e)


def _save_pending_check(payload):
    if not _valid_pending(payload):
        raise ValueError("pending checker tidak valid")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    records = [record for record in _read_raw_pending_records()
               if not (isinstance(record, dict) and record.get("sessionId") == payload["sessionId"])]
    records.append(payload)
    records = _prune_pending_records(records, now_ms)
    _atomic_write(PENDING_PATH, json.dumps({"sessions": records}, ensure_ascii=False, indent=2))


def _read_manual_ledger():
    """Catatan sesi g3 yang file cek manual-nya sudah terkirim. Tahan terhadap
    file hilang/rusak: kembalikan {} kalau tidak bisa dibaca."""
    try:
        with open(MANUAL_LEDGER_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_manual_ledger(ledger):
    try:
        _atomic_write(MANUAL_LEDGER_PATH, json.dumps(ledger, ensure_ascii=False, indent=2))
    except OSError as e:
        log.warning("simpan manual-ledger gagal: %s", e)


def _manual_session_key(pending):
    """Kunci unik per sesi (sessionId). Label sesi berulang tiap hari, jadi
    JANGAN pakai label saja - nanti sesi hari ini dianggap sudah terkirim
    padahal itu catatan sesi kemarin."""
    if not isinstance(pending, dict):
        return None
    sid = pending.get("sessionId")
    if sid:
        return str(sid)
    label = pending.get("sessionLabel") or pending.get("sessionName")
    closed = _pending_time_ms(pending)
    if not label:
        return None
    return f"{label}|{closed}"


def _prune_manual_ledger(ledger, now_ms):
    cutoff = now_ms - 3 * 24 * 60 * 60 * 1000
    return {k: v for k, v in ledger.items()
            if isinstance(v, dict) and int(v.get("sentAt") or 0) >= cutoff}


def _record_manual_sent(pending):
    """Catat bahwa file cek manual sesi ini benar-benar terkirim ke developer."""
    key = _manual_session_key(pending)
    if not key:
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ledger = _read_manual_ledger()
    rec = ledger.get(key) if isinstance(ledger.get(key), dict) else {}
    rec["sentAt"] = now_ms
    ledger[key] = rec
    _write_manual_ledger(_prune_manual_ledger(ledger, now_ms))


def _load_pending_check(session_id=None):
    records = _read_pending_records()
    if session_id is not None:
        return next((record for record in records if record.get("sessionId") == session_id), None)
    return records[0] if records else None


def _clear_pending_check(expected_session_id=None):
    if expected_session_id is None:
        try:
            os.unlink(PENDING_PATH)
            return True
        except FileNotFoundError:
            return False
    # Pakai record mentah: report yang sukses untuk satu sesi tidak boleh
    # ikut menghapus record lain yang bermasalah.
    raw = _read_raw_pending_records()
    remaining = [record for record in raw
                 if not (isinstance(record, dict) and record.get("sessionId") == expected_session_id)]
    if len(remaining) == len(raw):
        return False
    if remaining:
        _atomic_write(PENDING_PATH, json.dumps({"sessions": remaining}, ensure_ascii=False, indent=2))
    else:
        try:
            os.unlink(PENDING_PATH)
        except FileNotFoundError:
            return False
    return True


def _session_path(topic_id):
    return os.path.join(DATA_DIR, f"session-{topic_id}.json")


def _session_payload(sess, g3=False):
    participants = sess.get("participants", {})
    participant_values = list(participants.values()) if isinstance(participants, dict) else list(participants or [])
    label = sess.get("label") or sess.get("sessionLabel") or ""
    return {
        "topicId": sess.get("topicId"),
        "chatId": GROUPS["g3"]["cid"] if g3 else sess.get("chatId"),
        "sessionName": (sess.get("sessionName") or label.split(" | ", 1)[0]),
        "sessionLabel": label,
        "openedAt": sess.get("openedAt", int(datetime.now(timezone.utc).timestamp() * 1000)),
        "links": sess.get("links", []),
        "entries": sess.get("entries", []),
        "participants": participant_values,
        "mpost": sess.get("mpost", {}),
        "handleOwner": sess.get("handle_owner", {}),
        "reported": list(sess.get("reported", set())),
        "adminUids": list(sess.get("admin_uids", set())),
        "linkKeys": list(sess.get("_linkKeys", set())),
    }


def _save_session_file(sess, path, g3=False):
    _atomic_write(path, json.dumps(_session_payload(sess, g3=g3), ensure_ascii=False, indent=2))


def _save_g3_session(sess):
    _save_session_file(sess, SESSION_PATH, g3=True)


def _save_other_session(sess):
    _save_session_file(sess, _session_path(sess.get("topicId")), g3=False)


def _load_session_file(path, expected_cid=None, expected_tid=None):
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, dict) or not isinstance(value.get("entries"), list) or not isinstance(value.get("links"), list):
            return None
        if expected_tid is not None and value.get("topicId") != expected_tid:
            return None
        if expected_cid is not None and value.get("chatId") != expected_cid:
            return None
        if not isinstance(value.get("openedAt"), (int, float)) or isinstance(value.get("openedAt"), bool):
            return None
        participants = value.get("participants", [])
        if not isinstance(participants, list) or any(not isinstance(p, dict) for p in participants):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def _load_g3_session():
    return _load_session_file(SESSION_PATH, GROUPS["g3"]["cid"], GROUPS["g3"]["tid"])


def _load_other_session(topic_id, chat_id):
    return _load_session_file(_session_path(topic_id), chat_id, topic_id)


def _clear_session_file(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _clear_g3_session():
    _clear_session_file(SESSION_PATH)


def _clear_other_session(topic_id):
    _clear_session_file(_session_path(topic_id))


def _session_at_for_group(g, now=None):
    now = now or datetime.now(timezone.utc)
    minute = now.hour * 60 + now.minute
    for i, (oh, om, ch, cm) in enumerate(g["sch"]):
        start = oh * 60 + om
        end = ch * 60 + cm
        open_now = start <= minute < end if start < end else minute >= start or minute < end
        if open_now:
            return i, f"Sesi {i + 1} | {oh:02d}:{om:02d}-{ch:02d}:{cm:02d} UTC"
    return None


def _g3_session_at(now=None):
    return _session_at_for_group(GROUPS["g3"], now)


def _session_start_ms_for_group(group, now=None):
    now = now or datetime.now(timezone.utc)
    current = _session_at_for_group(group, now)
    if not current:
        return int(now.timestamp() * 1000)
    index = current[0]
    start = group["sch"][index][0] * 60 + group["sch"][index][1]
    end = group["sch"][index][2] * 60 + group["sch"][index][3]
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if start >= end and now.hour * 60 + now.minute < end:
        midnight -= timedelta(days=1)
    return int((midnight + timedelta(minutes=start)).timestamp() * 1000)


def _mpost_by_uid(value):
    """Kunci mpost HARUS int (uid Telegram).

    Setelah state melewati JSON, kunci object otomatis jadi string. Kalau tidak
    dinormalkan, `mpost.get(uid)` meleset tiap bot restart -> aturan 1 link per
    sesi lupa semua orang dan `quota_reported` yang lama hilang.
    """
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, rec in value.items():
        try:
            out[int(key)] = rec
        except (TypeError, ValueError):
            continue
    return out


def _restore_session_state(saved, chat_id, topic_id):
    participants = {str(p.get("uid")): p for p in saved.get("participants", []) if p.get("uid") is not None}
    return {
        "topicId": topic_id,
        "chatId": chat_id,
        "openedAt": saved.get("openedAt"),
        "seen": {norm_x(x) for x in saved.get("links", [])},
        "links": list(saved.get("links", [])),
        "entries": list(saved.get("entries", [])),
        "participants": participants,
        "closed": False,
        "label": saved.get("sessionLabel"),
        "handle_owner": saved.get("handleOwner", {}) if isinstance(saved.get("handleOwner", {}), dict) else {},
        "reported": set(saved.get("reported", [])) if isinstance(saved.get("reported", []), list) else set(),
        "member_cache": {},
        "mpost": _mpost_by_uid(saved.get("mpost")),
        "admin_uids": set(str(uid) for uid in saved.get("adminUids", [])) if isinstance(saved.get("adminUids", []), list) else set(),
        "_linkKeys": set(saved.get("linkKeys", [])) if isinstance(saved.get("linkKeys", []), list) else set(),
    }


def _archive_session_file(path, saved):
    stamp = int(saved.get("openedAt") or datetime.now(timezone.utc).timestamp() * 1000)
    archive = os.path.join(DATA_DIR, f"recovered-session-{stamp}.json")
    _atomic_write(archive, json.dumps(saved, ensure_ascii=False, indent=2))
    _clear_session_file(path)


def _resume_other_sessions():
    now = datetime.now(timezone.utc)
    for name, group in GROUPS.items():
        if name == "g3" or name in PAUSED_GROUPS:
            continue
        saved = _load_other_session(group["tid"], group["cid"])
        if not saved:
            continue
        current = _session_at_for_group(group, now)
        same_day = datetime.fromtimestamp(saved["openedAt"] / 1000, timezone.utc).date() == now.date()
        if current and current[1] == saved.get("sessionLabel") and same_day:
            ACTIVE[(group["cid"], group["tid"])] = _restore_session_state(saved, group["cid"], group["tid"])
            log.info("%s session resumed label=%s links=%d", name, saved.get("sessionLabel"), len(saved.get("links", [])))
        else:
            _archive_session_file(_session_path(group["tid"]), saved)
            log.info("%s stale session archived label=%s links=%d", name, saved.get("sessionLabel"), len(saved.get("links", [])))


def _ensure_active_sessions():
    now = datetime.now(timezone.utc)
    for name, group in GROUPS.items():
        if name in PAUSED_GROUPS:
            continue
        key = (group["cid"], group["tid"])
        if key in ACTIVE and not ACTIVE[key].get("closed"):
            continue
        current = _session_at_for_group(group, now)
        if not current:
            continue
        if name == "g3" and os.path.exists(SESSION_PATH):
            preserved = _load_g3_session()
            if preserved and preserved.get("entries"):
                # Sesi lama masih ada. Tetap JALANKAN sesi jendela sekarang:
                # sebelumnya di-skip -> tidak ada ACTIVE -> SEMUA link jendela ini
                # dibuang. Sesi lama diamankan sebagai pending checker.
                try:
                    _queue_recovered_g3(preserved)
                    log.warning("g3 sesi lama diamankan ke pending; sesi jendela sekarang tetap dibuka")
                except Exception as e:
                    log.exception("g3 sesi lama gagal diamankan: %s", e)
                    try:
                        _archive_session_file(SESSION_PATH, preserved)
                    except Exception as archive_error:
                        log.error("g3 arsip sesi lama juga gagal: %s", archive_error)
        label = current[1]
        opened_at = _session_start_ms_for_group(group, now)
        sess = {"chatId": group["cid"], "topicId": group["tid"], "openedAt": opened_at,
                "seen": set(), "links": [], "entries": [], "participants": {},
                "closed": False, "label": label, "handle_owner": {},
                "reported": set(), "member_cache": {}, "mpost": {}, "admin_uids": set()}
        ACTIVE[key] = sess
        if name == "g3":
            _save_g3_session(sess)
        else:
            _save_other_session(sess)
        log.info("%s active session initialized after restart label=%s", name, label)


def _resume_g3_session():
    if "g3" in PAUSED_GROUPS:
        return
    saved = _load_g3_session()
    if not saved:
        return
    current = _g3_session_at()
    saved_day = datetime.fromtimestamp(saved["openedAt"] / 1000, timezone.utc).date()
    current_day = datetime.now(timezone.utc).date()
    if current and current[1] == saved.get("sessionLabel") and saved_day == current_day:
        g3 = GROUPS["g3"]
        ACTIVE[(g3["cid"], g3["tid"])] = _restore_session_state(saved, g3["cid"], g3["tid"])
        log.info("g3 session resumed label=%s entries=%d", saved.get("sessionLabel"), len(saved.get("entries", [])))
        return
    if saved.get("entries"):
        closed_at = int(saved.get("openedAt") or datetime.now(timezone.utc).timestamp() * 1000)
        pending = {
            "topicId": GROUPS["g3"]["tid"],
            "chatId": GROUPS["g3"]["cid"],
            "sessionName": saved.get("sessionName"),
            "sessionLabel": saved.get("sessionLabel"),
            "closedAt": closed_at,
            "checkAt": _recovery_check_at(closed_at),
            "reportAt": _g3_report_due_ms(closed_at),
            "sessionId": f"recovered-{closed_at}-{GROUPS['g3']['cid']}-{GROUPS['g3']['tid']}",
            "entries": saved.get("entries", []),
            "links": list(saved.get("links") or []),
            "openedAt": saved.get("openedAt"),
            "linksFileSent": False,
            "participants": saved.get("participants", []),
            "adminUids": saved.get("adminUids", []),
            "mpost": saved.get("mpost", {}),
        }
        try:
            _save_pending_check(pending)
            log.info("g3 missed close recovered for checker label=%s", saved.get("sessionLabel"))
        except OSError as e:
            log.warning("g3 missed close recovery failed: %s", e)
            return
    _clear_g3_session()


def _next_g3_open_ms(now_ms=None):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else int(now_ms)
    now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    for day in (0, 1):
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight += timedelta(days=day)
        for oh, om, _, _ in GROUPS["g3"]["sch"]:
            candidate = int((midnight.timestamp() + (oh * 60 + om) * 60) * 1000)
            if candidate > now_ms:
                return candidate
    return now_ms + 24 * 60 * 60 * 1000


def _g3_check_due_ms(closed_at=None):
    return _next_g3_open_ms(closed_at) - CHECKER_LEAD_MINUTES * 60 * 1000


def _g3_report_due_ms(closed_at=None):
    return _g3_check_due_ms(closed_at)


def _recovery_check_at(closed_at=None):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    due_ms = _g3_check_due_ms(closed_at)
    return 0 if due_ms <= now_ms else due_ms


def _participant_name(participant):
    return participant.get("who") or f"id{participant.get('uid', 'unknown')}"


def _session_immune_uids(pending):
    """UID yang tidak boleh dilaporkan: protected + VIP + admin/creator yang
    sudah terdeteksi saat sesi berjalan + entry bertanda exempt (rekaman lama)."""
    immune = set(PROTECTED_IDS) | set(VIP_UIDS)
    for uid in (pending.get("adminUids") or []):
        try:
            immune.add(int(uid))
        except (TypeError, ValueError):
            continue
    for entry in (pending.get("entries") or []):
        if isinstance(entry, dict) and entry.get("exempt") and entry.get("uid") is not None:
            try:
                immune.add(int(entry["uid"]))
            except (TypeError, ValueError):
                continue
    return immune


def _analyze_g3(pending):
    """Analisis sesuai cara grup 2 (post patokan acak).

    - Peserta = SEMUA dropper sesi. Handle X diambil dari drop pertamanya.
    - Wajib komen post milik orang lain (post sendiri otomatis lolos, bebas
      berdasarkan UID penerima link -> anti farming).
    - Post yang tidak terverifikasi DIKECUALIKAN dari kewajiban (tidak boleh
      menuduh orang karena post yang tidak terbaca).
    - Orang kebal (protected/VIP/admin) tidak masuk hasil sama sekali.
    """
    cache = _fetch_cache(pending)
    immune = _session_immune_uids(pending)
    scope = _in_scope_tweet_ids(pending)
    entries = [e for e in (pending.get("entries") or []) if isinstance(e, dict)]

    # --- pool post (dedup per tweet id, uid = penerima link) ---
    posts = {}
    for entry in entries:
        link = norm_x(entry.get("link", ""))
        tweet_id = x_tweet_id(link)
        handle = parse_x_handle(link)
        if not tweet_id or not handle:
            continue
        key = str(tweet_id)
        if scope is not None and key not in scope:
            # di luar cakupan cek (hanya post patokan yang diperiksa)
            continue
        post = posts.get(key)
        if post is None:
            state = cache.get(key) or {}
            status = state.get("state") or POST_PENDING
            post = posts[key] = {
                "tweetId": key, "link": link, "handle": handle.lower(),
                "uid": entry.get("uid"), "who": entry.get("who"),
                "verified": status == POST_OK, "status": status,
                "reason": str(state.get("reason") or status),
                "commenters": {str(c).lower() for c in (state.get("commenters") or [])} if status == POST_OK else set(),
            }
        elif post.get("uid") is None:
            post["uid"] = entry.get("uid")
    verified = [p for p in posts.values() if p["verified"]]

    # --- peserta: semua dropper, handle dari drop pertamanya ---
    first_by_uid = {}
    for entry in entries:
        uid = entry.get("uid")
        if uid is None:
            continue
        key = str(uid)
        if key not in first_by_uid:
            first_by_uid[key] = entry
    source = pending.get("participants") or []
    if isinstance(source, dict):
        source = list(source.values())
    parts = []
    seen_keys = set()
    for participant in source:
        if not isinstance(participant, dict):
            continue
        uid = participant.get("uid")
        key = str(uid) if uid is not None else _participant_name(participant).lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        own = first_by_uid.get(key)
        link = own.get("link") if own else None
        handle = parse_x_handle(link) if link else None
        # ambiguous: tidak punya link sendiri di pool (hanya duplikat) atau tanpa uid
        parts.append({"uid": uid, "key": key.lower() if isinstance(key, str) else key,
                      "who": participant.get("who") or _participant_name(participant),
                      "handle": handle.lower() if handle else None,
                      "manual": (own is None or uid is None)})
    # peserta yang punya entry tapi somehow tidak tercatat di participants
    for entry in entries:
        uid = entry.get("uid")
        if uid is None:
            continue
        key = str(uid)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        handle = parse_x_handle(entry.get("link", ""))
        parts.append({"uid": uid, "key": key, "who": entry.get("who") or f"id{uid}",
                      "handle": handle.lower() if handle else None, "manual": handle is None})
    # bentrok handle: 2+ peserta dengan handle sama -> semuanya ambigu
    counts = {}
    for part in parts:
        if part["handle"]:
            counts[part["handle"]] = counts.get(part["handle"], 0) + 1
    for part in parts:
        if part["handle"] and counts[part["handle"]] > 1:
            part["manual"] = True

    results = []
    immune_count = 0
    for part in parts:
        try:
            if part["uid"] is not None and int(part["uid"]) in immune:
                immune_count += 1
                continue
        except (TypeError, ValueError):
            pass
        # bebas dari post yang link-nya milik dia (by UID), fallback by handle
        if part["uid"] is not None:
            required = [p for p in verified if p["uid"] is None or str(p["uid"]) != str(part["uid"])]
        else:
            required = [p for p in verified if p["handle"] != part["handle"]]
        missed = [p for p in required if not part["handle"] or part["handle"] not in p["commenters"]]
        results.append({
            "uid": part["uid"], "who": part["who"], "handle": part["handle"] or "-",
            "manual": bool(part["manual"]),
            "required": len(required), "commented": len(required) - len(missed),
            "missed": len(missed),
            "missedPosts": [{"link": p["link"], "owner": p["handle"]} for p in missed],
            "complete": not missed,
        })
    results.sort(key=lambda item: (item["complete"], -item["missed"], str(item["handle"]).lower()))
    unreadable = [p for p in posts.values() if not p["verified"]]
    return {
        "results": results,
        "defaulters": [r for r in results if not r["complete"]],
        "participants": len(results),
        "immune": immune_count,
        "posts": len(posts),
        "checked": len(verified),
        "pending": sum(1 for p in unreadable if p["status"] == POST_PENDING),
        "unreadable": sum(1 for p in unreadable if p["status"] == POST_UNREADABLE),
        "unverified": len(unreadable),
        "coverageComplete": bool(posts) and not unreadable,
        # Post patokan = post yang benar-benar terverifikasi (dipakai proof link)
        "proofLink": (verified[0]["link"] if verified
                      else (next(iter(posts.values()))["link"] if posts else "-")),
        "readablePosts": [p["link"] for p in verified],
        "unverifiedDetails": [{"link": p["link"], "owner": p["handle"], "reason": p["reason"]}
                              for p in unreadable],
    }


def _missed_owner_names(item):
    return [f"@{p['owner']}" for p in (item.get("missedPosts") or []) if p.get("owner")]


def _checker_summary(pending, analysis):
    """Pesan ringkas ke topic — sama dengan grup 2 (renderCheckMessage, en)."""
    label = pending.get("sessionLabel") or pending.get("sessionName") or "Session"
    lines = [f"CHECK {label}"]
    if not analysis["participants"]:
        lines.append("No posts could be checked.")
        return "\n".join(lines)
    lines.append(f"Participants: {analysis['participants']} | Posts checked: {analysis['checked']} "
                 f"| Unverified: {analysis['unverified']}")
    lines.append("")
    for item in analysis["results"]:
        if item["complete"]:
            lines.append(f"✅ @{item['handle']} — {item['commented']}/{item['required']}")
        else:
            lines.append(f"❌ @{item['handle']} — {item['commented']}/{item['required']} "
                         f"(miss: {', '.join(_missed_owner_names(item))})")
    if analysis["unverifiedDetails"]:
        lines.append("")
        for u in analysis["unverifiedDetails"]:
            owner = f"post @{u['owner']}" if u.get("owner") else (u.get("who") or "post")
            lines.append(f"⚠️ Could not check: {owner} — {u.get('reason') or '-'}")
    return "\n".join(lines)


def _format_defaulters(pending, analysis):
    """Format FINAL file defaulter — sama persis dengan grup 2
    (src/checker.js: formatDefaulters).

    Daftar = USERNAME TELEGRAM peserta yang tidak komen di post patokan.
    Pemilik post patokan otomatis tidak masuk daftar. 1 link acak sebagai bukti.
    """
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    name = pending.get("sessionName") or pending.get("sessionLabel") or "Session"
    lines = [f"Defaulters: {name}", f"Check time: {stamp}", ""]
    defaulters = analysis.get("defaulters") or []
    if not defaulters:
        lines.append("(no defaulters - everyone commented on the post)")
    else:
        seen = set()
        index = 0
        for item in defaulters:
            who = str(item.get("who") or "").strip()
            if not who:
                uid = item.get("uid")
                who = f"uid{uid}" if uid is not None else "unknown"
            key = who.lower()
            if key in seen:          # satu username Telegram cukup sekali
                continue
            seen.add(key)
            index += 1
            lines.append(f"{index}. {who}{' (cek manual)' if item.get('manual') else ''}")
    lines += ["", "Proof link for example:", analysis.get("proofLink") or "-"]
    return "\n".join(lines)


def _checker_caption(pending, analysis):
    # string persis dari grup 2 i18n: 'Check {label} (topic {topicId}): {participants} participants, {incomplete} incomplete'
    name = pending.get("sessionLabel") or pending.get("sessionName") or "Session"
    incomplete = len(analysis.get("defaulters") or [])
    return (f"Check {name} (topic {pending.get('topicId', '-')}): "
            f"{analysis['participants']} participants, {incomplete} incomplete")


X_BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
X_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def _x_headers(ct0):
    return {
        "authorization": X_BEARER,
        "cookie": f"auth_token={X_AUTH_TOKEN}; ct0={ct0}",
        "x-csrf-token": ct0,
        "content-type": "application/json",
        "user-agent": X_USER_AGENT,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "accept": "*/*",
    }


def _x_url(query_id, tweet_id, cursor=None):
    variables = {
        "focalTweetId": str(tweet_id),
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
    }
    if cursor:
        variables["cursor"] = cursor
    field_toggles = {
        "withArticleRichContentState": True,
        "withArticlePlainText": False,
        "withGrokAnalyze": False,
        "withDisallowedReplyControls": False,
    }
    return f"https://x.com/i/api/graphql/{query_id}/TweetDetail?{urlencode({'variables': json.dumps(variables, separators=(',', ':')), 'fieldToggles': json.dumps(field_toggles, separators=(',', ':'))})}"


def _collect_x_tweets(node, acc):
    if isinstance(node, list):
        for item in node:
            _collect_x_tweets(item, acc)
        return acc
    if not isinstance(node, dict):
        return acc
    cursor_type = node.get("cursorType")
    if isinstance(cursor_type, str) and cursor_type.startswith("Bottom") and node.get("value") is not None:
        acc["cursor"] = str(node["value"])
    if isinstance(node.get("rest_id"), str):
        core = node.get("core") if isinstance(node.get("core"), dict) else {}
        user_results = core.get("user_results") if isinstance(core.get("user_results"), dict) else {}
        result = user_results.get("result") if isinstance(user_results.get("result"), dict) else {}
        legacy = node.get("legacy") if isinstance(node.get("legacy"), dict) else {}
        result_legacy = result.get("legacy") if isinstance(result.get("legacy"), dict) else {}
        result_core = result.get("core") if isinstance(result.get("core"), dict) else {}
        user = result_legacy.get("screen_name") or result_core.get("screen_name")
        if user:
            reply_to = legacy.get("in_reply_to_status_id_str")
            acc["tweets"].append({"id": node["rest_id"], "user": str(user).lower(), "replyTo": str(reply_to) if reply_to is not None else None})
        elif "user_results" in core:
            acc["unresolved"] = acc.get("unresolved", 0) + 1
    for key, value in node.items():
        if key in {"quoted_status_result", "quotedRefResult"}:
            continue
        _collect_x_tweets(value, acc)
    return acc


def _x_page(payload, tweet_id, known_ids=None, focal_user=None):
    data = payload.get("data") if isinstance(payload, dict) else None
    conversation = data.get("threaded_conversation") if isinstance(data, dict) else None
    root = conversation if isinstance(conversation, (dict, list)) else payload
    collected = _collect_x_tweets(root, {"tweets": [], "cursor": None, "unresolved": 0})
    focal_id = str(tweet_id)
    cursor = collected.get("cursor")
    focal = next((x for x in collected["tweets"] if x["id"] == focal_id), None)
    if focal is not None:
        if focal_user is not None and focal["user"] != focal_user:
            return False, set(), cursor, set(known_ids or {focal_id}), focal["user"], False, collected.get("unresolved", 0)
        focal_user = focal["user"]
    elif focal_user is None or not collected["tweets"]:
        # Post tidak ada di halaman ini. Kalau halamannya benar-benar kosong
        # (0 tweet), itu TIDAK mungkin halaman continuation yang sah: artinya
        # respons X tidak berguna (cursor lama kedaluwarsa / respons rusak).
        # Wajib dilaporkan sebagai "tidak ditemukan" supaya tidak salah
        # dianggap thread yang sudah habis lengkap.
        return False, set(), cursor, set(), None, False, collected.get("unresolved", 0)
    known = set(known_ids or {focal_id})
    known.add(focal_id)
    authors = {
        x["user"] for x in collected["tweets"]
        if x["id"] != focal_id and x["user"] != focal_user
    }
    return True, authors, cursor, known, focal_user, False, collected.get("unresolved", 0)


def _read_cached_query_id():
    try:
        with open(X_QUERY_ID_PATH, encoding="utf-8") as f:
            value = json.load(f).get("queryId")
        if value:
            return str(value)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return X_QUERY_ID


def _cache_query_id(value):
    global X_QUERY_ID
    if not value:
        return
    X_QUERY_ID = str(value)
    try:
        _atomic_write(X_QUERY_ID_PATH, json.dumps({"queryId": X_QUERY_ID, "savedAt": int(datetime.now(timezone.utc).timestamp() * 1000)}))
    except OSError:
        pass


def _read_cached_ct0():
    try:
        with open(X_CT0_PATH, encoding="utf-8") as f:
            value = f.read().strip()
        return value or None
    except OSError:
        return None


def _cache_ct0(value):
    global X_CT0
    if not value:
        return
    X_CT0 = str(value)
    try:
        _atomic_write(X_CT0_PATH, X_CT0)
        os.chmod(X_CT0_PATH, 0o600)
    except OSError:
        pass


async def _refresh_x_query_id(session):
    try:
        async with session.get("https://x.com/home", headers={"user-agent": X_USER_AGENT, "accept": "text/html", "cookie": f"auth_token={X_AUTH_TOKEN}; ct0={X_CT0}"}, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                return None
            html = await response.text()
        bundles = re.findall(r'''https://abs\.twimg\.com/responsive-web/client-(?:web|server)/[^"']+\.js''', html)
        bundles = list(dict.fromkeys(bundles))
        candidates = [bundle for bundle in bundles if "/main." in bundle]
        if not candidates:
            candidates = bundles
        for bundle in reversed(candidates):
            async with session.get(bundle, headers={"user-agent": X_USER_AGENT}, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    continue
                js = await response.text()
            patterns = [r'queryId\s*:\s*"([A-Za-z0-9_-]+)"\s*,\s*operationName\s*:\s*"TweetDetail"', r'operationName\s*:\s*"TweetDetail".*?queryId\s*:\s*"([A-Za-z0-9_-]+)"']
            for pattern in patterns:
                match = re.search(pattern, js)
                if match:
                    return match.group(1)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None


async def _refresh_x_ct0(session):
    try:
        async with session.get("https://x.com/home", headers={"cookie": f"auth_token={X_AUTH_TOKEN}", "user-agent": X_USER_AGENT}, timeout=aiohttp.ClientTimeout(total=20)) as response:
            cookies = response.headers.getall("Set-Cookie", [])
        for cookie in cookies:
            match = re.search(r"(?:^|;\s*)ct0=([^;]+)", cookie)
            if match:
                return match.group(1)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None


async def _fetch_x_replies_once(session, tweet_id, ct0, query_id, page_delay, expected_handle=None, resume=None):
    """Baca SEMUA komentar satu post sampai cursor habis (batas atas MAX_PAGES).

    resume: {commenters, cursor, pages, unresolved} dari percobaan sebelumnya,
    supaya 429 di tengah tidak mengulang dari halaman 1. Kalau cursor tersimpan
    sudah tidak berlaku, fungsi ini mengulang dari awal (cursor=None) dan
    hanya menandai complete kalau seluruh halaman benar-benar terbaca.
    """
    authors = set()
    known_ids = {str(tweet_id)}
    focal_user = str(expected_handle).lower() if expected_handle else None
    cursor = None
    pages = 0
    unresolved_total = 0
    seen_cursors = set()
    resumed = False
    if isinstance(resume, dict) and resume.get("cursor"):
        authors = {str(c).lower() for c in (resume.get("commenters") or [])}
        cursor = str(resume["cursor"])
        pages = int(resume.get("pages") or 0)
        unresolved_total = int(resume.get("unresolved") or 0)
        resumed = True
    cap = CHECKER_REPLY_CAP if CHECKER_REPLY_CAP > 0 else None

    def restart(reason):
        """Cursor lama tidak berlaku -> baca ulang dari awal."""
        return {"verified": True, "commenters": [], "pages": 0, "truncated": False,
                "capped": False, "cursorAmbiguous": False, "unresolvedUsers": 0,
                "complete": False, "restart": True, "reason": reason,
                "resume": {"commenters": [], "cursor": None, "pages": 0, "unresolved": 0}}

    while pages < CHECKER_MAX_PAGES:
        if cursor is not None:
            if cursor in seen_cursors:
                return {"verified": True, "commenters": sorted(authors), "pages": pages,
                        "truncated": True, "capped": False, "complete": False,
                        "reason": "cursor pagination berulang", "resumed": resumed,
                        "resume": {"commenters": sorted(authors), "cursor": cursor,
                                   "pages": pages, "unresolved": unresolved_total}}
            seen_cursors.add(cursor)
        if resumed and pages == 0:
            log.info("checker: %s dilanjutkan dari cursor halaman %s (%s komentar sudah terkumpul)",
                     tweet_id, pages, len(authors))
        try:
            async with session.get(_x_url(query_id, tweet_id, cursor), headers=_x_headers(ct0), timeout=aiohttp.ClientTimeout(total=45)) as response:
                status = response.status
                if status == 400:
                    return {"verified": False, "reason": "queryId tidak valid (HTTP 400)", "http": status, "staleQueryId": True}
                if status in {401, 403}:
                    return {"verified": False, "reason": f"sesi X ditolak (HTTP {status})", "http": status, "authFail": True}
                if status == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = float(retry_after)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                    # progres ikut dibawa supaya percobaan berikutnya lanjut
                    # dari halaman ini, bukan mengulang dari halaman 1
                    return {"verified": False, "reason": "rate limit X (HTTP 429)", "http": status,
                            "rateLimited": True, "retryAfter": retry_after,
                            "resume": {"commenters": sorted(authors), "cursor": cursor,
                                       "pages": pages, "unresolved": unresolved_total}}
                if status < 200 or status >= 300:
                    return {"verified": False, "reason": f"HTTP {status}", "http": status,
                            "resume": {"commenters": sorted(authors), "cursor": cursor,
                                       "pages": pages, "unresolved": unresolved_total}}
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            return {"verified": False, "reason": f"fetch gagal: {e}",
                    "resume": {"commenters": sorted(authors), "cursor": cursor,
                               "pages": pages, "unresolved": unresolved_total}}
        if isinstance(payload, dict) and payload.get("errors"):
            first_error = payload["errors"][0] if isinstance(payload["errors"], list) and payload["errors"] else {}
            message = first_error.get("message", "?") if isinstance(first_error, dict) else str(first_error)
            return {"verified": False, "reason": f"API error: {message}", "http": status, "staleQueryId": True}
        if not isinstance(payload, dict) or "data" not in payload:
            return restart("respons X tidak memuat data")
        focal_found, page_authors, cursor, known_ids, focal_user, _, page_unresolved = _x_page(payload, tweet_id, known_ids, focal_user)
        unresolved_total += page_unresolved
        if not focal_found:
            if resumed:
                # Cursor lama tidak berlaku -> ulang dari awal, jangan tandai complete.
                return restart("cursor lama tidak berlaku")
            if expected_handle and focal_user and focal_user != str(expected_handle).lower():
                return {"verified": False, "reason": "handle URL tidak cocok dengan pemilik post X", "http": status, "ownerMismatch": True}
            return {"verified": False, "reason": "post tidak ditemukan di respons X", "http": status}
        authors.update(page_authors)
        pages += 1
        served_now = len(page_authors) + (1 if focal_found else 0)
        if cap is not None and len(authors) >= cap:
            return {"verified": True, "commenters": sorted(authors), "pages": pages, "truncated": False,
                    "capped": True, "cursorAmbiguous": False, "unresolvedUsers": unresolved_total,
                    "complete": False, "resumed": resumed,
                    "resume": {"commenters": sorted(authors), "cursor": cursor,
                               "pages": pages, "unresolved": unresolved_total}}
        if not cursor:
            # Cursor lama bisa saja sudah kedaluwarsa: X membalas halaman kosong.
            # Itu bukan berarti thread habis. Kalau kita melanjutkan dari cursor
            # dan halamannya kosong tanpa cursor -> baca ulang dari awal, JANGAN
            # tandai lengkap (kalau tidak, orang yang komentar di halaman yang
            # terlewat akan dituduh salah).
            if resumed and not served_now:
                return restart("cursor lama tidak berlaku (halaman kosong)")
            # Thread habis -> baru boleh disebut lengkap.
            log.info("checker: %s selesai di halaman %s%s", tweet_id, pages,
                     " (dilanjutkan dari cursor sebelumnya)" if resumed else "")
            return {"verified": True, "commenters": sorted(authors), "pages": pages, "truncated": False,
                    "capped": False, "cursorAmbiguous": False, "unresolvedUsers": unresolved_total,
                    "complete": unresolved_total == 0, "resumed": resumed,
                    "resume": {"commenters": sorted(authors), "cursor": None,
                               "pages": pages, "unresolved": unresolved_total}}
        if page_delay > 0:
            await asyncio.sleep(page_delay)
    return {"verified": True, "commenters": sorted(authors), "pages": pages, "truncated": True,
            "capped": False, "cursorAmbiguous": False, "unresolvedUsers": unresolved_total,
            "complete": False, "reason": f"melebihi batas {CHECKER_MAX_PAGES} halaman", "resumed": resumed,
            "resume": {"commenters": sorted(authors), "cursor": cursor,
                       "pages": pages, "unresolved": unresolved_total}}


async def _fetch_x_replies_robust(session, tweet_id, expected_handle=None, resume=None):
    global X_RATE_LIMIT_UNTIL
    ct0 = _read_cached_ct0() or X_CT0
    query_id = _read_cached_query_id()
    rate_attempt = 0
    while True:
        wait = max(0.0, X_RATE_LIMIT_UNTIL - time.monotonic())
        if wait > 0:
            await asyncio.sleep(wait)
        result = await _fetch_x_replies_once(session, tweet_id, ct0, query_id, CHECKER_PAGE_DELAY, expected_handle, resume)
        if result.get("staleQueryId"):
            fresh = await _refresh_x_query_id(session)
            if fresh:
                query_id = fresh
                _cache_query_id(fresh)
                result = await _fetch_x_replies_once(session, tweet_id, ct0, query_id, CHECKER_PAGE_DELAY, expected_handle, resume)
        if result.get("authFail"):
            fresh_ct0 = await _refresh_x_ct0(session)
            if fresh_ct0 and fresh_ct0 != ct0:
                ct0 = fresh_ct0
                _cache_ct0(fresh_ct0)
                result = await _fetch_x_replies_once(session, tweet_id, ct0, query_id, CHECKER_PAGE_DELAY, expected_handle, resume)
        if result.get("rateLimited"):
            # 429 di tengah: simpan progres per halaman lalu lanjut dari sana.
            # Kalau tidak ada progres tersimpan, hasilnya percobaan terakhir.
            if isinstance(result.get("resume"), dict):
                resume = result["resume"]
            if rate_attempt < CHECKER_RATE_LIMIT_RETRIES:
                delay = max(float(result.get("retryAfter") or 0), CHECKER_RATE_LIMIT_BASE_SECONDS * (2 ** rate_attempt))
                X_RATE_LIMIT_UNTIL = time.monotonic() + delay
                rate_attempt += 1
                await asyncio.sleep(delay)
                continue
        return result


GROUPS = {
    "g1": {"cid": -1002288455639, "tid": 3920,
        "om": "\U0001f513Session {session} Open Now Everyone.\n\n\U0001f517Drop Your Post Link\U0001f447",
        "cm": "\U0001f512Session Closed. \n\n\U0001f4ca Total Posts Submitted: {total}\n\n⏰Complete all engagement in 3 hours.\n\n\U0001f6abIf you skip link = Warn/Ban.\n1️⃣No/Skip community post.\n2️⃣Smart replied = 7+ more words.\n\n\U0001f44d \"Done\" in the Approval Channel to confirm that your engagement is complete. ",
        "sch": [(5,0,5,30),(9,0,9,30),(13,0,13,30),(17,0,17,30)]},
    "g2": {"cid": -1003445459351, "tid": 14,
        "om": "\U0001f680 ENGAGE ORBIT SESSION START!\n\nDrop your links now! Let\u2019s boost each other. \U0001f513",
        "cm": "Session closed \U0001f4f8\n\nComplete all engagement in 3 hours.\n\nIf you skip any link = Warn\n1. No/Skip community post\n2. Smart replies = 4 or more words\n\n\U0001f942Total Links: {total}\n\nLinks available in the file above",
        "sch": [(5,30,6,0),(10,30,11,0),(14,30,15,0),(18,30,19,0)]},
    "g3": {"cid": -1004398227454, "tid": 868,
        "om": "\U0001f4c5 POSTING SESSION START!\n\nDrop your post links now! Session open for 5 minutes \u23f3",
        "cm": "SESSION CLOSED\u2705\n\n\u2705Engage.\u2705 Drop a Reaction. \U0001f525 Sign Out.\n\n\U0001f942Total Links: {total}\n\u26a0\ufe0f2 Warnings = Mute/Ban\n\nLinks available in the file above",
        "sch": [(5,0,5,5),(9,0,9,5),(14,0,14,5),(18,0,18,5)]},
}

def _queue_recovered_g3(saved):
    if not saved:
        return
    if saved.get("entries"):
        closed_at = int(saved.get("openedAt") or datetime.now(timezone.utc).timestamp() * 1000)
        pending = {
            "topicId": GROUPS["g3"]["tid"],
            "chatId": GROUPS["g3"]["cid"],
            "sessionName": saved.get("sessionName"),
            "sessionLabel": saved.get("sessionLabel"),
            "closedAt": closed_at,
            "checkAt": _recovery_check_at(closed_at),
            "reportAt": _g3_report_due_ms(closed_at),
            "sessionId": f"recovered-{closed_at}-{GROUPS['g3']['cid']}-{GROUPS['g3']['tid']}",
            "entries": saved.get("entries", []),
            "links": list(saved.get("links") or []),
            "openedAt": saved.get("openedAt"),
            # File link BELUM terkirim: bot mati di tengah sesi, jadi job
            # deliver_pending_link_files yang mengirimnya (tarik dari Telegram
            # pakai userbot kalau links kosong).
            "linksFileSent": False,
            "participants": saved.get("participants", []),
            "adminUids": saved.get("adminUids", []),
            "mpost": saved.get("mpost", {}),
        }
        _save_pending_check(pending)
    _clear_g3_session()


def _arm_recovered_s4():
    if "g3" in PAUSED_GROUPS:
        return None
    if not CHECKER_ENABLED:
        return None
    try:
        with open(RECOVERED_S4_PATH, encoding="utf-8") as f:
            recovered = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(recovered, dict) or recovered.get("status") != "recovered_not_armed" or not recovered.get("entries"):
        return None
    closed_at = int(recovered.get("closedAt") or datetime.now(timezone.utc).timestamp() * 1000)
    session_id = f"recovered-s4-{closed_at}"
    pending = {
        "topicId": GROUPS["g3"]["tid"],
        "chatId": GROUPS["g3"]["cid"],
        "sessionName": recovered.get("sessionName") or "Sesi 4",
        "sessionLabel": recovered.get("sessionLabel") or "Sesi 4 | 18:00-18:05 UTC",
        "closedAt": closed_at,
        "checkAt": _recovery_check_at(closed_at),
        "reportAt": _g3_report_due_ms(closed_at),
        "sessionId": session_id,
        "entries": recovered.get("entries", []),
        "participants": recovered.get("participants", []),
        "adminUids": recovered.get("adminUids", []),
        "mpost": recovered.get("mpost", {}),
        "sourceUrl": recovered.get("sourceUrl"),
        "recovered": True,
    }
    _save_pending_check(pending)
    recovered["status"] = "armed"
    recovered["armedAt"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    recovered["pendingSessionId"] = session_id
    _atomic_write(RECOVERED_S4_PATH, json.dumps(recovered, ensure_ascii=False, indent=2))
    log.info("recovered S4 armed for checker due=%s", datetime.fromtimestamp(pending["checkAt"] / 1000, timezone.utc).isoformat())
    return pending


async def do_open(g, session_number=None):
    c, t = g["cid"], g["tid"]
    log.info("OPEN %s/%s", c, t)
    opened_at = int(datetime.now(timezone.utc).timestamp() * 1000)
    is_g3 = (c, t) == (GROUPS["g3"]["cid"], GROUPS["g3"]["tid"])
    old_path = SESSION_PATH if is_g3 else _session_path(t)
    old = _load_g3_session() if is_g3 else _load_other_session(t, c)
    if old and int(old.get("openedAt") or 0) != opened_at:
        try:
            if is_g3:
                _queue_recovered_g3(old)
            else:
                _archive_session_file(old_path, old)
        except OSError as e:
            log.warning("OPEN aborted because prior session could not be preserved: %s", e)
            return
    sess = {"chatId": c, "topicId": t, "openedAt": opened_at,
            "seen": set(), "links": [], "entries": [], "participants": {},
            "closed": False, "label": session_label(g, session_number), "handle_owner": {},
            "reported": set(), "member_cache": {}, "mpost": {}, "admin_uids": set()}
    ACTIVE[(c, t)] = sess
    try:
        if is_g3:
            _save_g3_session(sess)
        else:
            _save_other_session(sess)
        if t:
            opened = await api("reopenForumTopic", chat_id=c, message_thread_id=t)
            if not opened.get("ok"):
                raise RuntimeError(f"reopen topic failed: {opened.get('description', 'unknown')}")
        # {session} diganti nomor sesi berjalan. g2/g3 tidak punya placeholder ini.
        announced = await send(c, g["om"].replace("{session}", str(session_number or 1)), t)
        if not announced.get("ok"):
            log.warning("OPEN announcement failed %s/%s: %s", c, t, announced.get("description", "unknown"))
    except Exception as e:
        sess["openError"] = str(e)[:300]
        try:
            if is_g3:
                _save_g3_session(sess)
            else:
                _save_other_session(sess)
        except OSError as save_error:
            log.warning("OPEN state could not be preserved: %s", save_error)
        log.exception("OPEN failed but state retained %s/%s", c, t)
        return
    log.info("OPEN done %s", c)

LAST_OFFSET = None


async def _drain_pending_updates(limit=20):
    """Proses update getUpdates yang masih antre. Dipakai sebelum file link
    dikirim saat sesi ditutup supaya tidak ada link yang drop saat close hilang."""
    global LAST_OFFSET
    if LAST_OFFSET is None:
        return 0
    processed = 0
    for _ in range(limit):
        try:
            d = await api("getUpdates", client_timeout=15.0, offset=LAST_OFFSET, timeout=0)
        except Exception as e:
            log.warning("drain getUpdates gagal: %s", e)
            break
        if not d.get("ok"):
            break
        result = d.get("result") or []
        if not result:
            break
        for upd in result:
            uid_upd = upd.get("update_id")
            try:
                await handle_update(upd)
            except Exception as e:
                log.exception("drain handle_update gagal update_id=%s: %s", uid_upd, e)
            if uid_upd is not None:
                LAST_OFFSET = int(uid_upd) + 1
                processed += 1
    return processed


async def do_close(g):
    c, t = g["cid"], g["tid"]
    log.info("CLOSE %s/%s", c, t)
    sess = ACTIVE.get((c, t))
    g3_close = bool(sess and (c, t) == (GROUPS["g3"]["cid"], GROUPS["g3"]["tid"]))
    if g3_close and sess:
        # 0. Tandai batas atas sesi SEBELUM drain/sweep, jadi _sweep_g3_links
        #    hanya menarik pesan di antara buka dan tutup - tidak lebih.
        sess["closedAt"] = int(datetime.now(timezone.utc).timestamp() * 1000)
        # 1. Proses update yang masih antre: link yang drop 1-2 detik sebelum
        #    tutup tidak boleh hilang hanya karena bot belum sempat memproses.
        try:
            drained = await asyncio.wait_for(_drain_pending_updates(20), timeout=30)
            if drained:
                log.warning("CLOSE DRAIN: %d update diproses sebelum file dikirim", drained)
        except Exception as e:
            log.warning("drain update sebelum close gagal: %s", e)
        # 2. Tarik link member langsung dari Telegram (jaring pengaman).
        try:
            added = await asyncio.wait_for(_sweep_g3_links(sess), timeout=90)
            if added:
                log.warning("CLOSE SWEEP: %d link tertinggal dipulihkan sebelum file dikirim", added)
        except Exception as e:
            log.warning("sweep link sebelum close gagal (file tetap dikirim): %s", e)
    if sess:
        sess["closed"] = True
    if t:
        try:
            await api("closeForumTopic", chat_id=c, message_thread_id=t)
        except Exception as e:
            log.warning("close topic failed %s/%s: %s", c, t, e)
    total = len(sess["links"]) if sess else 0
    pending_saved = not (g3_close and sess.get("entries"))
    if g3_close and sess.get("entries"):
        closed_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        pending = {
            "topicId": t,
            "chatId": c,
            "sessionName": sess["label"].split(" | ", 1)[0],
            "sessionLabel": sess["label"],
            "closedAt": closed_at,
            "checkAt": _g3_check_due_ms(closed_at),
            "reportAt": _g3_report_due_ms(closed_at),
            "sessionId": f"{closed_at}-{c}-{t}",
            "entries": sess["entries"],
            "links": list(sess.get("links", [])),
            "participants": list(sess.get("participants", {}).values()),
            "adminUids": sorted(str(u) for u in sess.get("admin_uids", set())),
            "mpost": sess.get("mpost", {}),
        }
        try:
            _save_pending_check(pending)
            pending_saved = True
            log.info("g3 pending checker saved label=%s entries=%d links=%d participants=%d", sess["label"], len(sess["entries"]), len(sess.get("links", [])), len(sess.get("participants", {})))
        except Exception as e:
            # JANGAN biarkan ini mematikan sisa alur close: pesan tutup + file
            # link tetap harus terkirim (ValueError/TypeError ikut tertangkap).
            log.exception("g3 pending checker save gagal, link file tetap dikirim: %s", e)
    # WAJIB: pesan close dicoba lebih keras (attempts dinaikkan) supaya gangguan
    # jaringan sesaat tidak membuat file link hilang. Kalau pesan close tetap
    # gagal, file link TETAP dikirim - link yang sudah terkumpul tidak boleh
    # dibuang hanya karena pesan close gagal.
    close_text = g["cm"].replace("{total}", str(total))
    try:
        msg_ok = await send(c, close_text, t, attempts=max(TG_RETRY_ATTEMPTS, 6))
    except Exception as e:
        log.error("pesan close gagal (%s): %s", c, e)
        msg_ok = None
    if not (isinstance(msg_ok, dict) and msg_ok.get("ok")):
        log.error("pesan close TIDAK terkirim %s/%s: %s - file link TETAP dikirim",
                  c, t, (msg_ok or {}).get("description", "?") if isinstance(msg_ok, dict) else "?")
    sess = ACTIVE.pop((c, t), None)
    file_sent = True
    if sess and sess["links"]:
        file_sent = await send_link_file(c, t, sess["label"], sess["links"])
        if g3_close:
            _mark_link_file_sent(file_sent, sess["label"])
    if g3_close and (pending_saved or not sess or not sess.get("entries")):
        _clear_g3_session()
    elif not g3_close and sess and file_sent:
        _clear_other_session(t)
    _save_x_owners()
    log.info("CLOSE done %s", c)

async def reconcile_sessions():
    """Jaring pengaman: kalau cron open/close somehow terlewat (misfire, restart,
    event loop sibuk), sesi yang harusnya buka/tutup dikembalikan keadaannya.
    Idempoten: tidak melakukan apa pun kalau memang sudah sesuai."""
    now = datetime.now(timezone.utc)
    for name, group in GROUPS.items():
        if name in PAUSED_GROUPS:
            continue
        key = (group["cid"], group["tid"])
        current = _session_at_for_group(group, now)
        sess = ACTIVE.get(key)
        if current and (sess is None or sess.get("closed")):
            log.warning("RECONCILE: %s sesi %s belum aktif, dibuka sekarang", name, current[1])
            try:
                await do_open(group, current[0] + 1)
            except Exception as e:
                log.exception("reconcile open %s gagal: %s", name, e)
        elif not current and sess is not None and not sess.get("closed"):
            log.warning("RECONCILE: %s sesi %s masih aktif padahal window sudah lewat, ditutup", name, sess.get("label"))
            try:
                await do_close(group)
            except Exception as e:
                log.exception("reconcile close %s gagal: %s", name, e)


async def _guard_manual_list():
    """Jaring pengaman file cek manual G3: untuk SETIAP sesi g3 yang sudah lewat
    jadwal manual-list (40 menit sebelum sesi g3 berikutnya buka) tapi belum
    tercatat terkirim - mis. bot mati tepat di jam kirim - file dikirim ulang
    otomatis sampai terkirim. Hanya g3."""
    if not MANUAL_LIST_TARGET:
        return
    records = [r for r in _read_pending_records() if isinstance(r, dict)]
    if not records:
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ledger = _read_manual_ledger()
    for pending in records:
        closed_ms = _pending_time_ms(pending)
        if not closed_ms:
            continue
        key = _manual_session_key(pending)
        if not key:
            continue
        due_ms = _next_g3_open_ms(closed_ms) - MANUAL_LIST_LEAD_MINUTES * 60 * 1000
        # Beri kesempatan cron g3_listN dulu (misfire_grace 300 dtk); baru
        # bertindak setelah lewat tenggang. Di luar jendela lookback: jangan
        # kirim file basi.
        if now_ms < due_ms + MISSED_GRACE_MIN * 60 * 1000:
            continue
        if now_ms - due_ms > MISSED_LOOKBACK_MIN * 60 * 1000:
            continue
        rec = ledger.get(key) if isinstance(ledger.get(key), dict) else {}
        if rec.get("sentAt"):
            continue
        label = pending.get("sessionLabel") or "Session"
        sent = await send_manual_list(pending)
        if sent:
            log.warning("GUARD manual list: sesi terlewat %s, dikirim ulang ke developer", label)
            ledger = _read_manual_ledger()


async def _sweep_g3_links(sess):
    """Tarik isi topic sesi g3 langsung dari Telegram, merge link yang belum
    tercatat. Mengembalikan jumlah link yang ditambahkan.

    Dipakai dua kali: berkala (self-healing) dan SATU KALI PAS LANGSUNG
    SEBELUM file link dikirim saat sesi ditutup, supaya tidak ada link member
    yang tertinggal di Telegram tapi tidak masuk links.txt.
    """
    if sess is None or WATCHDOG is None:
        return 0
    try:
        ent = await WATCHDOG.get_input_entity(GROUPS["g3"]["cid"])
        tid = GROUPS["g3"]["tid"]
        opened = int(sess.get("openedAt") or 0)
        # closedAt diisi do_close tepat saat sesi ditutup. Batas atas dipakai
        # supaya pesan setelah sesi ditutup tidak ikut masuk ke txt sesi ini.
        closed = int(sess.get("closedAt") or 0)
        known_ids = {e.get("messageId") for e in sess.get("entries", []) if e.get("messageId")}
        names = dict(sess.get("_name_cache") or {})
        added = scanned = fetched = 0
        hit_window_end = False
        # PENTING: JANGAN pakai `reply_to=` di sini. reply_to memanggil
        # messages.GetRepliesRequest = "balasan LANGSUNG untuk sebuah pesan",
        # BUKAN "semua pesan di dalam topic". Link yang ditulis member tanpa
        # membalas pesan tertentu tidak akan pernah terlihat, sehingga link
        # yang hilang dari txt tidak pernah bisa dipulihkan. Topic dicek di
        # sisi klien lewat reply_to_top_id.
        async for msg in WATCHDOG.iter_messages(ent, limit=G3_SWEEP_LIMIT):
            fetched += 1
            stamp = int(msg.date.timestamp() * 1000) if msg.date else 0
            if stamp and stamp < opened - 2000:
                hit_window_end = True
                break                      # sudah melewati awal sesi -> selesai
            if stamp and closed and stamp > closed + G3_SWEEP_GRACE_MS:
                continue                   # di luar sesi ini -> bukan milik sesi ini
            header = getattr(msg, "reply_to", None)
            top = getattr(header, "reply_to_top_id", None) if header else None
            if top != tid and getattr(msg, "reply_to_msg_id", None) != tid:
                continue                   # bukan pesan di topic sesi ini
            scanned += 1
            if msg.id in known_ids:
                continue                  # sudah pernah tercatat
            links = _links_from_text(msg.text) or _links_from_text(getattr(msg, "caption", None))
            if not links:
                continue
            if msg.sender_id and msg.sender_id not in names:
                try:
                    ent_u = await WATCHDOG.get_entity(msg.sender_id)
                    names[msg.sender_id] = (getattr(ent_u, "username", None),
                                            getattr(ent_u, "first_name", None))
                except Exception:
                    names[msg.sender_id] = (None, None)
            uname, fname = names.get(msg.sender_id, (None, None))
            who = f"@{uname}" if uname else (fname or f"id{msg.sender_id}")
            for link in links:
                k = norm_x(link)
                sess["seen"].add(k)
                # Dedup hanya per-pesan: pesan yang sama + link yang sama tidak
                # digandakan. Link identik dari pesan/member lain tetap masuk.
                if _link_already_recorded(sess, msg.id, k):
                    continue
                _record_link(sess, msg.id, k)
                sess["links"].append(k)
                sess.setdefault("entries", []).append({
                    "link": k, "who": who, "uid": msg.sender_id, "exempt": False,
                    "atMs": stamp or opened, "messageId": msg.id, "backfilled": True,
                })
                if msg.sender_id is not None:
                    sess.setdefault("participants", {}).setdefault(str(msg.sender_id), {
                        "uid": msg.sender_id, "who": who, "username": uname, "firstName": fname})
                added += 1
        sess["_name_cache"] = names
        if fetched >= G3_SWEEP_LIMIT and not hit_window_end:
            # Loop habis karena kena G3_SWEEP_LIMIT, bukan karena sudah sampai
            # awal sesi. Ada pesan lama yang belum diperiksa - jangan diam.
            log.error("sweep link g3 KENA BATAS: %d pesan terakhir masih di dalam "
                      "sesi, pesan yang lebih lama belum diperiksa "
                      "(naikkan G3_SWEEP_LIMIT)", G3_SWEEP_LIMIT)
        if added:
            _save_g3_session(sess)
            log.warning("RECONCILE LINK: %d link dipulihkan dari Telegram untuk sesi g3 "
                        "(ditinjau %d pesan)", added, scanned)
    except Exception as e:
        log.warning("reconcile link g3 gagal: %s", e)
    return added


async def reconcile_g3_links():
    """Self-healing berkala: link yang somehow terlewat dari getUpdates ditarik
    kembali dari Telegram sebelum sesi ditutup."""
    sess = ACTIVE.get((GROUPS["g3"]["cid"], GROUPS["g3"]["tid"]))
    if not sess or sess.get("closed"):
        return
    await _sweep_g3_links(sess)


def _links_from_text(text):
    if not text:
        return []
    return [m.group(0) for m in X_RE.finditer(str(text))]


async def _g3_links_from_telegram(opened_ms, limit=3000):
    """Tarik link grup 3 dari Telegram pakai userbot (oxyas string).

    Dipakai kalau bot somehow tidak punya link sesi - misalnya bot mati di
    tengah sesi sehingga file link tidak pernah terkirim. Satu baris per link
    unik per pesan, urutan waktu.
    """
    if WATCHDOG is None or not opened_ms:
        return []
    try:
        g3 = GROUPS["g3"]
        ent = await WATCHDOG.get_input_entity(g3["cid"])
        skip = set()
        for who in (WATCHDOG.get_me(),):
            if who and getattr(who, "id", None) is not None:
                skip.add(who.id)
        try:
            me_bot = await api("getMe")
            bid = (me_bot.get("result") or {}).get("id")
            if bid is not None:
                skip.add(int(bid))
        except Exception:
            pass
        rows = []
        async for msg in WATCHDOG.iter_messages(ent, reply_to=g3["tid"], limit=limit):
            stamp = int(msg.date.timestamp() * 1000) if msg.date else 0
            if stamp and stamp < int(opened_ms) - 2000:
                break                      # sudah melewati awal sesi -> selesai
            links = _links_from_text(getattr(msg, "text", None)) or \
                _links_from_text(getattr(msg, "caption", None))
            if not links:
                continue
            if msg.sender_id is not None and int(msg.sender_id) in skip:
                continue                  # pesan bot sendiri
            rows.append((stamp, msg.id, list(dict.fromkeys(norm_x(l) for l in links))))
        rows.sort(key=lambda r: (r[0], r[1]))
        return [l for _, _, ls in rows for l in ls]
    except Exception as e:
        log.warning("tarik link g3 dari telegram gagal: %s", e)
        return []


def _mark_link_file_sent(sent, label):
    """Tandai record pending sesi ini sebagai "file link sudah terkirim" supaya
    job deliver_pending_link_files tidak mengirimnya lagi."""
    if not sent:
        return
    for rec in _read_pending_records():
        if isinstance(rec, dict) and (rec.get("sessionLabel") == label
                                     or rec.get("sessionName") == label):
            rec["linksFileSent"] = True
            rec["linksFileSentAt"] = int(datetime.now(timezone.utc).timestamp() * 1000)
            try:
                _save_pending_check(rec)
            except (OSError, ValueError) as e:
                log.warning("tandai file link terkirim gagal: %s", e)


async def deliver_pending_link_files():
    """Kirim file link untuk sesi g3 yang tercatat tapi file-nya belum pernah
    terkirim - mis. bot mati pas sesi tutup, sehingga do_close tidak jalan.

    Kalau record tidak punya `links`, link ditarik dari Telegram pakai userbot.
    Dijalankan tiap menit sampai semua file tertinggal terkirim.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for rec in _read_pending_records():
        if not isinstance(rec, dict) or rec.get("linksFileSent"):
            continue
        cid, tid = rec.get("chatId"), rec.get("topicId")
        label = rec.get("sessionLabel") or rec.get("sessionName") or "Sesi"
        links = list(rec.get("links") or [])
        if not links:
            links = await _g3_links_from_telegram(rec.get("openedAt") or rec.get("closedAt"))
            if links:
                rec["links"] = links
        if not links:
            continue
        # WAJIB: pesan close dulu, baru file link. Kalau pesan close GAGAL,
        # file TIDAK boleh dikirim - dicoba lagi menit berikutnya. Member tidak
        # boleh pernah dapat file tanpa pesan close.
        try:
            g3 = GROUPS["g3"]
            msg_ok = await send(cid, g3["cm"].replace("{total}", str(len(links))), tid)
        except Exception as e:
            log.warning("pesan close tertunda gagal: %s", e)
            continue
        if not (isinstance(msg_ok, dict) and msg_ok.get("ok")):
            log.warning("pesan close tertunda tidak terkirim (%s), file ditunda",
                        (msg_ok or {}).get("description", "?") if isinstance(msg_ok, dict) else "?")
            continue
        try:
            ok = await send_link_file(cid, tid, label, links)
        except Exception as e:
            log.warning("kirim file link tertunda gagal: %s", e)
            continue
        if ok:
            rec["linksFileSent"] = True
            rec["linksFileSentAt"] = now_ms
            log.warning("LINK FILE TERLAMBAT: %d link %s dikirim ke %s/%s",
                        len(links), label, cid, tid)
            try:
                _save_pending_check(rec)
            except (OSError, ValueError) as e:
                log.warning("tandai file link terkirim gagal: %s", e)


# --- /lb: leaderboard g2 (aktif + tidak pernah kena /warn) -------------------

def _lb_stamp(moment):
    return datetime.fromtimestamp(moment.timestamp(), WIB).strftime("%d/%m %H:%M")


def _g2_session_windows_wib():
    """Window sesi g2 dalam menit WIB, diturunkan dari jadwal g2 (UTC)."""
    return [((((oh + 7) % 24) * 60 + om), (((ch + 7) % 24) * 60 + cm))
            for oh, om, ch, cm in GROUPS["g2"]["sch"]]


def _g2_session_index(dt_wib, windows):
    """Index sesi (0..3) dari waktu WIB, None kalau di luar window sesi."""
    minute = dt_wib.hour * 60 + dt_wib.minute
    for i, (start, end) in enumerate(windows):
        inside = (start <= minute < end) if start < end else (minute >= start or minute < end)
        if inside:
            return i
    return None


def _lb_msg_text(msg):
    return (getattr(msg, "text", None) or "") or ""


def _lb_msg_has_link(msg):
    """Link post X, dicek di teks, caption, dan URL entity supaya tidak ada yang terlewat."""
    for text in ((getattr(msg, "text", None) or ""), (getattr(msg, "caption", None) or "")):
        if text and X_RE.search(text):
            return True
    for group in (getattr(msg, "entities", None) or [], getattr(msg, "caption_entities", None) or []):
        for ent in group:
            url = getattr(ent, "url", None)
            if url and X_RE.search(url):
                return True
    return False


def _lb_data_age_hours():
    """Umur data leaderboard dalam jam, None kalau file belum ada / rusak."""
    try:
        with open(LB_PATH, encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not value.get("generatedAt"):
        return None
    try:
        return (datetime.now(timezone.utc).timestamp() * 1000 - int(value["generatedAt"])) / 3600000.0
    except (TypeError, ValueError):
        return None


def _lb_render(data):
    """Teks /lb. None kalau file belum ada / kosong - supaya tidak pernah print 0."""
    if not isinstance(data, dict):
        return None
    top = data.get("top")
    if not isinstance(top, list) or not top:
        return None
    lines = [f"/lb \u2014 ENGAGE ORBIT \u2014 {data.get('windowFrom') or '?'} "
             f"to {data.get('windowTo') or '?'} WIB",
             "TOP 10 ACTIVE, NEVER WARNED"]
    for i, row in enumerate(top[:10], 1):
        if not isinstance(row, dict):
            return None
        lines.append(f"{i:>2}. {str(row.get('who') or '?'):<15} {row.get('links', 0)} links, "
                     f"{row.get('sessions', 0)} sessions")
    return "\n".join(lines)


async def _refresh_lb_g2():
    g2 = GROUPS["g2"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LB_WINDOW_DAYS)
    windows = _g2_session_windows_wib()
    ent = await WATCHDOG.get_input_entity(g2["cid"])

    # Admin tidak boleh masuk leaderboard.
    admin_uids, admin_names = set(), set()
    async for participant in WATCHDOG.iter_participants(ent, filter=ChannelParticipantsAdmins):
        admin_uids.add(participant.id)
        uname = getattr(participant, "username", None)
        if uname:
            admin_names.add(uname.lower())

    # Topic warn: satu-satunya sumber "pernah kena warn". Hanya /warn yang
    # dihitung; /unmute dan /mute tidak.
    warned, warn_scanned = set(), 0
    async for msg in WATCHDOG.iter_messages(ent, reply_to=LB_WARN_TOPIC, limit=LB_SCAN_LIMIT):
        stamp = msg.date.astimezone(WIB)
        if stamp < cutoff:
            break
        warn_scanned += 1
        found = LB_WARN_RE.match(_lb_msg_text(msg).strip())
        if found:
            warned.add(found.group(1).lower())

    # Topic sesi: link post di dalam window sesi = aktivitas.
    names, sessions, links, scanned = {}, defaultdict(set), defaultdict(int), 0
    async for msg in WATCHDOG.iter_messages(ent, reply_to=g2["tid"], limit=LB_SCAN_LIMIT):
        stamp = msg.date.astimezone(WIB)
        if stamp < cutoff:
            break
        scanned += 1
        uid = msg.sender_id
        if uid is None or uid in admin_uids or not _lb_msg_has_link(msg):
            continue
        slot = _g2_session_index(stamp, windows)
        if slot is None:
            continue
        links[uid] += 1
        sessions[uid].add((stamp.date(), slot))
        if uid not in names:
            try:
                names[uid] = getattr(await WATCHDOG.get_entity(uid), "username", None)
            except Exception:
                names[uid] = None

    rows = []
    for uid, total in links.items():
        uname = names.get(uid)
        # tanpa username (tidak bisa ditampilkan) dan yang kena warn: keluar.
        if not uname or uname.lower() in admin_names or uname.lower() in warned:
            continue
        rows.append({"who": f"@{uname}", "links": total, "sessions": len(sessions.get(uid, ()))})
    rows.sort(key=lambda r: (-r["links"], -r["sessions"], r["who"].lower()))

    _atomic_write(LB_PATH, json.dumps({
        "generatedAt": int(now.timestamp() * 1000),
        "windowFrom": _lb_stamp(cutoff),
        "windowTo": _lb_stamp(now),
        "top": rows[:10],
    }, ensure_ascii=False, indent=2))
    log.info("lb g2: %d pesan sesi + %d pesan warn dibaca | %d aktif, %d kena warn, %d bersih"
             " | top1=%s %s link", scanned, warn_scanned, len(links), len(warned), len(rows),
             rows[0]["who"] if rows else "-", rows[0]["links"] if rows else 0)


async def refresh_lb_g2():
    """Job latar 24 jam. /lb sendiri tidak pernah menarik data."""
    if WATCHDOG is None or LB_LOCK.locked():
        return
    async with LB_LOCK:
        try:
            await _refresh_lb_g2()
        except Exception as e:
            log.warning("lb g2 refresh gagal: %s", e)


async def _handle_lb_command(cid, tid, msg):
    """/lb -> TOP 10 member g2 yang aktif dan tidak pernah kena /warn.

    Hanya g2, seperti /vip. Panjang < 4096 karakter jadi tidak perlu dipecah.
    """
    if cid != GROUPS["g2"]["cid"]:
        return False
    if not LB_CMD_RE.match(str(msg.get("text") or msg.get("caption") or "").strip()):
        return False
    data = None
    try:
        with open(LB_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("/lb: data leaderboard tidak terbaca (%s), tidak ada yang ditampilkan", e)
    body = _lb_render(data)
    if not body:
        await send(cid, LB_NOT_READY, tid)
        return True
    age_h = _lb_data_age_hours()
    if age_h is not None and age_h > 26:
        log.warning("/lb: data leaderboard sudah %.1f jam, belum disegarkan", age_h)
    await send(cid, body, tid)
    return True


async def vip_refresh_loop():
    # Refresh PERTAMA langsung jalan: sejak bot start sampai tag VIP terbaca,
    # jangan ada celah di mana VIP masih bisa dilaporkan.
    while True:
        try:
            await refresh_vips()
        except Exception as e:
            log.warning("refresh VIP gagal: %s", e)
        await asyncio.sleep(VIP_SCAN_MINUTES * 60)


def build():
    utc = ZoneInfo("UTC")
    # misfire_grace_time=300: job open/close TIDAK boleh dilewat hanya karena
    # event loop sedang sibuk (default 1 detik = sesi bisa gagal buka/tutup).
    s = AsyncIOScheduler(timezone=utc, job_defaults={"misfire_grace_time": 300,
                                                      "coalesce": True, "max_instances": 1})
    for gn, g in GROUPS.items():
        paused = gn in PAUSED_GROUPS
        if paused:
            log.info("grup %s di-PAUSE: job buka/tutup sesi tidak dijadwalkan", gn)
        for i, (oh, om, ch, cm) in enumerate(g["sch"]):
            n = i + 1
            if paused:
                continue
            s.add_job(do_open, CronTrigger(hour=oh, minute=om, timezone=utc), args=[g, n], id=f"{gn}_s{n}_o")
            s.add_job(do_close, CronTrigger(hour=ch, minute=cm, timezone=utc), args=[g], id=f"{gn}_s{n}_c")
        if gn == "g3" and MANUAL_LIST_ENABLED:
            # 40 menit sebelum tiap sesi g3 dibuka: kirim file cek manual
            # berisi sesi yang barusan tutup.
            for i, (oh, om, _, _) in enumerate(g["sch"]):
                n = i + 1
                lead = (oh * 60 + om - MANUAL_LIST_LEAD_MINUTES) % (24 * 60)
                s.add_job(send_manual_list, CronTrigger(hour=lead // 60, minute=lead % 60, timezone=utc),
                          id=f"g3_list{n}")
        if gn == "g3" and CHECKER_ENABLED:
            for i, (oh, om, _, _) in enumerate(g["sch"]):
                n = i + 1
                check_minute = (oh * 60 + om - CHECKER_LEAD_MINUTES) % (24 * 60)
                s.add_job(do_check_g3, CronTrigger(hour=check_minute // 60, minute=check_minute % 60, timezone=utc), id=f"g3_c{n}")
            s.add_job(do_check_g3, IntervalTrigger(seconds=20), id="g3_check_retry")
    s.add_job(reconcile_sessions, IntervalTrigger(seconds=60), id="reconcile_sessions")
    s.add_job(reconcile_g3_links, IntervalTrigger(minutes=2), id="reconcile_links")
    # Jaring pengaman file cek manual g3: kirim ulang kalau terlewat.
    if MANUAL_LIST_ENABLED:
        s.add_job(_guard_manual_list, IntervalTrigger(seconds=60), id="guard_manual_list")
    # NOTE: job deliver_pending_link_files DIMATIKAN. Ia mengirim file link dari
    # record pending lama ke topic dan menghasilkan file yang salah. Jangan
    # diaktifkan lagi tanpa batas usia record + verifikasi jumlah link.
    # /lb: tarikan 24 jam sekali (bukan per menit) supaya tidak membanjiri
    # Telegram. 03:07 UTC = 10:07 WIB, di luar jam buka/tutup semua sesi.
    s.add_job(refresh_lb_g2, CronTrigger(hour=3, minute=7, timezone=utc), id="lb_g2_refresh")
    return s

async def main():
    global WATCHDOG
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi")
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    me = await api("getMe")
    if not me.get("ok") or not (me.get("result") or {}).get("username"):
        raise RuntimeError(f"getMe failed: {me.get('description', 'unknown')}")
    _load_vip_cache()
    _load_x_owners()
    _prune_pending_file()
    _arm_recovered_s4()
    _resume_other_sessions()
    _resume_g3_session()
    _ensure_active_sessions()
    log.info("Bot @%s started", me["result"]["username"])
    log.info("kebalisan: protected=%s vip_daftar=%d vip_reader=%s vip_tag=%s",
             sorted(PROTECTED_IDS), len(VIP_UIDS),
             "AKTIF" if VIP_READER_OK else "MATI (pakai /vip di grup)", ",".join(VIP_RANK_TAGS) or "-")
    if not VIP_UIDS and not VIP_READER_OK:
        log.error("PERINGATAN: belum ada satu pun VIP terdaftar DAN tag VIP tidak bisa dibaca. "
                  "Sesi ini masih jalan, tapi belum ada orang yang dilindungi sebagai VIP. "
                  "Daftarkan dengan: /vip @username (dari admin/VIP) di dalam grup.")
    sc = build(); sc.start()
    if CHECKER_ENABLED:
        log.info("checker g3 aktif lead=%s report=%s cookie=%s slice=%ss deadline_margin=%sm",
                 CHECKER_LEAD_MINUTES, CHECKER_REPORT_TARGET,
                 _has_x_cookie(), CHECKER_SLICE_SECONDS, CHECKER_DEADLINE_MARGIN // 60000)
    asyncio.create_task(do_check_g3())
    for j in sc.get_jobs():
        log.info("  %-24s %s", j.id, j.next_run_time)
    try:
        WATCHDOG = await _setup_watchdog()
        asyncio.create_task(WATCHDOG.run_until_disconnected())
        asyncio.create_task(vip_refresh_loop())
        # Tarikan 24 jam sekali = baca thousands pesan, jadi hanya saat tidak ada
        # sesi g2 yang sedang jalan dan data lama/tidak ada, supaya tidak
        # mengganggu sesi mana pun dan tidak narik data berulang.
        _lb_age = _lb_data_age_hours()
        if _session_at_for_group(GROUPS["g2"]) is None and (_lb_age is None or _lb_age > 20):
            asyncio.create_task(refresh_lb_g2())
    except Exception as e:
        log.error("Watchdog failed to start: %s", e)
    asyncio.create_task(poll_updates())
    _atomic_write(READY_PATH, str(os.getpid()))
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
