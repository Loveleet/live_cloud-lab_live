# Migrate to a new GitHub repo (same name: lab_live)

Use this when you want to **move the project to a new repository** (e.g. to leave secrets/credentials out of the old repo). The app will still use **GitHub Pages** for the frontend and your **cloud server** for the API.

---

## What makes the website use the cloud

| Piece | Where it's set | Purpose |
|--------|----------------|--------|
| **Frontend URL** | GitHub Pages: branch `gh-pages`, root | Site is `https://<username>.github.io/<repo_name>/` (e.g. `https://loveleet.github.io/lab_live/`) |
| **API URL** | GitHub repo → **Settings → Secrets and variables → Actions** → `API_BASE_URL` | Backend URL the frontend calls (e.g. `https://api.clubinfotech.com` or `http://YOUR_CLOUD_IP:10000`) |
| **Deploy workflow** | `.github/workflows/deploy-frontend-pages.yml` | On push (or manual run) it builds the app, writes `api-config.json` from `API_BASE_URL`, and deploys to the `gh-pages` branch |
| **Cloud CORS** | Cloud server `server.js` → `allowedOrigins` | Must include your Pages origin, e.g. `https://<username>.github.io` so the browser allows API calls |

So: **GitHub Pages** serves the UI; **Actions secret `API_BASE_URL`** points the UI to your cloud; **cloud `server.js`** must allow your Pages origin in CORS.

---

## Step-by-step: new repo with same name `lab_live`

### 1. Create the new repo on GitHub

1. **GitHub** → **Your profile** → **Repositories** → **New**.
2. **Repository name:** `lab_live` (same as now so the URL stays `https://<username>.github.io/lab_live/` if you keep the same account).
3. **Visibility:** Private or Public (Pages works for both).
4. **Do not** add a README, .gitignore, or license (you already have them).
5. Click **Create repository**.

If you use a **different GitHub account/org**, the Pages URL will be `https://<new-username>.github.io/lab_live/`. You’ll need to add that origin to the cloud server CORS (Step 7).

---

### 2. Clean the old repo from secrets (before copying)

On your **local clone of the current repo**:

- **Do not copy** any of these into the new repo (or remove them before first push):
  - `.env` (if it exists)
  - `lab-trading-dashboard/.env`
  - `server/server.js` (it’s gitignored; the new repo will use `server.example.js` and create `server.js` on the server)
  - Any file that contains real passwords, API keys, or your cloud IP/hostnames

- The **deploy workflow** (`.github/workflows/deploy-frontend-pages.yml`) uses only the **API_BASE_URL** secret and does not hardcode any cloud URL, so it is safe to copy into the new repo.

---

### 3. Push code to the new repo

From your local project root (e.g. `lab_live`):

```bash
# Add the new repo as a remote (replace NEW_USER with your GitHub username or org)
git remote add neworigin https://github.com/NEW_USER/lab_live.git

# Push your current branch (e.g. main or lab_live) to the new repo
git push -u neworigin main
# Or, if your default branch is lab_live:
# git push -u neworigin lab_live
```

If you want to push **all branches** (e.g. `lab_live` too):

```bash
git push neworigin --all
```

---

### 4. Turn on GitHub Pages for the new repo

1. In the **new repo** → **Settings** → **Pages**.
2. **Source:** “Deploy from a branch”.
3. **Branch:** `gh-pages` (the workflow will create it on first deploy).
4. **Folder:** `/ (root)`.
5. Save.

---

### 5. Set the API secret in the new repo

1. In the **new repo** → **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret**:
   - **Name:** `API_BASE_URL`
   - **Value:** Your backend URL, e.g. `https://api.clubinfotech.com` or `http://YOUR_CLOUD_IP:10000` (no trailing slash).

This is what makes the frontend call your cloud. Without it, the app builds but won’t load data.

---

### 6. Give Actions permission to write to the repo

1. In the **new repo** → **Settings** → **Actions** → **General**.
2. Under **Workflow permissions**, choose **Read and write permissions**.
3. Save.

---

### 7. Run the deploy workflow

1. In the **new repo** → **Actions** → **Deploy frontend to GitHub Pages**.
2. **Run workflow** (choose branch `main` or `lab_live` if needed).
3. Wait for the run to finish. It will create/update the `gh-pages` branch with the built app and `api-config.json`.

---

### 8. Cloud server CORS (if Pages URL changed)

Your cloud **server.js** must allow the **origin** of the Pages site in `allowedOrigins`.

- If you kept the **same GitHub user** and repo name: the origin is still `https://loveleet.github.io`. No change if it’s already there.
- If you use a **new GitHub user**: the origin is `https://<new-username>.github.io`. Add it on the cloud:

  1. On the cloud server, edit the file that defines `allowedOrigins` (e.g. `server.js` or the one generated from `server.example.js`).
  2. Add: `"https://<new-username>.github.io"`.
  3. Restart the Node service:  
     `sudo systemctl restart lab-trading-dashboard`

---

### 9. (Optional) Update in-app help links

The UI has links to the GitHub repo (e.g. Settings → Secrets, Deploy workflow). To point them to the new repo:

1. In the codebase, search for the old repo URL (e.g. `https://github.com/Loveleet/lab_live`).
2. Replace with the new repo URL (e.g. `https://github.com/NEW_USER/lab_live`).

Main place: `lab-trading-dashboard/src/App.jsx` (around the “API not configured” / “Set API_BASE_URL” message and links).

---

### 10. (Optional) Point deploy scripts at the new repo

If you use scripts that reference the repo URL (e.g. `.env.deploy` or `REPO_URL`), set:

- `REPO_URL=https://github.com/NEW_USER/lab_live.git`

Use the new repo URL wherever you deploy or clone from.

---

## Checklist

| Step | Done |
|------|------|
| 1. Create new repo `lab_live` on GitHub | |
| 2. Don’t copy `.env`, `server/server.js`, or any real secrets | |
| 3. Add new remote and push code to new repo | |
| 4. Settings → Pages → Deploy from branch `gh-pages` | |
| 5. Settings → Secrets → Actions → `API_BASE_URL` = cloud URL | |
| 6. Settings → Actions → General → Read and write permissions | |
| 7. Actions → Deploy frontend to GitHub Pages → Run workflow | |
| 8. If new GitHub user: add new origin to cloud CORS and restart Node | |
| 9. (Optional) Update repo links in App.jsx | |
| 10. (Optional) Update REPO_URL in deploy env | |

---

## After migration

- **Frontend:** `https://<username>.github.io/lab_live/`
- **API:** Whatever you set in `API_BASE_URL` (your cloud).
- **Old repo:** You can archive or delete it after you’re sure the new one works. If you delete it, any existing GitHub Pages for the old repo will stop serving.

If something doesn’t load (e.g. “No trade records”, or CORS errors), re-check: `API_BASE_URL` secret, cloud CORS origin, and that the cloud server is running (`systemctl status lab-trading-dashboard` and `journalctl -u lab-trading-dashboard -n 50`).
