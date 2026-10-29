# Contributing to RL Clipper

Thanks for helping! RL Clipper is created and maintained by **[Youssof Kandil (@Youssof-Kandil)](https://github.com/Youssof-Kandil)**. Bug reports, ideas and pull requests are all welcome.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting a bug

Anyone can report a problem. Use **[New issue → Bug report](../../issues/new/choose)**. The form asks for what we need to fix it fast:

- **What you did and what happened**, plus what you expected instead.
- **Your setup:** OS, GPU (or "none"), and the app's version or commit.
- **The "This computer" panel** from the home page (copy its lines).
- **The terminal output** of `run.ps1` / `run.sh` around the error.
- **For wrong or missing clips:** the time in the video, the play type, whether the match had a saved replay, and what the **Matches** panel says the sync source was.

Please search [existing issues](../../issues) first, and add your details there if your problem is already reported.

Never attach replay files or recordings you don't want public, and never post passwords or tokens.

**Security problems:** don't open a public issue. See [SECURITY.md](SECURITY.md).

## Suggesting a feature

Use **[New issue → Feature request](../../issues/new/choose)**. Describe the problem you want solved, not just the solution. For example, "my TikToks are too long to upload" is more useful than "add a bitrate slider".

## Making changes

### Ground rules

1. **Open an issue first** for anything bigger than a small fix, so we can agree on the approach before you spend time on it.
2. **One topic per pull request.** Small PRs get reviewed and merged much faster.
3. **Keep it working everywhere.** RL Clipper must run on Windows, macOS and Linux, with or without an NVIDIA GPU, with or without Rocket League replays. Anything GPU- or OS-specific needs a fallback. The "This computer" panel and `GET /api/health` show what's available.
4. **Add tests** for detection, sync, captions and export logic (`backend/tests`). CI must pass.
5. **Keep it local.** RL Clipper never uploads anything. Don't add telemetry, accounts or network calls, except for downloads the user starts (models, rrrocket).
6. **Attribution stays.** Don't remove or alter the copyright and attribution notices in `LICENSE`, `NOTICE`, the README or the app's footer. See [License](#license) below.

### Setup

Requirements: ffmpeg, [uv](https://docs.astral.sh/uv/) and Node.js 20+ (see the [README](README.md#requirements)).

```bash
# Windows
.\run.ps1 -Dev
# macOS / Linux
bash run.sh --dev
```

This starts the backend with auto-reload and the Vite dev server with hot reload at http://localhost:5173.

### Tests and checks

```bash
cd backend
uv run pytest                 # whole suite, about 100 tests
cd ../frontend
npm run build                 # type-checks (tsc) and builds the UI
```

Useful helpers:

- `uv run python tests/make_sample.py ../data/sample.mkv` makes a synthetic test recording.
- `uv run python -m app.detect <video> --debug <dir>` runs detection from the command line and saves every OCR crop.
- The replay JSON helpers in `tests/test_replays.py` let you build replay scenarios without real `.replay` files.

### Code style

- **Python:** 3.10+ syntax with type hints. Keep functions small and documented where the *why* isn't obvious. Follow the style of the surrounding code.
- **TypeScript / React:** function components and hooks. No UI framework, plain CSS in `styles.css` using the existing CSS variables.
- **Comments:** explain intent and Rocket League / ffmpeg quirks, not the obvious.
- **Text in the UI:** short, plain words. Say what will happen.

### Pull requests

1. Fork the repo and create a branch from `main` (`fix/clock-ocr-overtime`, `feat/vertical-zoom`, …).
2. Make your change and add tests. Run `uv run pytest` and `npm run build`.
3. Fill in the pull request template: what changed and why, how you tested it, and screenshots for UI changes.
4. Respond to review. The maintainer may ask for changes before merging.

## License

RL Clipper is licensed under the **[Apache License 2.0](LICENSE)**.

By submitting a contribution, you agree that it's licensed under the same license (Apache-2.0, Section 5).

Forks and redistributions must keep the [NOTICE](NOTICE) file crediting Youssof Kandil, and must mark files they changed (Apache-2.0, Section 4).
