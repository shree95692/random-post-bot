from pyrogram import Client, filters
import asyncio
import random
import json
import os
import base64
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
import requests
from keep_alive import keep_alive  # For Render/Replit keep alive

# === CONFIG ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Direct IDs
PRIVATE_CHANNEL_ID = -1002458215030   # Private channel ID
PUBLIC_CHANNEL_ID = -1002469220850    # Public channel ID

# GitHub config
GITHUB_REPO = "shree95692/random-forward-db"
GITHUB_FILE = "posted.json"
GITHUB_PAT = os.getenv("GITHUB_PAT")  # PAT env me rakho

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))
TIMEZONE = pytz.timezone("Asia/Kolkata")

# Admin alerts
ADMIN_ID = 5163916480  # tumhara Telegram ID

client = Client("scheduled_forward_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
POSTED_FILE = "posted.json"


# ===================== Alert Helper =====================
async def send_alert(text):
    """Send alert to admin (async)."""
    try:
        await client.send_message(ADMIN_ID, f"⚠️ ALERT:\n{text}")
    except Exception as e:
        print("❌ Failed to send alert to admin:", e)


def _schedule_alert(text):
    """
    Schedule an async alert from sync context safely.
    If event loop not running, just print.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop and loop.is_running():
            loop.create_task(send_alert(text))
        else:
            print("ALERT (no running loop):", text)
    except Exception as e:
        print("ALERT scheduling failed:", e)


# ===================== GitHub Backup Helpers =====================
def download_from_github():
    """
    Restore posted.json from GitHub and merge with local file.
    Keeps format: {"all_posts":[[chat,msg],...],"forwarded":[[chat,msg],...]}
    """
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200 or not r.text.strip():
            print(f"⚠️ GitHub restore failed or empty content | Status: {r.status_code}")
            return 0

        try:
            remote_data = json.loads(r.text)
        except Exception as e:
            print("⚠️ Remote JSON invalid, skipping restore:", e)
            return 0

        # Ensure structure
        remote_all = remote_data.get("all_posts", []) or []
        remote_forwarded = remote_data.get("forwarded", []) or []

        # Load local data if present
        local_data = {"all_posts": [], "forwarded": []}
        if os.path.exists(POSTED_FILE):
            try:
                with open(POSTED_FILE, "r") as f:
                    local_data = json.load(f)
            except Exception as e:
                print("⚠️ Local JSON invalid, using empty base:", e)

        local_all = local_data.get("all_posts", []) or []
        local_forwarded = local_data.get("forwarded", []) or []

        # Merge using set of tuples to avoid duplicates and ensure lists of lists in final JSON
        merged_all_set = {tuple(x) for x in local_all + remote_all}
        merged_forwarded_set = {tuple(x) for x in local_forwarded + remote_forwarded}

        merged = {
            "all_posts": [list(x) for x in merged_all_set],
            "forwarded": [list(x) for x in merged_forwarded_set]
        }

        # If merged ends up empty but local had data, preserve local
        if not merged["all_posts"] and local_all:
            merged["all_posts"] = local_all
        if not merged["forwarded"] and local_forwarded:
            merged["forwarded"] = local_forwarded

        # Save final merged DB (pretty for humans)
        with open(POSTED_FILE, "w") as f:
            json.dump(merged, f, indent=4)

        print(f"✅ Database restored & merged: {len(merged['all_posts'])} posts, {len(merged['forwarded'])} forwarded")
        return len(merged["all_posts"])
    except Exception as e:
        print(f"⚠️ Could not restore DB: {e}")
        return 0


def upload_to_github():
    """
    Upload local POSTED_FILE to GitHub repo (base64 content). Non-blocking alert on failure.
    """
    if not os.path.exists(POSTED_FILE):
        print("⚠️ No local DB to upload.")
        return

    try:
        with open(POSTED_FILE, "r") as f:
            content = f.read()
    except Exception as e:
        print("❌ Failed to read POSTED_FILE for upload:", e)
        return

    try:
        b64_content = base64.b64encode(content.encode()).decode()
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
        headers = {"Authorization": f"token {GITHUB_PAT}"} if GITHUB_PAT else {}
        sha = None
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            try:
                sha = r.json().get("sha")
            except:
                sha = None

        data = {
            "message": "Auto-backup posted.json",
            "content": b64_content,
            "branch": "main"
        }
        if sha:
            data["sha"] = sha

        r = requests.put(url, headers=headers, json=data, timeout=15)
        if r.status_code in [200, 201]:
            print("✅ Database backed up to GitHub")
        else:
            error_msg = f"❌ GitHub backup failed (status {r.status_code}): {r.text}"
            print(error_msg)
            _schedule_alert(error_msg)
    except Exception as e:
        error_msg = f"❌ GitHub backup exception: {e}"
        print(error_msg)
        _schedule_alert(error_msg)


# ===================== Local DB Helpers =====================
def load_posted():
    """Load local posted.json safely, return canonical structure."""
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                data = json.load(f)
            # Normalize keys
            all_posts = data.get("all_posts", []) or []
            forwarded = data.get("forwarded", []) or []
            # Ensure inner items are lists of two values (chat_id, msg_id)
            normalized_all = []
            for item in all_posts:
                try:
                    normalized_all.append([int(item[0]), int(item[1])])
                except:
                    continue
            normalized_forwarded = []
            for item in forwarded:
                try:
                    normalized_forwarded.append([int(item[0]), int(item[1])])
                except:
                    continue
            return {"all_posts": normalized_all, "forwarded": normalized_forwarded}
        except Exception as e:
            print("⚠️ Failed to parse POSTED_FILE, returning empty DB:", e)
            return {"all_posts": [], "forwarded": []}
    return {"all_posts": [], "forwarded": []}


def save_posted(data):
    """
    Merge with existing local DB (to avoid accidental overwrite) and save in canonical format.
    Then upload to GitHub.
    """
    if not isinstance(data, dict):
        print("⚠️ save_posted expects dict, got:", type(data))
        return

    old = load_posted()
    # merge sets
    merged_all = {tuple(x) for x in old.get("all_posts", []) + data.get("all_posts", [])}
    merged_forwarded = {tuple(x) for x in old.get("forwarded", []) + data.get("forwarded", [])}

    final = {
        "all_posts": [list(x) for x in merged_all],
        "forwarded": [list(x) for x in merged_forwarded]
    }

    # Save locally
    try:
        with open(POSTED_FILE, "w") as f:
            json.dump(final, f, indent=4)
        print(f"💾 DB saved locally. Total posts: {len(final['all_posts'])}")
    except Exception as e:
        print("❌ Failed to save POSTED_FILE:", e)
        return

    # Upload to GitHub (best-effort)
    try:
        upload_to_github()
    except Exception as e:
        print("❌ upload_to_github failed:", e)


# ===================== Event: Save new posts =====================
@client.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post_handler(c, message):
    """
    Save every new message from private channel into local DB (format preserved).
    """
    data = load_posted()
    post_key = [message.chat.id, message.id]

    if post_key not in data.get("all_posts", []):
        data["all_posts"].append(post_key)

        # Remove duplicates and normalize
        data["all_posts"] = [list(x) for x in {tuple(p) for p in data.get("all_posts", [])}]
        data["forwarded"] = [list(x) for x in {tuple(p) for p in data.get("forwarded", [])}]

        save_posted(data)
        print(f"💾 Saved new post {message.id} for scheduling")
    else:
        print(f"ℹ️ Post {message.id} already saved, skipping.")


# ===================== Event: Deleted Post Handler =====================
@client.on_deleted_messages()
async def handle_deleted_messages(c, messages):
    """
    When messages are deleted from the source channel, remove only those entries
    from DB (keep other duplicates intact).
    """
    if not messages:
        return
    data = load_posted()
    changed = False
    for msg in messages:
        try:
            key = [msg.chat.id, msg.id]
            if key in data.get("all_posts", []):
                data["all_posts"].remove(key)
                changed = True
                print(f"❌ Removed deleted post {msg.id} from DB")
            if key in data.get("forwarded", []):
                data["forwarded"].remove(key)
        except Exception as e:
            print("⚠️ Error processing deleted message:", e)
    if changed:
        save_posted(data)


# ===================== Scheduled Forward =====================
async def forward_scheduled_posts(user_id=None):
    now = datetime.now(TIMEZONE)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] ⏳ Running scheduled forward job...")
    data = load_posted()
    all_posts = data.get("all_posts", []) or []
    already_forwarded = data.get("forwarded", []) or []

    # If no posts at all, nothing to do
    if not all_posts:
        print("⚠️ No posts to forward.")
        return

    remaining = [post for post in all_posts if post not in already_forwarded]

    if not remaining:
        print("✅ All posts forwarded once. Resetting cycle.")
        data["forwarded"] = []
        save_posted(data)
        remaining = all_posts

    if not remaining:
        print("⚠️ No posts available to forward after reset.")
        return

    count = min(POSTS_PER_BATCH, len(remaining))
    try:
        selected = random.sample(remaining, count)
    except Exception as e:
        print("❌ random.sample failed:", e)
        selected = remaining[:count]

    for item in selected:
        try:
            chat_id, msg_id = int(item[0]), int(item[1])
            # use copy_message (recommended) to preserve original
            await client.copy_message(
                chat_id=PUBLIC_CHANNEL_ID,
                from_chat_id=chat_id,
                message_id=msg_id
            )
            # append and dedupe forwarded list
            data["forwarded"].append([chat_id, msg_id])
            data["forwarded"] = [list(x) for x in {tuple(p) for p in data.get("forwarded", [])}]
            print(f"✅ Forwarded message {msg_id}")
        except Exception as e:
            error_text = f"❌ Failed to forward message {item}: {e}"
            print(error_text)
            try:
                _schedule_alert(error_text)
                if user_id:
                    await client.send_message(user_id, error_text)
            except:
                pass

    save_posted(data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(c, message):
    await message.reply_text(
        "✅ Bot chal raha hai!\n"
        f"⏰ Scheduled: {POSTS_PER_BATCH} posts at 10:00 AM & 11:00 PM IST\n"
        "📡 Source: Private channel me jo naye posts aaye, unko save karke schedule pe forward karega."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(c, message):
    await message.reply_text("⏳ Abhi random posts forward ho rahe hain...")
    await forward_scheduled_posts(user_id=message.from_user.id)
    await message.reply_text("✅ Posts forward ho gaye!")


@client.on_message(filters.command("test") & filters.private)
async def test_command(c, message):
    data = load_posted()
    await message.reply_text(
        f"📊 Database Status:\n"
        f"Total saved posts: {len(data['all_posts'])}\n"
        f"Already forwarded: {len(data['forwarded'])}\n"
        f"Remaining: {len([p for p in data['all_posts'] if p not in data['forwarded']])}"
    )


@client.on_message(filters.command("update_from_github") & filters.private)
async def update_from_github_command(c, message):
    await message.reply_text("🔄 GitHub se database restore ho raha hai...")
    try:
        restored = download_from_github()
        await message.reply_text(f"✅ Database restored from GitHub! Total posts: {restored}")
    except Exception as e:
        await message.reply_text(f"❌ Restore failed: {e}")


# ===================== Main =====================
from pyrogram import idle
import logging

logging.basicConfig(level=logging.INFO)  # optional, debug logs console me

# ===================== Main =====================
async def main():
    # start keep-alive
    keep_alive()

    # Try restore first (merge remote + local)
    download_from_github()

    # Start client
    await client.start()
    print("✅ Bot started and scheduler loaded!")

    # Scheduler (IST)
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()

    # --- Debug handler: temporary, will log all private messages ---
    @client.on_message(filters.private)
    async def _debug_private_messages(c, m):
        try:
            user = m.from_user.id if m.from_user else "unknown"
            text = m.text or m.caption or "<non-text>"
            print(f"🔍 DEBUG incoming private message from {user}: {text[:200]}")
        except Exception as e:
            print("DEBUG handler error:", e)

    # keep running using pyrogram idle
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
