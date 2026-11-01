"""Read-only: dump every post with its insights to out/insights.json."""
import json, os, sys
from autopost.instagram import Instagram, InstagramError

cfg = json.load(open("config.json"))
ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID") or "me", cfg["graph_api_base"])
me = ig.me(); ig.user_id = str(me["user_id"])
fields = "id,caption,permalink,timestamp,media_type,media_product_type,like_count,comments_count,media_url,thumbnail_url"
media = list(ig.edge(f"{ig.user_id}/media", fields=fields, limit=50, max_items=400))
REEL = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions",
        "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
OTHER = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions"]
errors = {}
for m in media:
    metrics = REEL if m.get("media_product_type") == "REELS" else OTHER
    ins = {}
    try:
        d = ig._call("GET", f"{m['id']}/insights", metric=",".join(metrics))
        for row in d.get("data", []):
            ins[row["name"]] = (row.get("values") or [{}])[0].get("value", row.get("total_value", {}).get("value"))
    except InstagramError as e:
        # retry one metric at a time so one unsupported metric does not hide the rest
        for k in metrics:
            try:
                d = ig._call("GET", f"{m['id']}/insights", metric=k)
                for row in d.get("data", []):
                    ins[row["name"]] = (row.get("values") or [{}])[0].get("value")
            except InstagramError as e2:
                errors.setdefault(k, str(e2)[:200])
    m["insights"] = ins
acct = {}
try:
    acct = ig._call("GET", f"{ig.user_id}", fields="username,followers_count,media_count")
except InstagramError as e:
    errors["account"] = str(e)[:200]
os.makedirs("out", exist_ok=True)
json.dump({"account": acct, "media": media, "errors": errors}, open("out/insights.json", "w"), indent=1, ensure_ascii=False)
print(len(media), "posts;", "errors:", json.dumps(errors)[:1500])
