# CCQS — Integration into ADFM-App-Folder

This document tells whoever is integrating CCQS into the `adfundmgmt/ADFM-App-Folder` multi-page Streamlit app exactly what to do.

CCQS is a daily-refresh chart-quality screener that scores ~860 stocks across ~148 thematic baskets. It runs its own GitHub Actions cron, writes its own cache parquets, and is deployable standalone at `app/streamlit_app.py`. This guide is for embedding it as a `pages/07_CCQS.py` tab inside the firm's analytics suite.

---

## Architecture decision

Two valid integration patterns. Pick one:

### Pattern A — Git submodule (recommended for most cases)

Add CCQS as a submodule under `ADFM-App-Folder/external/ccqs/`. The submodule pin tracks a specific commit; you bump it when you want CCQS updates.

**Pros:** clean separation of concerns; CCQS continues to receive cache commits from its own cron with no impact on ADFM's CI; the bump-the-pin model gives you predictable rollouts.

**Cons:** Streamlit Cloud needs `git config --global submodule.recurse true` or an explicit `git submodule update --init --recursive` step. Streamlit Cloud does this automatically when the `.gitmodules` file is present, but verify.

### Pattern B — Vendored copy

Copy CCQS's `app/`, `compute/`, `data/universe.py`, `data/manual_overrides.yaml`, and `data/cache/dashboard/*.parquet` into `ADFM-App-Folder/external/ccqs/`. No submodule.

**Pros:** no submodule semantics; everything ships with one git history.

**Cons:** code drift — you have to manually re-copy from CCQS when methodology changes. Daily cache parquets are >20 MB and bloat the ADFM repo's history.

→ **Use Pattern A unless you have a specific reason not to.**

---

## Pattern A — Step-by-step

### Step 1. Add the submodule

From the `ADFM-App-Folder` root:

```bash
git submodule add https://github.com/adfundmgmt/Composite-Chart-Quality-Score.git external/ccqs
git submodule update --init --recursive
git add .gitmodules external/ccqs
git commit -m "feat: add CCQS as submodule under external/ccqs"
```

This pins CCQS at its current HEAD commit. When you want to pull the latest CCQS commits later, run:

```bash
cd external/ccqs && git pull origin main && cd ../..
git add external/ccqs
git commit -m "chore: bump CCQS submodule to latest"
```

### Step 2. Create the wrapper page

Create `ADFM-App-Folder/pages/07_CCQS.py` with this content:

```python
"""CCQS — Composite Chart Quality Score.

Daily technical screening tool. Scores ~860 stocks across ~148 thematic
baskets. Cron-refreshed every weekday at 4:05 PM ET.

Source repo: https://github.com/adfundmgmt/Composite-Chart-Quality-Score
"""

import sys
from pathlib import Path

# Make the CCQS submodule importable.
_CCQS_ROOT = Path(__file__).resolve().parents[1] / "external" / "ccqs"
if str(_CCQS_ROOT) not in sys.path:
    sys.path.insert(0, str(_CCQS_ROOT))

# Import and render. The function re-executes the CCQS standalone script
# in the current Streamlit context so every top-level statement (data
# loading, sidebar widgets, tables, stock detail, footer) runs fresh.
from app.streamlit_app_entry import render_ccqs_page

render_ccqs_page()
```

The `07_` prefix controls sidebar ordering — adjust the number to slot CCQS where you want it in the page list.

### Step 3. Merge requirements

CCQS pins dependencies in `external/ccqs/requirements.txt`. Either:

**Option 3a (simplest):** append CCQS's requirements to ADFM's `requirements.txt`. Conflicts (different version pins of pandas, numpy, etc.) — keep the higher version, or whichever ADFM already uses if it satisfies CCQS's minimum.

**Option 3b (cleaner):** add a single `-r external/ccqs/requirements.txt` line to ADFM's `requirements.txt`. pip resolves the union.

```bash
# In ADFM-App-Folder/requirements.txt, append:
-r external/ccqs/requirements.txt
```

Streamlit Cloud will install both sets on next deploy.

### Step 4. Python version

CCQS requires **Python 3.13** (specifically 3.13.0+ — uses PEP 695 union syntax in some modules). Check `ADFM-App-Folder/runtime.txt` or `.python-version`. If it pins anything lower, bump to 3.13.

### Step 5. Commit and push

```bash
git add pages/07_CCQS.py requirements.txt
git commit -m "feat: embed CCQS as /CCQS page in ADFM suite"
git push origin main
```

Streamlit Cloud auto-redeploys on push. First build with the new dependencies takes 5–10 min. Subsequent rebuilds are 1–2 min.

### Step 6. Verify

Navigate to `https://adfundmgmt.streamlit.app/CCQS` and confirm:

- [ ] Page header shows today's date
- [ ] Themes table contains "Magnificent Seven"
- [ ] Clicking AAPL in Stock Detail shows THEME = "Magnificent Seven"
- [ ] Sidebar filters (Leadership Tier, State) populate
- [ ] System Health & Methodology section at the bottom expands
- [ ] Footer shows "© 2026 AD Fund Management LP"

If any of those look broken, capture a screenshot and ping the maintainer.

---

## Operational details to know

### Daily cron

CCQS has its own GitHub Actions cron at `adfundmgmt/Composite-Chart-Quality-Score/.github/workflows/pipeline.yml`. It runs at **4:05 PM ET Mon-Fri** (5 min after NYSE close), regenerates the cache, and commits to the CCQS repo's main.

After the cron commits, the new cache becomes available in `external/ccqs/data/cache/dashboard/*.parquet` only after you bump the submodule pin in ADFM-App-Folder. Without a pin bump, the ADFM-embedded CCQS will show stale data.

**Recommendation:** add a second cron on the ADFM-App-Folder repo that runs at 4:15 PM ET weekdays and does the submodule bump + push automatically. Sample workflow:

```yaml
# .github/workflows/bump-ccqs-submodule.yml
name: Bump CCQS submodule
on:
  schedule:
    - cron: '15 20 * * 1-5'  # 4:15 PM ET (EDT)
    - cron: '15 21 * * 1-5'  # 4:15 PM ET (EST)
  workflow_dispatch: {}
permissions:
  contents: write
jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
          token: ${{ secrets.GITHUB_TOKEN }}
      - name: Update CCQS submodule
        run: |
          cd external/ccqs
          git fetch origin main
          git checkout origin/main
          cd ../..
      - name: Commit if changed
        run: |
          if [[ -n "$(git status --porcelain)" ]]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add external/ccqs
            git commit -m "chore: bump CCQS submodule to latest"
            git push
          fi
```

This makes the ADFM-embedded dashboard auto-refresh every weekday ~10 min after the CCQS cron runs.

### Hard-gate tests

CCQS has 91 pytest tests, 140 TradingView reference-parity field checks, and 11 pipeline sanity checks. All run on every commit via CCQS's own CI. **ADFM does not need to re-run these.** The submodule pin guarantees you only embed code that already passed the gates upstream.

### Methodology lock

CCQS has a "Methodology Lock §3" invariant: any change to `STATE_WEIGHTS`, `FEATURE_ORDER`, or `COMPONENT_COLS` must preserve 140/140 TV parity. The CCQS CI enforces this. Don't fork the methodology in ADFM — if you want a variant, do it on a branch in the CCQS repo and bump the submodule to that branch.

### Data path resolution

CCQS's `app/utils/data_loader.py` resolves the cache directory via `Path(__file__).resolve().parents[2] / "data" / "cache"`. This works correctly when CCQS is at `external/ccqs/` because the `parents[2]` calculation walks up from `app/utils/data_loader.py` to the CCQS repo root, finding `data/cache/dashboard/` reliably. No env-var override needed.

### Streamlit caching

CCQS's display layer uses `@st.cache_data(ttl=1800)` (30-min TTL). This is independent of ADFM's own cache decorators — they don't conflict. If you ever need to force-flush CCQS's cache from the UI, the only documented way is a Streamlit Cloud **Reboot** of the ADFM app.

---

## TL;DR for the boss

1. `git submodule add https://github.com/adfundmgmt/Composite-Chart-Quality-Score.git external/ccqs`
2. Create `pages/07_CCQS.py` (10-line wrapper, content above)
3. Append `-r external/ccqs/requirements.txt` to `requirements.txt`
4. Make sure Python 3.13 is the deploy target
5. Commit + push — Streamlit Cloud auto-redeploys
6. Optional: add the submodule-bump cron (sample above) so it stays current

Total active work: ~15 minutes plus the build wait.
