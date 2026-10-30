# AGENTS.md — Success Hunters Instagram autopilot

Read this first. It is the full handover of the system built for the Instagram account
**@successhunters.prints** (Creator account, store successhuntersprints.com, motivational /
athlete canvas wall art). Owner/operator: Azuolas Savickas. **Talk to him in Lithuanian, short and
plain.** He is not a developer: give exact clicks, never ask him to edit code.

## 1. What runs where

| Part | Where | When | What it does |
|---|---|---|---|
| Publishing | GitHub Actions, `comments-loop.yml` → `python -m autopost.queue` | checks every minute | Publishes each entry in `trigger/queue.json` when its Vilnius time comes (via `autopost.publish --date --slot`). |
| Comment replies | same loop → `python -m autopost.comments` | every 5 min | Replies with templates, lowercase; emoji-only or unmatched comments get one emoji; unknown questions → Discord. |
| Like watcher | `likes.yml` → `autopost.likes` | hourly | Discord message when a post reaches 500 likes. |
| Token refresh | `check-and-refresh.yml` | Mondays 09:17 UTC | Refreshes the 60-day Instagram token and saves it with `gh secret set` (needs `GH_PAT`). |
| Prepare/review | `prepare.yml` (push `trigger/prepare.json`) | on demand | Builds clean JPGs + captions + review sheets for a date range into the orphan branch `prepared`. |
| Inspect one Drive file | `inspect.yml` (push `trigger/inspect.json`) | on demand | Downloads one image, reports/repairs it into branch `inspect`. |
| Music, story, hide likes | **Codex computer use on the owner's Mac** in BlueStacks Air (Instagram app) | +6 min after each post | The Instagram API cannot do these. See §6. |

`comments-loop.yml` runs ~5.5 h and re-dispatches itself (plus a 6-hourly cron as backup). GitHub's own
cron is often hours late — that is why publishing is driven by this loop, not by cron.

`publish.yml` still has the old New York crons; they do nothing because `config.json`
`"publishing_paused": true`. Keep it true. Push of `trigger/publish.json` still publishes one post
on demand (`{"date","slot","at"?(UTC),"force"?}`).

## 2. Content source (Google Drive)

`<root>/<YYYY.MM>/<D.MM.YYYY>/<NN_Post_Name>/` with images `01_*.png … 13_*.png` (numeric order =
carousel order, 01 = the original artwork) and `instagram_caption*.pdf` (`*updated*` preferred).
Root folder id: secret `DRIVE_ROOT_FOLDER_ID` (falls back to `config.json`). Access via the service
account in `GOOGLE_SERVICE_ACCOUNT_JSON`. Marketing uploads the folders; nothing to do on our side.

Key in all state files = `"<D.MM.YYYY day as ISO date>#<slot>"`, e.g. `2026-10-25#3` = folder
`25.10.2026/03_…`.

## 3. Files you will touch

| File | Purpose |
|---|---|
| `trigger/queue.json` | The schedule. One line per post: `{"date":"2026-10-29","slot":1,"at":"2026-10-29 15:00"}` (Vilnius time). `"skip":true` = don't publish. Posts >3 h late are skipped and reported. |
| `state/published.json` | What went out: `title, permalink, song, song_index, published_at`. Never delete entries (it prevents double posting and drives song order). Manual posts are recorded as `{"title":…, "manual":true}`. |
| `music/library.json` | The account's Instagram **Saved** songs, in Saved order (108). Rotation: next post gets `last song_index + 1`, wrapping around. `music/plan.json` can force a song for a key. |
| `review/skip.json` | Image numbers to leave out of a post (AI glitches), e.g. `{"2026-10-26#2":["06"]}`. |
| `replies/templates.json` | 20 owner-written reply templates (triggers → reply), praise replies, `emoji_only.replies`, spam patterns. |
| `config.json` | Image size/quality, comment limits, `publishing_paused`. |
| `state/comments.json`, `state/likes.json` | Bot memory; don't edit by hand. |
| `agent/voice.md`, `agent/skills/ig-*` | Brand voice and Instagram writing playbooks (captions, replies, DMs, reels…). Use them when writing anything in the brand's name. |

Code: `autopost/` (publish, queue, drive, captions, images, music, comments, likes, instagram,
notify, refresh_token, check_setup, prepare). Tests: `python -m pytest -q` (all must pass before push).

## 4. Everyday tasks (how to do them)

**Schedule new days** (current standard times 15:00, 19:00, 21:00 Vilnius): append to
`trigger/queue.json` three lines per day; commit + push to `main`. Before scheduling, optionally run
prepare for those dates (push `trigger/prepare.json` `{"from","to","run":<n+1>}`), then check
`summary.json` on branch `prepared` for missing folders, broken files, warnings.

**Change a time**: edit that entry's `"at"` in `queue.json` (only for posts not yet in `published.json`).

**Publish one post now**: push `trigger/publish.json` with `{"date":"YYYY-MM-DD","slot":N}` (add
`"at":"<UTC ISO>"` to make the job wait until then).

**Remove an image**: add its number to `review/skip.json` under the post key.

**Change a reply**: edit `replies/templates.json`; run tests; push. Style rules below.

## 5. Rules the owner set (keep them)

- **Caption style (owner's standing rule, 29.10.2026):** text from the Drive PDF, all lowercase, short lines
  with a blank line between paragraphs, ending `shop now. "<Product Name>". link in bio.` Only the product
  name in quotes keeps its capitals. The PDF header (`<Title> Instagram caption SH IG DAILY <date>`) is
  never part of the caption. All of this is enforced in `captions.clean_caption`; check `summary.json` /
  `caption.txt` on branch `prepared` before scheduling new days.
- Replies follow `Success_Hunters_Instagram_AI_Response_Guide.txt` (27.10.2026): short, lowercase,
  emoji-led. Order: spam → skip; bare tag of a friend → skip; emoji only → one emoji from
  `🫡 🧨 🚀 🔥 🙌 🖤 💯 👏`; customer issue → short "DM us your order number" + Discord;
  criticism / AI / originality → no reply, Discord; then templates (e.g. `link in bio 👀`), agreement
  (`💯`, `always. 🫡`), athlete names → `🐐`, fan debates ("messi > ronaldo") → skip, short hype → one
  emoji, real compliments (4+ words) → words; image/GIF comments (no text in the API) → skip; unknown question → Discord. **Never 🤔 or 🤫.** Don't claim
  worldwide shipping: ask the country. Mentions of @successhunters.prints are ignored when matching.
- Images: metadata (EXIF/XMP/C2PA) is stripped on every upload. **Do not try to remove or defeat AI
  watermarks (visible or invisible, e.g. SynthID) or Instagram's "AI info" label.** Instagram sometimes
  labels posts "Likely made with AI" from the pixels; that is accepted.
- No automatic likes/comments on other accounts. Do not like comments by automation.
- Never put tokens/keys in chat, code or docs — only GitHub Secrets. Never ask the owner to paste them.
- Don't publish anything the owner didn't schedule. Ask before irreversible actions.
- A Drive file cut at its end marker but with a complete picture is used (`images.check_decodable`);
  a really truncated one is skipped and reported.

## 6. Codex on the Mac: music, story, hide likes

Instagram's API cannot add music to carousels, hide likes or share a post to the story, so this part
runs in the Instagram Android app inside **BlueStacks Air** on the owner's Mac mini (logged in as
successhunters.prints). Codex Computer Use: allow only BlueStacks ("Always allow"); Mac awake and
unlocked; BlueStacks open in front. Automation at **15:06, 19:06, 23:06 Europe/Vilnius**.

Per post (≈3 min), in this order:
1. Read `state/published.json` (raw: `https://raw.githubusercontent.com/Azuolass/ig-autopost/main/state/published.json`),
   take the newest `published_at` (stop if >40 min old), note `title`, `permalink`, `song`.
2. Instagram → profile tab → pull to refresh → open the first post; check it matches the title.
3. If the post header already shows a song, a person added one: leave it. Otherwise ⋯ → Edit →
   Add audio → Search "<song> <artist>" → pick the result with the **filled bookmark** (Saved version)
   → confirm → ✓ → ✓.
4. Share (paper plane) → Add to story → deny camera/mic → "Your stories". No drawing/text/stickers.
5. **Last**: ⋯ → Hide like count; reopen ⋯ and confirm it says "Unhide like count" (editing the
   post un-hides likes, so this must come after step 3).
6. Report in Lithuanian: title, link, song, story yes/no, likes hidden yes/no, failures.

Do NOT use Instagram's own "Schedule this post": scheduling drops the music and story sharing.
If you ever need to upload images into BlueStacks: `docs/dl.html?p=<prepared folder name>` opened in
BlueStacks Chrome downloads a prepared post into the Android gallery.

## 7. Accounts, secrets, external pieces (no values here)

- GitHub repo `Azuolass/ig-autopost` (public; Actions need "Read and write" workflow permissions).
- Secrets: `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_API_KEY`,
  `DRIVE_ROOT_FOLDER_ID`, `DISCORD_WEBHOOK_URL`, `GH_PAT` (fine-grained, this repo, Secrets read/write).
- Meta app (developers.facebook.com, owner's account), "Instagram API with Instagram Login", **Live**
  mode (required to read other people's comments). Privacy/data-deletion pages: GitHub Pages from
  `docs/` → `https://azuolass.github.io/ig-autopost/privacy.html`.
- Google Cloud project with a service account that has Viewer access to the Drive folder.
- Discord channel webhook = all notifications.
- API limits: 200 calls/hour per user (we use < 100); 100 posts/day (we post 3). All free.

## 8. Open items / history

- Scheduled through 28.10.2026; folders for 29–31.10 did not exist yet on 22.10.
- Branch `drive-private` (folder id only from secret + privacy check) is not merged.
- 25.10 15:00 post got music + hidden likes by a person; 19:00 done by automation; 23:00 by Claude.
- Old schedule (US prime time 20:00/00:00/04:00 LT) was replaced by 15/19/23 LT on 23–24.10.
- The service-account key was once visible in a screenshot — rotating it is recommended.
