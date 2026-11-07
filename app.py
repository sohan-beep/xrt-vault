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

MINING_PER_DAY = 9
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
            "mining_last_update": now
        }

    user = data[uid]

    user.setdefault("balance", 0)
    user.setdefault("last_daily", "")
    user.setdefault("daily_streak", 0)

    # Existing accounts start the new mining system from now.
    if "mining_last_update" not in user:
        user["mining_last_update"] = now

    return user


def accrue_mining(user):
    now = time.time()
    last = float(user["mining_last_update"])
    elapsed = max(0, now - last)

    earned = elapsed * MINING_PER_DAY / 86400

    user["balance"] = float(user["balance"]) + earned
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

        accrue_mining(user)
        save_data(data)

        balance = user["balance"]
        streak = user["daily_streak"]

    return jsonify({
        "id": telegram_user["id"],
        "first_name": telegram_user.get("first_name", ""),
        "balance": round(balance, 6),
        "mining_per_day": MINING_PER_DAY,
        "daily_bonus": DAILY_BONUS,
        "daily_streak": streak
    })


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
