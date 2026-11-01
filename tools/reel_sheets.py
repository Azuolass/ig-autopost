"""Read-only: download chosen reels from the IG API and make contact sheets in out/sheets."""
import json, os, subprocess, requests
from autopost.instagram import Instagram
cfg = json.load(open("config.json"))
ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID") or "me", cfg["graph_api_base"])
me = ig.me(); ig.user_id = str(me["user_id"])
links = {r["link"]: r for r in json.load(open("tools/_winners.json"))}
os.makedirs("out/sheets", exist_ok=True)
info = []
for m in ig.edge(f"{ig.user_id}/media", fields="id,permalink,media_url,media_product_type", limit=50, max_items=120):
    r = links.get(m["permalink"])
    if not r or not m.get("media_url"):
        continue
    name = f'{r["views"]:05d}'
    open("v.mp4", "wb").write(requests.get(m["media_url"], timeout=120).content)
    dur = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "v.mp4"]).decode().strip()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "v.mp4", "-vf", "fps=1,scale=216:384,tile=8x3", "-frames:v", "1", f"out/sheets/{name}.jpg"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "v.mp4", "-t", "25", "-vn", "-ac", "1", "-b:a", "64k", f"out/sheets/{name}.mp3"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "v.mp4", "-vf", "scale=540:-2", "-c:v", "libx264", "-crf", "30", "-an", f"out/sheets/{name}_low.mp4"])
    info.append({"views": r["views"], "file": r["file"], "dur": dur})
json.dump(info, open("out/sheets/info.json", "w"), indent=1, ensure_ascii=False)
print(info)
