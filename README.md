# Financial Calculators (self-updating Lotto tab)

Tenure Pay / Business / Lotto calculators. The Lotto tab's jackpot figures
refresh automatically via a scheduled GitHub Action — no manual edits needed.

## One-time setup

1. **Create a new repo on GitHub** (public or private both work), and upload
   every file in this folder, keeping the same structure:
   ```
   index.html
   data/jackpots.json
   scripts/update_jackpots.py
   .github/workflows/update-jackpots.yml
   ```

2. **Enable GitHub Pages**
   Repo → Settings → Pages → Source: "Deploy from a branch" → Branch: `main`,
   folder `/ (root)` → Save. GitHub gives you a URL like:
   `https://yourname.github.io/your-repo-name/`
   That link is permanent — it always shows whatever is currently committed.

3. **Allow the Action to commit updates**
   Repo → Settings → Actions → General → scroll to "Workflow permissions" →
   select **"Read and write permissions"** → Save.
   (Without this, the scheduled Action can fetch new numbers but can't push
   the update back to the repo.)

4. **Test it once manually**
   Repo → Actions tab → "Update Lottery Jackpots" → **Run workflow** button.
   Check the run's log: it should say it parsed both games and either
   committed a change or found no change. If it says a fetch or parse
   failed, see Troubleshooting below.

That's it — from here it runs on its own every 6 hours (editable in the
workflow file's cron line), and your Pages link always reflects the latest
committed numbers.

## How it works

- `scripts/update_jackpots.py` fetches public state-lottery pages (no CORS
  issue — this runs on GitHub's servers, not in a browser) and parses out
  the current jackpot + cash values with regex.
- It writes the result to `data/jackpots.json`.
- `index.html`'s own JavaScript fetches that JSON file on page load and
  fills in the Powerball/Mega Millions fields automatically. If the fetch
  fails for any reason, it silently falls back to the hardcoded values
  already baked into the page.
- The GitHub Action just runs that script on a timer and commits the file
  if it changed. GitHub Pages redeploys automatically on every commit.

## Troubleshooting

- **A run fails to parse a value:** lottery sites occasionally tweak their
  page wording, which can break the regex matching. Open the failed run's
  log to see which source URL and which value (jackpot vs. cash) it
  couldn't find, then adjust the `jackpot_words` / `cash_words` lists or
  add another source URL in `scripts/update_jackpots.py`.
- **Numbers not updating on the live page:** hard-refresh the page (the
  fetch uses `cache: 'no-store'`, so this is usually a browser/CDN cache
  issue, not a data issue) — or check the Action's last run actually
  committed a change.
- **Want faster updates on draw nights:** lower the `cron` interval in
  `.github/workflows/update-jackpots.yml` (e.g. every hour: `0 * * * *`).
  Cron times are UTC.
