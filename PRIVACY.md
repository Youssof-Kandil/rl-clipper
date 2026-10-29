# Privacy Policy

*Last updated: 29 October 2026*

RL Clipper is open-source software by Youssof Kandil ([@Youssof-Kandil](https://github.com/Youssof-Kandil)) that you run on your own computer. This policy explains what happens with your data when you use it, including when you connect a YouTube or TikTok account.

## The short version

- RL Clipper runs **entirely on your computer**. There is no RL Clipper server, account, analytics or tracking.
- Your recordings, clips, captions and settings stay on your computer, in the app's `data/` folder.
- When you connect YouTube or TikTok, the sign-in tokens are stored **only on your computer** (`data/accounts.json`). They are used only to upload the videos you choose to post.
- Nothing is sent to the developer of RL Clipper. Ever.

## What RL Clipper accesses

**Your videos and Rocket League replays.** RL Clipper reads the recordings you open and your local Rocket League replay files to find plays. They are processed on your computer and never uploaded, unless you choose to post an export.

**Your voice (captions).** Captions are made by a speech-recognition model (Whisper) that runs on your computer. Audio is not sent anywhere.

**YouTube (Google) account, if you connect it.** RL Clipper requests:

- `youtube.upload`, to upload the videos you choose to post, with the title, description, tags, visibility and schedule you enter;
- `youtube.readonly`, to show which channel is connected.

It does not read, change or delete your other videos, comments, subscriptions or account data.

**TikTok account, if you connect it.** RL Clipper requests:

- `user.info.basic`, to show which account is connected;
- `video.upload`, to send the videos you choose to your TikTok inbox as drafts;
- `video.publish`, only if you turn on direct posting, to post the videos you choose with the caption and privacy you pick.

It does not read your other content, followers or messages.

## Where data goes

Data goes to a third party only when you ask:

- videos you post go to **YouTube** (Google) or **TikTok**;
- the speech model is downloaded once from **Hugging Face**;
- the replay parser (rrrocket) is downloaded once from **GitHub**.

Their own privacy policies apply to those services: the [Google Privacy Policy](https://policies.google.com/privacy), the [TikTok Privacy Policy](https://www.tiktok.com/legal/privacy-policy) and the [YouTube Terms of Service](https://www.youtube.com/t/terms).

RL Clipper's use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Keeping and deleting your data

Everything RL Clipper stores is in its `data/` folder on your computer. Delete that folder to remove it.

To disconnect an account:

1. Click **Disconnect** in Settings → Accounts. This deletes the tokens and revokes them with Google or TikTok.
2. Or revoke access yourself: for Google at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), and for TikTok in the app under *Settings → Security → Apps*.

## Children

RL Clipper is not directed at children under 13.

## Changes and contact

Changes to this policy are published in this file, in the [project repository](https://github.com/Youssof-Kandil/rl-clipper). Questions: [open an issue](https://github.com/Youssof-Kandil/rl-clipper/issues), or contact the maintainer through their GitHub profile.
