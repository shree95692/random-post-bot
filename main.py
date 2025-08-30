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
    try:
        await client.send_message(ADMIN_ID, f"⚠️ ALERT:\n{text}")
    except:
        print("❌ Failed to send alert to admin")


# ===================== GitHub Backup Helpers =====================
def download_from_github():
    """
    Uses GitHub API (with PAT if present) to fetch posted.json (works for private repos).
    Merges remote + local DB and writes posted.json
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}?ref=main"
    headers = {}
    pat = os.getenv("GITHUB_PAT")
    if pat:
        headers["Authorization"] = f"token {pat}"

    try:
        r = requests.get(api_url, headers=headers, timeout=15)
        if r.status_code == 200:
            js = r.json()
            if "content" not in js:
                print("⚠️ GitHub API returned no content field.")
                return
            # content is base64 encoded
            try:
                remote_text = base64.b64decode(js["content"]).decode("utf-8")
                remote_data = json.loads(remote_text)
            except Exception as e:
                print(f"⚠️ Failed to decode remote JSON: {e}")
                return

            # load local if exists
            local_data = {"all_posts": [], "forwarded": []}
            if os.path.exists(POSTED_FILE):
                try:
                    with open(POSTED_FILE, "r") as f:
                        local_data = json.load(f)
                except Exception as e:
                    print(f"⚠️ Local JSON invalid, ignoring local: {e}")

            # merge sets to avoid duplicates
            merged_all = {tuple(x) for x in (local_data.get("all_posts", []) + remote_data.get("all_posts", []))}
            merged_forwarded = {tuple(x) for x in (local_data.get("forwarded", []) + remote_data.get("forwarded", []))}

            merged = {
                "all_posts": [list(x) for x in merged_all],
                "forwarded": [list(x) for x in merged_forwarded]
            }

            # safety: if merge empty but local has data, preserve local
            if not merged["all_posts"] and local_data.get("all_posts"):
                merged["all_posts"] = local_data["all_posts"]
            if not merged["forwarded"] and local_data.get("forwarded"):
                merged["forwarded"] = local_data["forwarded"]

            with open(POSTED_FILE, "w") as f:
                json.dump(merged, f, indent=4)

            print(f"✅ Database restored & merged from GitHub: {len(merged['all_posts'])} posts, {len(merged['forwarded'])} forwarded")
        elif r.status_code == 404:
            print("⚠️ GitHub file not found (404). Repo/file/branch wrong or private without PAT.")
        else:
            print(f"⚠️ GitHub API error: {r.status_code} -> {r.text[:200]}")
    except Exception as e:
        print(f"⚠️ Could not restore DB (request error): {e}")

def upload_to_github():
    if not os.path.exists(POSTED_FILE):
        return
    with open(POSTED_FILE, "r") as f:
        content = f.read()
    b64_content = base64.b64encode(content.encode()).decode()

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {"Authorization": f"token {GITHUB_PAT}"}
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    data = {
        "message": "Auto-backup posted.json",
        "content": b64_content,
        "branch": "main"
    }
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=headers, json=data)
    if r.status_code in [200, 201]:
        print("✅ Database backed up to GitHub")
    else:
        error_msg = f"❌ GitHub backup failed: {r.text}"
        print(error_msg)
        asyncio.create_task(send_alert(error_msg))


# ===================== Local DB Helpers =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"all_posts": [], "forwarded": []}


def save_posted(data):
    # Safety: agar data khali hai to overwrite mat karo
    if not data.get("all_posts") and not data.get("forwarded"):
        print("⚠️ Empty DB, skipping GitHub backup.")
        return

    with open(POSTED_FILE, "w") as f:
        json.dump(data, f, indent=4)   # pretty JSON format

    upload_to_github()


# ===================== Reliable Queue Save + Delete Handler + Cleanup =====================
import asyncio

db_lock = asyncio.Lock()
save_queue = asyncio.Queue()
pending_set = set()   # posts queued but not yet flushed (tuples)
seen_posts = set()    # posts already persisted (tuples)


async def queue_worker():
    """Continuously drain queue and write batches atomically to file (safe + fast)."""
    while True:
        try:
            # wait for at least one item
            item = await save_queue.get()
            batch = [item]

            # collect more quickly (0.5s window) to form a batch
            try:
                while True:
                    more = await asyncio.wait_for(save_queue.get(), timeout=0.5)
                    batch.append(more)
            except asyncio.TimeoutError:
                pass

            # convert to list of tuples (safety)
            batch = [tuple(x) if isinstance(x, list) else x for x in batch]

            # write batch under lock
            async with db_lock:
                data = load_posted()
                changed = False
                for post_key in batch:
                    if post_key not in seen_posts:
                        # append as list for JSON
                        data["all_posts"].append([post_key[0], post_key[1]])
                        seen_posts.add(post_key)
                        changed = True

                if changed:
                    # dedupe (safety)
                    data["all_posts"] = [list(x) for x in {tuple(p) for p in data.get("all_posts", [])}]
                    data["forwarded"] = [list(x) for x in {tuple(p) for p in data.get("forwarded", [])}]
                    save_posted(data)
                    print(f"💾 Saved batch of {len(batch)} posts to DB")
                else:
                    print("ℹ️ Batch processed but no new posts to save")

            # remove items from pending_set after flushing
            for pk in batch:
                pending_set.discard(tuple(pk))

        except Exception as e:
            print(f"❌ queue_worker error: {e}")
            await asyncio.sleep(1)


@client.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post(client, message):
    """Just enqueue incoming posts — worker will persist them."""
    post_key = (message.chat.id, message.id)

    # fast in-memory checks to avoid disk I/O and duplicate enqueue
    if post_key in seen_posts:
        print(f"ℹ️ Post {message.id} already in DB, skipping enqueue.")
        return
    if post_key in pending_set:
        print(f"ℹ️ Post {message.id} already queued, skipping duplicate.")
        return

    # enqueue
    pending_set.add(post_key)
    await save_queue.put(post_key)
    print(f"📥 Enqueued new post {message.id}")


# ===================== Delete Handler =====================
@client.on_deleted_messages(filters.chat(PRIVATE_CHANNEL_ID))
async def delete_post_handler(client, messages):
    """Try to remove deleted messages from DB when Telegram sends delete events."""
    async with db_lock:
        data = load_posted()
        removed = 0
        for msg in messages:
            post_key = [msg.chat.id, msg.id]
            tkey = (msg.chat.id, msg.id)
            if post_key in data.get("all_posts", []):
                data["all_posts"].remove(post_key)
                removed += 1
            if post_key in data.get("forwarded", []):
                data["forwarded"].remove(post_key)
            # also update in-memory sets
            seen_posts.discard(tkey)
            pending_set.discard(tkey)

        if removed > 0:
            save_posted(data)
            print(f"🗑️ Removed {removed} deleted posts from DB")


# ===================== Periodic cleanup (safe mode) =====================
async def cleanup_missing_posts(interval_minutes: int = 10):
    """
    Periodically verify saved posts still exist in source private channel.
    Removes only truly missing ones from DB.
    Skips deletion if access error (Peer id invalid / channel private).
    """
    await asyncio.sleep(5)  # small delay on startup
    while True:
        try:
            async with db_lock:
                data = load_posted()
                all_posts_copy = list(data.get("all_posts", []))
            removed_total = 0

            # iterate and check each message
            for idx, (chat_id, msg_id) in enumerate(all_posts_copy):
                try:
                    # attempt to fetch message; returns Message or None
                    msg = await client.get_messages(chat_id, msg_id)
                    if not msg:
                        raise ValueError("Message not found")
                except Exception as e:
                    err = str(e)
                    if "Peer id invalid" in err or "CHANNEL_PRIVATE" in err:
                        # 🔹 skip deletion, access issue
                        print(f"⚠️ Skip cleanup for {msg_id}: {err}")
                        continue
                    else:
                        # 🔹 truly missing
                        async with db_lock:
                            data = load_posted()
                            key = [chat_id, msg_id]
                            if key in data.get("all_posts", []):
                                data["all_posts"].remove(key)
                                if key in data.get("forwarded", []):
                                    data["forwarded"].remove(key)
                                save_posted(data)
                                removed_total += 1
                                seen_posts.discard((chat_id, msg_id))
                                pending_set.discard((chat_id, msg_id))
                                print(f"🗑️ cleanup: Removed missing post {msg_id} from DB ({err})")

                # throttle to avoid rate-limit bursts
                if (idx + 1) % 50 == 0:
                    await asyncio.sleep(0.5)

            if removed_total:
                print(f"🧹 Cleanup done, removed {removed_total} missing posts.")
            else:
                print("🧹 Cleanup done, no missing posts found.")

        except Exception as e:
            print(f"❌ cleanup_missing_posts error: {e}")

        # sleep until next run
        await asyncio.sleep(interval_minutes * 60)

# ===================== Scheduled Forward =====================
async def forward_scheduled_posts(user_id=None):
    print(f"[{datetime.now()}] ⏳ Running scheduled forward job...")
    data = load_posted()

    all_posts = data["all_posts"]
    already_forwarded = data["forwarded"]

    remaining = [post for post in all_posts if post not in already_forwarded]

    if not remaining:
        print("✅ All posts forwarded once. Resetting cycle.")
        data["forwarded"] = []
        save_posted(data)
        remaining = all_posts

    if not remaining:
        print("⚠️ No posts available to forward yet.")
        return

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for chat_id, msg_id in selected:
        try:
            await client.copy_message(
                chat_id=PUBLIC_CHANNEL_ID,
                from_chat_id=chat_id,
                message_id=msg_id
            )
            data["forwarded"].append([chat_id, msg_id])
            print(f"✅ Forwarded message {msg_id}")
        except Exception as e:
            error_text = f"❌ Failed to forward message {msg_id}: {e}"
            print(error_text)
            await send_alert(error_text)
            if user_id:
                try:
                    await client.send_message(user_id, error_text)
                except:
                    pass

    save_posted(data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "✅ Bot chal raha hai!\n"
        f"⏰ Scheduled: {POSTS_PER_BATCH} posts at 10:00 AM & 11:00 PM IST\n"
        "📡 Source: Private channel me jo naye posts aaye, unko save karke schedule pe forward karega."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message):
    await message.reply_text("⏳ Abhi random posts forward ho rahe hain...")
    await forward_scheduled_posts(user_id=message.from_user.id)
    await message.reply_text("✅ Posts forward ho gaye!")


@client.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    data = load_posted()
    await message.reply_text(
        f"📊 Database Status:\n"
        f"Total saved posts: {len(data['all_posts'])}\n"
        f"Already forwarded: {len(data['forwarded'])}\n"
        f"Remaining: {len([p for p in data['all_posts'] if p not in data['forwarded']])}"
    )


# ===================== NEW: Manual Restore Command =====================
@client.on_message(filters.command("restore") & filters.private)
async def restore_command(client, message):
    try:
        download_from_github()
        data = load_posted()
        if data.get("all_posts") or data.get("forwarded"):
            await message.reply_text(f"✅ Backup restored successfully!\n"
                                     f"Total saved posts: {len(data['all_posts'])}\n"
                                     f"Already forwarded: {len(data['forwarded'])}")
        else:
            await message.reply_text("⚠️ Restore attempted but database is empty.")
    except Exception as e:
        await message.reply_text(f"❌ Restore failed: {e}")

# ===================== Main =====================
async def main():
    keep_alive()
    download_from_github()

    # ensure local DB exists (if GitHub 404)
    if not os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "w") as f:
            json.dump({"all_posts": [], "forwarded": []}, f)

    # initialize in-memory sets from restored DB
    data = load_posted()
    seen_posts.clear()
    seen_posts.update({tuple(x) for x in data.get("all_posts", [])})
    pending_set.clear()

    # start pyrogram client
    await client.start()

    # ensure webhook cleared so polling receives updates (helpful on Render)
    try:
        await client.delete_webhook(drop_pending_updates=False)
        print("🧹 Webhook cleared (polling enabled).")
    except Exception as e:
        print(f"⚠️ Could not delete webhook: {e}")

    # start background workers
    asyncio.create_task(queue_worker())
    asyncio.create_task(cleanup_missing_posts())   # runs every 10 minutes by default

    print("✅ Bot started and scheduler loaded!")

    # scheduler jobs
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()

    # keep process alive for handlers & workers
    await asyncio.Event().wait()


if __name__ == "__main__":
    client.run(main())
