import os
import glob
import asyncio
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client(
    "screenshot_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

STORAGE_DIR = tempfile.mkdtemp()
stored_video = {"path": None}


def time_to_seconds(t: str) -> float:
    parts = list(map(float, t.strip().split(":")))
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    elif len(parts) == 2:
        return parts[0]*60 + parts[1]
    return parts[0]


def seconds_to_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


async def get_duration(video_path: str) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
        stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    return float(stdout.decode().strip() or 0)


async def download_with_progress(replied, dest_path, status):
    last_update = {"time": 0.0}

    async def progress(current, total):
        now = asyncio.get_event_loop().time()
        if total and (now - last_update["time"] > 4 or current == total):
            last_update["time"] = now
            percent = current * 100 / total
            try:
                await status.edit(f"Downloading video... {percent:.0f}%")
            except:
                pass

    return await replied.download(file_name=dest_path, progress=progress)



async def extract_frames(video_path: str, tmp: str, start_offset: float, interval: float, end_offset: float):
    pattern = os.path.join(tmp, "frame_%05d.jpg")
    span = max(0.1, end_offset - start_offset)

    cmd = ["ffmpeg", "-y"]
    if start_offset > 0:
        cmd += ["-ss", str(start_offset)]
    cmd += ["-i", video_path, "-t", str(span), "-vf", f"fps=1/{interval}", "-q:v", "2", pattern]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()

    files = sorted(glob.glob(os.path.join(tmp, "frame_*.jpg")))
    results = []
    for idx, path in enumerate(files):
        t = start_offset + idx * interval
        results.append((path, seconds_to_time(t)))
    return results


@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply(
        "**Personal Screenshot & Trim Bot**\n\n"
        "• `/store` (reply to a video) → store it for this session\n"
        "• `/ss` → 20 screenshots\n"
        "• `/ss every 10` → one every 10 seconds\n"
        "• `/ss 00:00:00 00:24:37` → one every 0.8s within that range\n"
        "• `/trim 00:01:20 00:02:45` → cut a clip\n\n"
        "Once you `/store` a video, `/ss` and `/trim` work without replying again."
    )


@app.on_message(filters.command("store") & filters.reply)
async def store_command(_, message: Message):
    replied = message.reply_to_message
    if not (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        return await message.reply("Please reply to a video.")

    status = await message.reply("Storing video for this session...")

    video_path = await download_with_progress(replied, os.path.join(STORAGE_DIR, "stored_video.mp4"), status)
    stored_video["path"] = video_path

    duration = await get_duration(video_path)

    await status.edit(
        f"Video stored for this session.\n"
        f"Duration: {seconds_to_time(duration)}\n\n"
        f"Now `/ss` and `/trim` will use this video automatically."
    )


async def resolve_video(message: Message, tmp: str, status: Message):
    replied = message.reply_to_message
    if replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        return await download_with_progress(replied, os.path.join(tmp, "video.mp4"), status)
    if stored_video["path"] and os.path.exists(stored_video["path"]):
        return stored_video["path"]
    return None


@app.on_message(filters.command("ss"))
async def ss_command(_, message: Message):
    args = message.command[1:]
    interval_seconds = None
    count = 20
    range_start = None
    range_end = None

    if len(args) == 2 and args[0].lower() == "every":
        try:
            interval_seconds = max(0.1, float(args[1]))
        except:
            return await message.reply("Usage: `/ss every 10` for one screenshot every 10 seconds.")
    elif len(args) == 2 and ":" in args[0] and ":" in args[1]:
        try:
            range_start = time_to_seconds(args[0])
            range_end = time_to_seconds(args[1])
            interval_seconds = 0.8
        except:
            return await message.reply("Usage: `/ss 00:00:00 00:24:37`")
        if range_end <= range_start:
            return await message.reply("End time must be after start time.")
    elif len(args) > 0:
        return await message.reply(
            "Usage:\n"
            "`/ss` → 20 screenshots\n"
            "`/ss every 10` → one every 10 seconds\n"
            "`/ss 00:00:00 00:24:37` → one every 0.8s within that range"
        )

    status = await message.reply("Generating screenshots with timestamps...")

    with tempfile.TemporaryDirectory() as tmp:
        video_path = await resolve_video(message, tmp, status)
        if not video_path:
            return await status.edit("Please reply to a video, or `/store` one first.")

        duration = await get_duration(video_path)
        if duration < 1:
            return await status.edit("Could not read video duration.")

        if range_start is not None:
            start_offset = range_start
            end_offset = min(range_end, duration)
            interval = interval_seconds
        elif interval_seconds:
            start_offset = interval_seconds
            end_offset = duration
            interval = interval_seconds
        else:
            interval = duration / (count + 1)
            start_offset = interval
            end_offset = duration

        screenshots = await extract_frames(video_path, tmp, start_offset, interval, end_offset)

        if not screenshots:
            return await status.edit("Failed to generate screenshots.")

        for idx, (path, timestamp) in enumerate(screenshots):
            is_last = idx == len(screenshots) - 1
            await message.reply_photo(path, caption=timestamp, quote=is_last)

        await status.delete()


@app.on_message(filters.command("trim"))
async def trim_command(_, message: Message):
    if len(message.command) < 3:
        return await message.reply(
            "Usage:\n`/trim START END`\n\n"
            "Examples:\n"
            "`/trim 00:01:20 00:02:45`\n"
            "`/trim 1:20 2:45`\n"
            "`/trim 80 165`"
        )

    try:
        start = time_to_seconds(message.command[1])
        end = time_to_seconds(message.command[2])
    except:
        return await message.reply("Invalid time format.")

    if end <= start:
        return await message.reply("End time must be greater than start time.")

    status = await message.reply(f"Trimming from {seconds_to_time(start)} → {seconds_to_time(end)}...")

    with tempfile.TemporaryDirectory() as tmp:
        video_path = await resolve_video(message, tmp, status)
        if not video_path:
            return await status.edit("Please reply to a video, or `/store` one first.")

        output_path = os.path.join(tmp, "trimmed.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c", "copy",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()

        if not os.path.exists(output_path):
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", video_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac",
                output_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

        if os.path.exists(output_path):
            await message.reply_video(
                output_path,
                caption=f"Trimmed: {seconds_to_time(start)} → {seconds_to_time(end)}"
            )
            await status.delete()
        else:
            await status.edit("Failed to trim the video.")


@app.on_message(filters.video | filters.document)
async def on_video(_, message: Message):
    if message.document and not (message.document.mime_type or "").startswith("video/"):
        return
    duration = message.video.duration if message.video else None
    duration_text = f"Duration: {seconds_to_time(duration)}\n\n" if duration else ""
    await message.reply(
        f"Video received!\n{duration_text}"
        "Reply with:\n"
        "• /store → save it for this session (then use `/ss` and `/trim` without replying again)\n"
        "• /ss → 20 screenshots\n"
        "• /trim 00:01:20 00:02:45 → cut clip"
    )


if __name__ == "__main__":
    print("Bot started...")
    app.run()
