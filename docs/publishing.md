# Posting to YouTube and TikTok

RL Clipper can upload your exports straight to **YouTube** (Shorts and regular videos) and **TikTok**.

It uses **your own** Google and TikTok developer apps. You create them once (about 10 minutes each) and paste their keys into **Settings → Accounts**. Nothing secret ships with RL Clipper. Your sign-in tokens stay on your computer in `data/accounts.json`.

## What to expect

| | YouTube | TikTok |
|---|---|---|
| What happens | The video is uploaded to your channel. 9:16 videos up to 3 minutes become **Shorts** (`#Shorts` is added to the title). | **Inbox mode (default):** the video arrives in your TikTok inbox as a **draft**. Open TikTok, tap the notification, add sounds or edits, and post. **Direct mode:** posted straight away. |
| Before review | Uploads are **forced to private** until your Google project passes YouTube's API audit. Publish them in YouTube Studio with one click. | Inbox mode needs **no review**. Direct mode needs TikTok's app audit; until then every direct post is private. |
| Scheduling | Yes: pick a time. YouTube publishes it even if your PC is off. | No: TikTok's API can't schedule. |
| Limits | A daily API quota (10,000 units by default). An upload costs 1,600 units in older docs and is reportedly ~100 since late 2025; check your project's quota page. | About 5 pending inbox drafts per 24 hours. Post or delete drafts to send more. |

## YouTube setup

1. **Create a Google Cloud project.** Go to [console.cloud.google.com](https://console.cloud.google.com), open the project menu, choose **New project** (any name, e.g. "RL Clipper"), and select it.
2. **Enable the API.** Go to *APIs & Services → Library*, search for **YouTube Data API v3**, and click **Enable**.
3. **Set up the OAuth consent screen** under *APIs & Services → OAuth consent screen* (in newer consoles, *Google Auth Platform*).
   1. **User type:** External. App name: "RL Clipper". Use your email for both email fields.
   2. **Scopes:** add `.../auth/youtube.upload` and `.../auth/youtube.readonly`.
   3. **Test users:** add the Google account that owns your channel.
   4. **Publish the app** (*Publishing status → In production*). In "Testing" mode, Google expires your sign-in every 7 days. Google may show "unverified app": for your own channel that's fine. Click *Advanced → Go to RL Clipper*.
4. **Create the keys** under *APIs & Services → Credentials → Create credentials → OAuth client ID*.
   - Application type: **Desktop app**. Name: "RL Clipper".
   - Copy the **Client ID** and **Client secret**.
5. **Connect in RL Clipper.** Go to *Settings → Accounts → YouTube*, paste both, and click **Connect YouTube**. Sign in with your channel's account and allow access. The tab says "YouTube connected".
6. **Optional: public uploads.** To have uploads go public straight from RL Clipper, request the [YouTube API compliance audit](https://support.google.com/youtube/contact/yt_api_form) for your project. Until then, uploads stay private.

## TikTok setup

1. **Developer account and app.** Sign up at [developers.tiktok.com](https://developers.tiktok.com), then go to *Manage apps → Connect an app*.
2. **Fill in the app details.** TikTok asks for an app icon, a description, and links to Terms and a Privacy Policy. Your GitHub repository's README or a simple page works.
3. **Add products:**
   - **Login Kit**, platform **Desktop**. Redirect URI: `http://127.0.0.1:8765/api/auth/tiktok/callback`. If you run RL Clipper on another port, use that port, or TikTok's wildcard port.
   - **Content Posting API**.
4. **Scopes:** `user.info.basic` and `video.upload`. Add `video.publish` only if you'll use direct posting.
5. **Sandbox:** while the app isn't reviewed yet, create a **Sandbox** and add your TikTok account as a target user. That lets you connect and test right away.
6. **Connect in RL Clipper.** Copy the **Client key** and **Client secret** into *Settings → Accounts → TikTok* and click **Connect TikTok**.
7. **Optional: direct posting.** Submit your app for review and the Content Posting API audit (TikTok asks for a demo video and a description of the posting flow). Once approved, tick **Direct post** in Settings and click **Reconnect**, which adds the `video.publish` permission.

## Posting

1. Export from the **YouTube** or **TikTok** tab.
2. In the **Post** panel under the export buttons, your exports are listed. Click **YouTube** or **TikTok** on one.
3. Write the title or caption (pre-filled, e.g. "Epic save #RocketLeague"), and for YouTube the description, tags, visibility and an optional schedule.
4. Click **Post**. Progress shows below, and a history line links to the result.

## Troubleshooting

| Message | Fix |
|---|---|
| "Add your … app keys in Settings → Accounts first" | Paste the keys and click Connect. |
| "sign-in failed: invalid_client" / "redirect_uri mismatch" | Check the keys for typos. For TikTok, the redirect URI in the developer portal must be exactly `http://127.0.0.1:8765/api/auth/tiktok/callback`. For Google, the client must be the **Desktop app** type. |
| "Your sign-in expired" | Disconnect, then connect again. On Google, publish the consent screen (Testing mode expires sign-ins weekly). |
| Uploaded as private | Expected until YouTube audits your Google project. Publish in YouTube Studio. |
| "quota is used up" | Your project's daily YouTube quota resets at midnight Pacific time. You can request more in the Cloud Console. |
| "only a few pending drafts per day" (TikTok) | Post or delete the drafts in your TikTok inbox. |
| "app isn't audited yet, so direct posts must be private" | Turn off **Direct post** to use inbox drafts, or finish TikTok's audit. |

Your tokens are stored in `data/accounts.json` on this computer. **Disconnect** deletes them and revokes them with Google or TikTok.
