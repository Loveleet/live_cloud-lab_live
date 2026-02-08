# Add the workflow so the Actions tab works

If **Actions** always sends you to the "Get started" / new workflow page, the repo has no workflow file yet. Add this file **in the repo on GitHub** (or push it from your machine).

---

## Option A: Create the file on GitHub (no terminal)

1. Go to **https://github.com/Loveleet/lab_live**
2. Switch to your branch (e.g. **lab_live**) using the branch dropdown.
3. Click **Add file** → **Create new file**.
4. In the path/name box type exactly:  
   **`.github/workflows/deploy-frontend-pages.yml`**  
   (GitHub will create the `.github` and `workflows` folders.)
5. Paste the contents below into the file editor.
6. Scroll down, click **Commit changes** → **Commit directly to the branch** → **Commit changes**.

After that, open **Actions** again. You should see the workflow list and **"Deploy frontend to GitHub Pages"** in the left sidebar (no more redirect to the "new" page).

---

## File to paste (full content of deploy-frontend-pages.yml)

```yaml
# Deploy ONLY the frontend to GitHub Pages on push to the configured branch(es).
# Edit "branches" below to run for your branch (e.g. main, lab_live).

name: Deploy frontend to GitHub Pages

on:
  push:
    branches: [main, lab_live]
  workflow_dispatch:
    inputs:
      branch:
        description: 'Branch to build and deploy (e.g. main or lab_live)'
        required: true
        default: 'lab_live'

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  deploy-frontend:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.inputs.branch || github.ref_name }}

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - name: Install and build frontend
        env:
          VITE_API_BASE_URL: ${{ secrets.API_BASE_URL || 'http://150.241.244.130:10000' }}
          VITE_BASE_PATH: /${{ github.event.repository.name }}/
        run: |
          npm ci
          npm run build

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: dist

  deploy:
    needs: deploy-frontend
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment: github-pages
    steps:
      - name: Deploy to GitHub Pages
        id: deploy
        uses: actions/deploy-pages@v4
```

---

## Option B: Push from your machine

If this project folder is the same repo as Loveleet/lab_live:

```bash
cd "/Volumes/Loveleet /Work/Binance/lab_live/lab_live/lab-trading-dashboard"
git remote -v
```

If you see `origin` pointing to `.../Loveleet/lab_live.git` (or lab_live), then:

```bash
git add .github/workflows/deploy-frontend-pages.yml
git commit -m "Add Deploy frontend to GitHub Pages workflow"
git push origin lab_live
```

(Use your real branch name.) Then open **Actions** again.
