# Frontend on GitHub, Backend + Secrets on Cloud

This setup gives you:

- **Frontend** → Built and deployed by **GitHub** (GitHub Pages) on every push to `main`. No manual upload.
- **Backend + secrets** → Stay only on the **cloud** (150.241.244.130). Server code and `/etc/lab-trading-dashboard.env` are on the cloud; GitHub never has your secrets.

---

## Flow

```
Push to main (GitHub)
       │
       ▼
┌──────────────────────────────────┐
│  GitHub Actions                  │
│  Build frontend (Vite)           │
│  → API base = cloud URL          │
│  Deploy to GitHub Pages          │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  GitHub Pages                    │
│  https://<owner>.github.io/<repo>/│
│  (frontend only, no secrets)     │
└──────────────────────────────────┘
       │
       │  All /api/* requests
       ▼
┌──────────────────────────────────┐
│  Cloud server                    │
│  150.241.244.130:10000           │
│  Backend (Node) + secrets in      │
│  /etc/lab-trading-dashboard.env  │
└──────────────────────────────────┘
```

- You **push code** → only the **frontend** is built and published to GitHub Pages.
- The **cloud** runs the backend only (or backend + an optional copy of the frontend). Secrets (DB, FALLBACK_API_URL, etc.) live only in `/etc/lab-trading-dashboard.env` on the cloud.

---

## One-time setup

### 1. Enable GitHub Pages (after first workflow run)

1. Run the workflow once (push to `main`/`lab_live` or **Actions → Deploy frontend to GitHub Pages → Run workflow**).
2. On GitHub: **Repo → Settings → Pages**. Under **Build and deployment**, set **Source** to **Deploy from a branch**, Branch: **gh-pages**, Folder: **/ (root)**. Save.

### 2. (Optional) Set your API URL

If your backend is not at `http://150.241.244.130:10000`, add a repo secret:

- **Settings → Secrets and variables → Actions → New repository secret**
- Name: `API_BASE_URL`
- Value: your backend URL (e.g. `http://150.241.244.130:10000`)

The workflow uses this when building the frontend so it calls your cloud API.

### 3. Cloud backend CORS

The cloud server already allows:

- `https://loveleet.github.io` (GitHub Pages)
- `https://lab-live.vercel.app`

If your GitHub username or Pages URL is different, add the origin on the **cloud** in `/etc/lab-trading-dashboard.env`:

```bash
ALLOWED_ORIGINS=https://yourusername.github.io
```

Then restart:

```bash
sudo systemctl restart lab-trading-dashboard
```

---

## What runs where

| What              | Where                    | Updated when                    |
|-------------------|--------------------------|---------------------------------|
| Frontend (React)  | GitHub Pages             | Every push to `main`            |
| Backend (Node)    | Cloud 150.241.244.130    | Only when you deploy to cloud   |
| Secrets (env)     | Cloud only               | Only when you edit on the server|

---

## URLs

- **Use the app (recommended):**  
  `https://<your-github-username>.github.io/<repo-name>/`  
  Example: `https://loveleet.github.io/lab_live/`

- **Backend API only:**  
  `http://150.241.244.130:10000`  
  (Frontend on GitHub Pages calls this automatically.)

---

## Updating the backend on the cloud

When you change **server** code (e.g. `server.example.js`), push to GitHub as usual, then **on the cloud** either:

- Run your existing deploy script (e.g. from your machine), or  
- SSH to the cloud and run `git pull`, `cp server/server.example.js server/server.js`, `sudo systemctl restart lab-trading-dashboard`.

The **frontend** will already be updated by GitHub Pages on push; no need to “send” the frontend to the cloud for this flow.
