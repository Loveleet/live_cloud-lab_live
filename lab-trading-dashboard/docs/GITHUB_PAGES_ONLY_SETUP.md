# Use GitHub Pages only (https://loveleet.github.io/lab_live/)

To have the app **only** at **https://loveleet.github.io/lab_live/** (and not use http://150.241.244.130:10000), the **API must be HTTPS**. Browsers block HTTPS pages from calling HTTP APIs (mixed content).

You need **one domain** for the API (e.g. `api.yourdomain.com` or `lab.yourdomain.com`) pointed at your server. Then follow the steps below.

---

## 1. Get a domain and point it to the server

- Buy a domain (e.g. from Namecheap, GoDaddy, Cloudflare, etc.) or use a subdomain you already have.
- In DNS, add an **A record**:
  - **Name:** e.g. `api` or `lab` (so you get `api.yourdomain.com` or `lab.yourdomain.com`)
  - **Value:** `150.241.244.130`
- Wait a few minutes, then check: `ping api.yourdomain.com` → should show `150.241.244.130`.

---

## 2. On the cloud server: nginx + HTTPS

SSH in: `ssh root@150.241.244.130`

```bash
# Install
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# Create config (replace api.yourdomain.com with YOUR domain)
sudo nano /etc/nginx/sites-available/lab-trading
```

Paste (change `server_name` to your domain):

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Save, then:

```bash
sudo ln -sf /etc/nginx/sites-available/lab-trading /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Get HTTPS certificate (replace with your domain)
sudo certbot --nginx -d api.yourdomain.com
```

Use your email, agree to terms, choose **Yes** to redirect HTTP→HTTPS.

---

## 3. CORS

The server already allows **https://loveleet.github.io**. No change needed for GitHub Pages. (If you later serve the app at your own domain too, add that origin in secrets: `ALLOWED_ORIGINS=https://yourdomain.com`.)

---

## 4. Point GitHub Pages at the HTTPS API

1. **GitHub** → your repo → **Settings** → **Secrets and variables** → **Actions**
2. Edit **API_BASE_URL** → set value to **`https://api.yourdomain.com`** (no trailing slash)
3. **Actions** → **Deploy frontend to GitHub Pages** → **Run workflow**

---

## 5. Test

Open **https://loveleet.github.io/lab_live/** and hard refresh (Ctrl+Shift+R). Login should work; the page will call `https://api.yourdomain.com` with no mixed content.

---

## Summary

| Step | What |
|------|------|
| 1 | Domain A record → `150.241.244.130` |
| 2 | On cloud: nginx + certbot → API at `https://api.yourdomain.com` |
| 3 | CORS: already allows GitHub Pages (no change needed) |
| 4 | GitHub: API_BASE_URL = `https://api.yourdomain.com`, run Deploy workflow |
| 5 | Use https://loveleet.github.io/lab_live/ |

Once this is done, you use **only** GitHub Pages; the API is reached over HTTPS from there.

---

## Optional: clubinfotech.com also opens the website

To have **https://clubinfotech.com** and **https://www.clubinfotech.com** serve the same dashboard (same app as GitHub Pages, but same-origin API):

### 1. DNS (at GoDaddy or your registrar)

- **A record** for `clubinfotech.com` → `150.241.244.130`
- **A record** for `www` (or CNAME `www` → `clubinfotech.com`) → `150.241.244.130`

Check: `ping clubinfotech.com` and `ping www.clubinfotech.com` → both show `150.241.244.130`.

### 2. Nginx on the cloud server

Add a server block for the main domain (or use the full `docs/nginx-lab-trading.conf` which includes both API and main site):

```nginx
server {
    listen 80;
    server_name clubinfotech.com www.clubinfotech.com;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d clubinfotech.com -d www.clubinfotech.com
```

Choose redirect HTTP→HTTPS when asked.

### 3. Deploy

Redeploy the app to the cloud so the updated server (CORS) and frontend (same-origin for clubinfotech.com) are live. The frontend will use `/api` on the same host when opened from clubinfotech.com.

### 4. Test

Open **https://clubinfotech.com** (or **https://www.clubinfotech.com**). You should see the same dashboard; login and data use the same server (same-origin, no CORS).
