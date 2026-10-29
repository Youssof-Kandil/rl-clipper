# Posting to YouTube and TikTok

RL Clipper can upload your exports straight to **YouTube** (Shorts and regular videos) and **TikTok** (as drafts in your inbox, or posted directly).

It uses **your own** Google and TikTok developer apps. You create them once (about 10 minutes for YouTube, 15–20 for TikTok) and paste their keys into RL Clipper. Nothing secret ships with RL Clipper. Your sign-in tokens stay on your computer in `data/accounts.json`.

**Where to start:** on the home page, click **Connect YouTube** / **Connect TikTok** in the *Post to YouTube & TikTok* card, or use **Settings** (top right). Both take you to **Settings → Accounts**. Inside a project, the **Post** panel's **Set up posting** button goes there too.

## What to expect

| | YouTube | TikTok |
|---|---|---|
| What happens | The video is uploaded to your channel. 9:16 videos up to 3 minutes become **Shorts** (`#Shorts` is added to the title). | **Inbox mode (default):** the video arrives in your TikTok inbox as a **draft**. You open TikTok, add sounds or edits, and post. **Direct mode:** posted straight away. |
| Before review | Uploads you mark *public* stay **private** until your Google project passes YouTube's API audit. Publish them in YouTube Studio with one click. | Inbox mode works from a **sandbox** with no review, for the accounts you add as target users. Direct mode needs TikTok's app audit; until then every direct post is private. |
| Scheduling | Yes: pick a time. YouTube publishes it even if your PC is off. | No: TikTok's API can't schedule. |
| Limits | A daily API quota (10,000 units by default; an upload costs 1,600 units in older docs and is reportedly ~100 since late 2025, so check your project's quota page). | About 5 pending inbox drafts per 24 hours. Post or delete drafts to send more. |

---

## YouTube setup (about 10 min)

Do this in your browser, signed in to the Google account that owns your channel.

### 1. Project and API
1. Open [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate). Name it `RL Clipper`, then **Create**. Make sure it's selected in the project picker at the top.
2. Open the [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) page and click **Enable**.

### 2. Consent screen ("Google Auth Platform")
Open the [Google Auth Platform](https://console.cloud.google.com/auth/overview) (older consoles: *APIs & Services → OAuth consent screen*) and click **Get started**.

1. **App name:** `RL Clipper`. **Support email:** yours. **Audience:** **External**. **Contact email:** yours. Then **Create**.
2. **Data access → Add or remove scopes:** tick `…/auth/youtube.upload` and `…/auth/youtube.readonly`, then **Update → Save**.
3. **Audience → Test users:** add your channel's Google account.
4. **Branding:** fill this page in before you can publish (see below). Use these values:

   | Field | Value |
   |---|---|
   | App logo | **leave empty**. A logo triggers Google's full verification review. |
   | Application home page | `https://<your-github-name>.github.io/rl-clipper/` (or the repository URL) |
   | Privacy policy link | `https://<your-github-name>.github.io/rl-clipper/PRIVACY.html` |
   | Terms of service link | `https://<your-github-name>.github.io/rl-clipper/TERMS.html` |
   | Authorized domains | `<your-github-name>.github.io` (or `github.com`) |
   | Developer contact | your email |

   Those pages come from **[your own GitHub Pages](#your-own-privacy-policy--terms-pages)**. Set them up first; TikTok needs them too.
5. **Audience → Publish app → Confirm.** This doesn't make anything public: it just stops "Testing" mode from signing you out every 7 days.

### 3. Keys
1. **Clients → Create client** (older: *Credentials → Create credentials → OAuth client ID*).
2. **Application type:** **Desktop app**. Name: `RL Clipper`. Click **Create**.
3. Copy the **Client ID** (`….apps.googleusercontent.com`) and **Client secret** (`GOCSPX-…`).
   - The downloadable `client_secret_….json` file is fine to keep, but **never share it or commit it**.

### 4. Connect
1. In RL Clipper, open **Settings → Accounts → YouTube**, paste both values, and click **Connect YouTube**.
2. Pick your channel's account. Google shows **"Google hasn't verified this app"**: that's expected for your own app. Click **Advanced → Go to RL Clipper (unsafe)**, allow both permissions, then **Continue**.
3. The tab says **"YouTube connected"**. Close it, then click **Save** in Settings.

**Optional:** to make uploads go public straight from the app, request the [YouTube API compliance audit](https://support.google.com/youtube/contact/yt_api_form).

---

## TikTok setup (about 15–20 min)

### 1. Developer account and app
1. Log in at [developers.tiktok.com](https://developers.tiktok.com) with the TikTok account you post from.
2. Click your avatar, then **Manage apps → Connect an app**. Choose **Individual** and name it `RL Clipper`.
3. **App details:**

   | Field | Value |
   |---|---|
   | Icon | any square image (1024×1024) |
   | Category | Entertainment |
   | Description | `Desktop app that clips my Rocket League gameplay into short videos and sends them to my TikTok inbox as drafts.` |
   | Terms of Service URL | `https://<your-github-name>.github.io/rl-clipper/TERMS.html` |
   | Privacy Policy URL | `https://<your-github-name>.github.io/rl-clipper/PRIVACY.html` |
   | Platforms | **Desktop** only. Web/Desktop URL: `https://<your-github-name>.github.io/rl-clipper/` |

4. **Verify the URLs.** TikTok shows *"This URL is not verified"*. Click **Verify URL properties → URL prefix**, enter `https://<your-github-name>.github.io/rl-clipper/`, download the **signature file** (`tiktok….txt`), add it to your Pages site ([below](#your-own-privacy-policy--terms-pages)), wait a minute, then click **Verify**.

### 2. Products and scopes
1. **Add products → Login Kit.** On the **Desktop** tab, set the redirect URI to exactly `http://127.0.0.1:8765/api/auth/tiktok/callback`.
2. **Add products → Content Posting API.** Leave **Direct Post off**. You don't need "Verify domains" (that's for pull-by-URL; RL Clipper uploads the file).
3. **Scopes:** `user.info.basic` and `video.upload`.

### 3. Use a Sandbox; skip "Submit for review" for now
The **Production** page won't save until you fill in **App review**: a written explanation plus a demo video. TikTok also requires new apps to record that demo **from a sandbox**. So:

1. Switch **Production → Sandbox** at the top and click **Create Sandbox** (copy settings from Production if offered).
2. Check the sandbox has the same platform, URLs (verify the prefix again if asked), Login Kit redirect URI, Content Posting API (Direct Post off) and scopes. Then **Save**.
3. **Sandbox settings → Target users → Add account:** log in with the TikTok account(s) you'll post to (up to 10).
4. Copy the **sandbox Client key and Client secret**. They're different from Production's.

### 4. Connect
In RL Clipper, open **Settings → Accounts → TikTok**, paste the sandbox key and secret, leave **Direct post** off, and click **Connect TikTok**. Authorize with a **target-user** account. The tab says **"TikTok connected"**. Then click **Save**.

### 5. Later, optional: Production review
You only need this if other people will use *your* TikTok app, or for **direct posting**. Record the sandbox flow (connect, then send a clip to the inbox, then the draft appearing in TikTok) and submit it with an explanation like:

> RL Clipper is a desktop app that runs on the creator's own computer. It detects goals and saves in their Rocket League gameplay recordings and exports short vertical videos. Login Kit (Desktop, user.info.basic): the creator connects their TikTok account in Settings → Accounts; we show their display name so they can see which account is connected. Content Posting API (video.upload): when the creator clicks "Send to TikTok inbox" on one of their exported clips, the app uploads that file (FILE_UPLOAD) to the creator's TikTok inbox as a draft; the creator then opens TikTok, edits and posts it themselves. Nothing is uploaded without the creator choosing the clip and clicking the button. Tokens are stored only on the creator's computer and can be revoked with Disconnect.

After approval, use the Production keys. For direct posting, add `video.publish`, tick **Direct post** in Settings, and click **Reconnect**.

---

## Your own privacy policy & terms pages

Google's Branding page and TikTok both want a privacy policy and terms of service at a URL you **own**. TikTok checks ownership with a signature file. A `github.com/…/blob/…` link can't hold that file, so use **GitHub Pages** (free):

1. **Fork** this repository on GitHub (or use your own copy). It already contains `PRIVACY.md` and `TERMS.md`; edit the name and contact in them if you like.
2. In your fork: **Settings → Pages → Build and deployment → Source: Deploy from a branch**, branch **main**, folder **/ (root)**, then **Save**.
3. After a minute your site is live:
   - `https://<your-github-name>.github.io/rl-clipper/`, which shows the README;
   - `https://<your-github-name>.github.io/rl-clipper/PRIVACY.html`;
   - `https://<your-github-name>.github.io/rl-clipper/TERMS.html`.
4. **TikTok's signature file:** add the downloaded `tiktok….txt` to the **root** of your fork (*Add file → Upload files*, commit to main). Check it opens at `https://<your-github-name>.github.io/rl-clipper/tiktok….txt`, then click **Verify** in TikTok. Keep the file there: TikTok may re-check it.

---

## Posting

1. Export from the **YouTube** or **TikTok** tab. Set **Size: Best** next to the export buttons for posting; see the FAQ on quality.
2. In the **Post** panel under the export buttons, click **YouTube** or **TikTok** next to an export.
3. Write the title or caption. It's pre-filled, e.g. "Epic save #RocketLeague". For YouTube there's also the description, tags, visibility and an optional schedule. Then click **Post** / **Send to TikTok inbox**.
4. Progress shows below, then a history line (a link for YouTube; "draft in your TikTok inbox" for TikTok).

---

## FAQ

**Will this let me post drafts to my own TikTok account?**
Yes. With the `video.upload` scope and your account added as a sandbox **target user**, RL Clipper sends videos to that account's inbox as drafts. No TikTok review is needed for that.

**TikTok says the upload worked, but I can't find the draft.**
- **Which account:** the draft goes to the account you authorized with when you clicked Connect. Settings → Accounts shows its name.
- **Where to look:** inbox drafts don't appear in your profile or Drafts at first. In the TikTok app (latest version), open **Inbox → System notifications**, or look for a notification like *"Your video is ready to edit"*. Tap it to open the editor; only then does it become a normal draft.
- **Sandbox:** TikTok only delivers to accounts listed as **target users**.
- **Limit:** you can have about 5 pending drafts at a time. Post or delete old ones.

**The uploaded video looks low quality. Why?**
- **The export size.** "Small" exports (HEVC, made to fit the phone apps' upload limits) are already compressed, and YouTube and TikTok compress again on top. Posting from RL Clipper goes through their API, which takes files up to several GB, so export at **Size: Best** for anything you'll post.
- **YouTube's first minutes.** Right after upload, YouTube serves a low-resolution version while it builds HD; give it a few minutes. Shorts are capped at 1080p and compressed hard either way.

**Google won't let me click "Publish app".**
The **Branding** page isn't complete. Add the home page, privacy policy and terms links, plus the authorized domain. Leave the logo empty. Or stay in Testing: it works the same, but you'll need to **Reconnect** every 7 days.

**TikTok says "This URL is not verified".**
TikTok must see you own the site. Use your own GitHub Pages URLs and its signature file ([above](#your-own-privacy-policy--terms-pages)); `github.com/…/blob/…` links can't be verified.

**TikTok won't let me save until I fill in App review.**
That's the Production config. Use a **Sandbox** instead: it saves without review, and its keys work right away for your target-user accounts.

**Is it safe to paste my client secret?**
Only into RL Clipper's Settings, which keeps it on your computer (`data/settings.json`). Don't post it anywhere else, and don't commit the downloaded `client_secret_….json`.

## Troubleshooting

| Message | Fix |
|---|---|
| "Add your … app keys in Settings → Accounts first" | Paste the keys and click Connect. |
| "sign-in failed: invalid_client" / "redirect_uri mismatch" | Check the keys for typos. For TikTok, the redirect URI must be exactly `http://127.0.0.1:8765/api/auth/tiktok/callback`, and the keys must come from the sandbox where your account is a target user. For Google, the client type must be **Desktop app**. |
| "Your sign-in expired" | Disconnect, then connect again. On Google, publish the app (Testing mode expires sign-ins weekly). |
| Uploaded as private | Expected until YouTube audits your Google project. Publish in YouTube Studio. |
| "quota is used up" | Your project's daily YouTube quota resets at midnight Pacific time. You can request more in the Cloud Console. |
| "The chunk size is invalid" (TikTok) | Fixed in RL Clipper. Update to the latest version. |
| "only a few pending drafts per day" | Post or delete the drafts in your TikTok inbox. |
| "app isn't audited yet, so direct posts must be private" | Turn off **Direct post** to use inbox drafts, or complete TikTok's audit. |

Your tokens are stored in `data/accounts.json` on this computer. **Disconnect** deletes them and revokes them with Google or TikTok.
