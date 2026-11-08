from flask import Flask, render_template, jsonify, request
import os
import json
import time
import hmac
import hashlib
from urllib.parse import parse_qsl
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Lock

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = os.path.expanduser("~/users.json")

MINING_PER_DAY = 1440
DAILY_BONUS = 1
STREAK_BONUS = 5

lock = Lock()


def verify_telegram(init_data):
    if not TOKEN or not init_data:
        return None

    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)

        if not received_hash:
            return None

        check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items())
        )

        secret_key = hmac.new(
            b"WebAppData", TOKEN.encode(), hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key, check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(data.get("auth_date", 0))
        now = int(time.time())

        if auth_date > now + 30 or now - auth_date > 3600:
            return None

        user = json.loads(data.get("user", "{}"))
        return user if user.get("id") else None

    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def get_verified_user():
    return verify_telegram(
        request.headers.get("X-Telegram-Init-Data", "")
    )


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_data(data):
    temp_file = DATA_FILE + ".tmp"

    with open(temp_file, "w") as f:
        json.dump(data, f, indent=4)

    os.replace(temp_file, DATA_FILE)


def get_user(data, user_id):
    uid = str(user_id)
    now = time.time()

    if uid not in data:
        data[uid] = {
            "balance": 0,
            "last_daily": "",
            "daily_streak": 0,
            "mining_last_update": now,
            "mining_rate_version": 2
        }

    user = data[uid]

    user.setdefault("balance", 0)
    user.setdefault("last_daily", "")
    user.setdefault("daily_streak", 0)
    user.setdefault("mining_active", False)

    if user.get("mining_rate_version", 0) < 2:
        last = float(user.get("mining_last_update", now))
        elapsed = max(0, now - last)
        old_earned = elapsed * 9 / 86400

        user["balance"] = float(user.get("balance", 0)) + old_earned
        user["mining_last_update"] = now
        user["mining_rate_version"] = 2

    return user

def process_referral(data, new_user_id, referrer_id):
    new_uid = str(new_user_id)
    ref_uid = str(referrer_id)

    if new_uid == ref_uid:
        return False

    if ref_uid not in data:
        return False

    new_user = data[new_uid]
    referrer = data[ref_uid]

    if new_user.get("referred_by"):
        return False

    new_user["referred_by"] = ref_uid
    referrer["balance"] = float(referrer.get("balance", 0)) + 25
    referrer["referral_count"] = int(
        referrer.get("referral_count", 0)
    ) + 1

    return True
def accrue_mining(user):
    now = time.time()
    last = float(user.get("mining_last_update", now))
    elapsed = max(0, now - last)

    earned = 0
    if user.get("mining_active", False):
        earned = elapsed * MINING_PER_DAY / 86400
        user["balance"] = float(user.get("balance", 0)) + earned

    user["mining_last_update"] = now
    return earned


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "XRT Vault Online"})


@app.route("/api/me")
def me():
    telegram_user = get_verified_user()

    if not telegram_user:
        return jsonify({"error": "Unauthorized"}), 401

    with lock:
        data = load_data()
        user = get_user(data, telegram_user["id"])

        pending_referrer = user.pop("pending_referrer", None)
        if pending_referrer:
            process_referral(
                data,
                telegram_user["id"],
                pending_referrer
            )

        accrue_mining(user)
        save_data(data)

        balance = user["balance"]
        streak = user["daily_streak"]

    return jsonify({
        "id": telegram_user["id"],
        "first_name": telegram_user.get("first_name", ""),
        "balance": round(balance, 6),
        "mining_per_day": MINING_PER_DAY,
        "mining_active": bool(user.get("mining_active", False)),
        "daily_bonus": DAILY_BONUS,
        "daily_streak": streak,
        "referral_link": f"https://t.me/xrtvaultbot?start=ref_{telegram_user['id']}",
        "referral_count": int(user.get("referral_count", 0)),
        "referral_earned": int(user.get("referral_count", 0)) * 25
    })


@app.route("/api/mining/start", methods=["POST"])
def mining_start():
    telegram_user = get_verified_user()
    if not telegram_user:
        return jsonify({"error": "Unauthorized"}), 401

    with lock:
        data = load_data()
        user = get_user(data, telegram_user["id"])

        if not user.get("mining_active", False):
            user["mining_last_update"] = time.time()
            user["mining_active"] = True

        save_data(data)
        balance = float(user.get("balance", 0))

    return jsonify({"success": True, "mining_active": True,
                    "balance": round(balance, 6)})


@app.route("/api/mining/stop", methods=["POST"])
def mining_stop():
    telegram_user = get_verified_user()
    if not telegram_user:
        return jsonify({"error": "Unauthorized"}), 401

    with lock:
        data = load_data()
        user = get_user(data, telegram_user["id"])

        accrue_mining(user)
        user["mining_active"] = False
        save_data(data)
        balance = float(user.get("balance", 0))

    return jsonify({"success": True, "mining_active": False,
                    "balance": round(balance, 6)})


@app.route("/api/daily", methods=["POST"])
def daily():
    telegram_user = get_verified_user()

    if not telegram_user:
        return jsonify({"error": "Unauthorized"}), 401

    today = datetime.now(
        ZoneInfo("Asia/Dhaka")
    ).date()

    today_string = today.isoformat()

    with lock:
        data = load_data()
        user = get_user(data, telegram_user["id"])

        accrue_mining(user)

        if user["last_daily"] == today_string:
            return jsonify({
                "error": "Daily bonus already claimed"
            }), 400

        last_daily = user["last_daily"]

        if last_daily:
            previous_date = datetime.fromisoformat(last_daily).date()

            if today - previous_date == timedelta(days=1):
                user["daily_streak"] += 1
            else:
                user["daily_streak"] = 1
        else:
            user["daily_streak"] = 1

        reward = DAILY_BONUS
        streak_reward = 0

        if user["daily_streak"] % 7 == 0:
            streak_reward = STREAK_BONUS

        total_reward = reward + streak_reward

        user["balance"] += total_reward
        user["last_daily"] = today_string

        save_data(data)

        balance = user["balance"]
        streak = user["daily_streak"]

    return jsonify({
        "success": True,
        "reward": reward,
        "streak_bonus": streak_reward,
        "daily_streak": streak,
        "balance": round(balance, 6)
    })


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    app.run(host="0.0.0.0", port=5000)

# XRT Vault Telegram Webhook
import urllib.request

WEBHOOK_URL = "https://xrt-vault.onrender.com/telegram-webhook"
WEBHOOK_SECRET = hashlib.sha256(
    (TOKEN + ":xrt-vault-webhook").encode()
).hexdigest() if TOKEN else ""


def telegram_api(method, payload):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if not TOKEN or not hmac.compare_digest(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
        WEBHOOK_SECRET
    ):
        return jsonify({"error": "Unauthorized"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message", {})
    chat = message.get("chat", {})
    text = message.get("text", "")

    if chat.get("type") == "private" and text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""

        if payload.startswith("ref_"):
            ref_uid = payload[4:]
            uid = str(chat["id"])

            with lock:
                data = load_data()

                if (ref_uid.isdigit() and ref_uid != uid
                        and ref_uid in data):
                    if uid not in data:
                        data[uid] = {"pending_referrer": ref_uid}
                    elif (not data[uid].get("referred_by")
                          and not data[uid].get("pending_referrer")):
                        data[uid]["pending_referrer"] = ref_uid

                    save_data(data)

        telegram_api("sendMessage", {
            "chat_id": chat["id"],
            "text": (
                "💙 Welcome to XRT Vault!\n\n"
                "Something Big Is Coming.\n"
                "Explore the Unknown. Unlock the Future.\n\n"
                "⚡ Be Early. Stay Ahead."
            ),
            "reply_markup": {
                "inline_keyboard": [[{
                    "text": "🚀 Open XRT Vault",
                    "web_app": {"url": "https://xrt-vault.onrender.com"}
                }]]
            }
        })

    elif chat.get("type") == "private" and text.startswith("/help"):
        telegram_api("sendMessage", {
            "chat_id": chat["id"],
            "text": "💎 XRT VAULT\n\nUse /start to open XRT Vault."
        })

    return jsonify({"ok": True})


# Register webhook when the Render app starts
if TOKEN:
    try:
        telegram_api("setWebhook", {
            "url": WEBHOOK_URL,
            "secret_token": WEBHOOK_SECRET
        })
        print("XRT Vault Telegram webhook registered.")
    except Exception as e:
        print("Telegram webhook registration failed:", str(e))
