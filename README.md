# Half-Light

A pseudonymous photo showcase built with a deterministic composition pipeline and static site. The pipeline grades, processes, and composes photos from a source directory, emitting a static HTML gallery that deploys to Cloudflare Pages.

## How SYNC Works

**Quick Deploy:** Double-click `deploy\SYNC.bat` to grade new photos, build the site, and push to Cloudflare.

**Recommended:** Create a `.lnk` shortcut to `deploy\SYNC.bat` in your Windows Favorites folder. Shortcuts ensure that future bat updates propagate automatically. (Plain copies of `.bat` also work since the script uses an absolute `cd /d` path, but shortcuts handle future updates seamlessly.)

## One-Time Setup

1. **Create a private GitHub repository** on GitHub.
2. **Add the remote** to your local clone:
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   ```
3. **Push to GitHub (after the project's finish step):**
   Once the project finish merges `build` → `master`, verify the site files are on master:
   ```bash
   git log master --oneline
   ```
   If the log doesn't show the site files, manually merge and push:
   ```bash
   git checkout master
   git merge build
   git push -u origin master
   ```

4. **Connect to Cloudflare Pages:**
   - Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
   - Navigate to **Workers & Pages** → **Pages**
   - Click **Create** → **Connect to Git**
   - Select your repository
   - **Production branch:** `master`
   - **Build command:** Leave empty (the site is pre-built locally)
   - **Build output directory:** `site`
   - Click **Save and deploy**

5. **After the first deploy, set the social-preview image:**
   Edit `site/index.html` and `site/contact.html` and change the `og:image` tags from `photos/og.jpg` to `https://<your-project>.pages.dev/photos/og.jpg` (or your custom domain). Relative og:image URLs are ignored by most social scrapers.

6. **Optional:** Add a custom domain in the Pages project settings.

After setup, every `SYNC` push automatically triggers a Cloudflare deployment (about 1 minute).

## Branch Safety (master is SYNC-only)

Repo-tracked git hooks (`deploy/githooks/`, wired via `git config core.hooksPath deploy/githooks`) block direct commits and pushes to `master`. Only `SYNC.bat` (which sets `HALFLIGHT_SYNC=1`) writes to master — so photo syncs stay clean and linear while any development work is forced onto branches:

- Development: `git checkout -b feature/<name>` — work, then merge deliberately with `HALFLIGHT_SYNC=1 git merge feature/<name>` from master.
- Deliberate admin on master: prefix the command with `HALFLIGHT_SYNC=1`.
- Fresh clone setup: run `git config core.hooksPath deploy/githooks` once (the hooks travel with the repo).

## Changing the Pseudonym

To rename the site and gallery:

1. **config.json:**
   - Change `"title"` (shown in the header)
   - Change `"intro_line"` (shown below the title)

2. **HTML metadata** (for browser tab and social preview):
   - Edit `site/index.html`: change the `<title>` and Open Graph tags (`og:title`, `og:description`)
   - Edit `site/contact.html`: change the `<title>` and Open Graph tags

All other site content (layout, grid, styling) derives at build time and requires no manual edits.

## The Grade (frozen 2026-08-09)

Every photo is graded individually — there is no single fixed filter. The pipeline measures each photo (median luminance, warm-hue fraction, colorfulness) and computes its own parameters per photo:

- **Dark scenes** (caves, night): near-identity tone, gentle highlight glow, cool-hue cleanup — deliberate darkness is preserved (photos below a luminance floor are never lifted at all).
- **Mid-bright warm scenes** (facades, golden interiors): firm contrast (deep toe + midtone lift) with the *golden* treatment — warm-hue saturation and luminance raised together, hue-gated, self-limiting on already-vivid pixels.
- **Very bright scenes** (backlit skylights): strong luminous lift that keeps chroma, plus a narrow pink/magenta band boost for stained-glass tints.

The profile was fitted numerically against the owner's own hand-graded reference edits (per-pair tone-transfer and per-hue chroma measurement) and cross-checked against researched grading lookbooks: Kodak Gold's sat+luminance golden pairing, Portra's soft highlight shoulder, Classic Chrome's hue-gated restraint, Kinfolk/Cereal editorial-vs-viral saturation discipline, and current (2026) zero-grain premium direction. Deliberate exclusions: no grain, no fade/lifted blacks, no global saturation pushes, no teal-boost trends.

All knobs live in `config.json` (`look`, `exposure`, `finish`) — the freeze is a starting point, not a cage. Per-photo regime decisions are logged in `site/photos/.log.jsonl` (`"regime"` field).

## Overrides: Skip, Caption, Relift

The `overrides.json` file lets you customize individual photos without rebuilding. Schema:

```json
{
  "photo_id_1": { "skip": true },
  "photo_id_2": { "caption": "Custom caption here" },
  "photo_id_3": { "no_lift": true }
}
```

- **`skip`:** Exclude the photo from the gallery (even if it passes grading)
- **`caption`:** Replace the auto-generated caption
- **`no_lift`:** Keep the original exposure without auto-lifting (useful if auto-lift misjudged the mood)

Photo IDs are the filenames without extension (e.g., `DSC_1234` for `DSC_1234.JPG`).

## Build Logs

The build pipeline logs detailed results to `site/photos/.log.jsonl`, one JSON line per photo per run. Check this file to debug:

- Grading decisions (exposure, white balance, rotation)
- Failures (invalid EXIF, corrupted file, etc.)
- Warning details

Example:
```
{"photo_id": "DSC_1234", "status": "ok", "exposure_lift": 1.2, ...}
{"photo_id": "DSC_1235", "status": "error", "error": "invalid EXIF orientation tag"}
```

## Troubleshooting

**SYNC fails with "SYNC FAILED" screen:**
- Check `site/photos/.log.jsonl` for the last few lines — they show which photos errored and why.
- Common causes: corrupted EXIF, unsupported format, file permissions.

**Build aborts after processing photos:**
- If more than 25% of photos fail (configurable via `config.json` → `guards.max_fail_frac`), the publish is intentionally aborted to prevent a broken gallery deploy.
- Fix the failing photos or adjust the failure threshold in `config.json`.

**Git push fails in SYNC:**
- Ensure your GitHub remote is configured (see One-Time Setup, step 2).
- Check your SSH key or personal access token is set up for git authentication.

**Site doesn't update after push:**
- Cloudflare typically deploys within a minute. Check the **Pages** project in Cloudflare Dashboard for build status.
- If the build is stuck, trigger a manual redeploy from the Pages dashboard.
