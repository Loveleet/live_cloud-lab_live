# Fix "404 - There isn't a GitHub Pages site here"

The workflow now deploys to the **gh-pages** branch (no "github-pages" environment needed). After the first successful run, set **Settings → Pages** → Source: **Deploy from a branch** → Branch: **gh-pages**, Folder: **/ (root)**. Then open https://loveleet.github.io/lab_live/

---

## 1. Push the workflow (if it’s only on your machine)

The workflow file must be in the repo on GitHub:

- **Path:** `.github/workflows/deploy-frontend-pages.yml`
- Commit and push the branch that has this file (e.g. `lab_live` or `main`):

```bash
git add .github/workflows/deploy-frontend-pages.yml
git commit -m "Add GitHub Pages deploy workflow"
git push origin lab_live
```

(or `git push origin main` if that’s your branch)

---

## 2. Run the workflow

**Option A – Push to trigger**

- Push to `main` or `lab_live` (the branches in the workflow). That triggers **Deploy frontend to GitHub Pages**.

**Option B – Run manually**

1. On GitHub: **Actions** tab.
2. In the left sidebar, click **Deploy frontend to GitHub Pages**.
3. Click **Run workflow**, choose the branch (e.g. `lab_live`), then **Run workflow**.

---

## 3. Check the run

1. **Actions** → click the latest run of **Deploy frontend to GitHub Pages**.
2. If it’s **green** → wait 1–2 minutes, then open:  
   **https://loveleet.github.io/lab_live/**
3. If it’s **red** → open the failed job and read the error.
   - **403 / "Permission denied to github-actions [bot]"**: Go to **Settings → Actions → General** → **Workflow permissions** → select **Read and write permissions** → Save. Then **Actions** → re-run the failed workflow.
   - Build errors: fix in repo and push again.

---

## 4. Summary

| Step | Action |
|------|--------|
| 1 | Push the workflow (and frontend code) to your branch (e.g. `lab_live`). |
| 2 | **Actions → Deploy frontend to GitHub Pages → Run workflow** (or push to trigger). |
| 3 | When the run is green: **Settings → Pages** → Source: **Deploy from a branch** → Branch: **gh-pages**, Folder: **/ (root)** → Save. |
| 4 | Open **https://loveleet.github.io/lab_live/**. |

---

## If "Deploy to GitHub Pages" step fails with 403

The workflow needs permission to push the `gh-pages` branch:

1. **Settings** → **Actions** → **General**.
2. Under **Workflow permissions**, choose **Read and write permissions**.
3. Click **Save**.
4. **Actions** → open the failed run → **Re-run all jobs**.
