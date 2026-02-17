# Theme profiles (Anish, Loveleet, custom) and debug

Theme profiles let you save UI settings **per profile on the server** so the same view (theme, font size, layout, etc.) follows you across devices when you’re logged in.

---

## What’s implemented

- **Backend**
  - `theme_profiles` table: one row per (user, profile name). Default profiles **Anish** and **Loveleet** are created when you first open the app while logged in.
  - `ui_settings` table: now has `theme_profile_id`. Settings are stored per (user, theme profile).
  - APIs: `GET/POST /api/theme-profiles`, `GET/POST /api/active-theme-profile`, `GET/POST /api/ui-settings` (scoped by active profile when logged in).
  - **Debug:** `GET /api/debug-theme-settings` (auth required) returns `user_id`, `active_theme_profile_name`, and recent settings keys.

- **Frontend**
  - **View** dropdown in the header (when logged in): select **Anish**, **Loveleet**, or create a **+ New** profile.
  - Theme (dark/light), font size, and layout are saved to the server for the **active profile** when you change them.
  - On load (or when you switch profile), the app loads settings from the server for that profile and applies them.
  - **Check** link next to the View selector: calls `/api/debug-theme-settings` and logs the result in the console.

---

## How to verify it’s working

1. **Log in** to the dashboard.

2. **Confirm profiles**
   - In the header you should see **View:** with a dropdown (e.g. Anish, Loveleet).
   - Open DevTools → **Console**. You should see `[Theme] profiles loaded 2 ...` and `[Theme] active profile Anish id=...` (or Loveleet).

3. **Change and save**
   - Change **theme** (dark/light), **font size**, or **layout**.
   - In Console you should see `[Theme] saveSetting theme profile= Anish` (or the active profile name).
   - In **Network** tab, filter by “ui-settings” or “theme”; you should see `POST /api/ui-settings` with body containing `theme_profile_id` and the key you changed.

4. **Debug endpoint**
   - Click the **Check** link next to the View selector, or open in a new tab (while logged in):  
     `https://api.clubinfotech.com/api/debug-theme-settings`
   - You should get JSON like:
     ```json
     {
       "debug": true,
       "user_id": "...",
       "active_theme_profile_id": 1,
       "active_theme_profile_name": "Anish",
       "recent_settings_count": 3,
       "recent_settings": [{"key": "theme", "updated_at": "..."}, ...]
     }
     ```

5. **Switch profile**
   - Select **Loveleet** in the View dropdown.
   - Console: `[Theme] set active profile Loveleet id=...` and `[Theme] apply server settings to app ... keys`.
   - Change theme/font again; it should save under **Loveleet**. Switch back to **Anish** and confirm the previous Anish settings are restored.

6. **Server logs (optional)**
   - On the server: `journalctl -u lab-trading-dashboard -n 50 --no-pager | grep -E 'theme_profiles|ui_settings|active-theme'`
   - You should see lines like `[theme_profiles] GET user_id= ... profiles= 2` and `[ui_settings] POST ... theme_profile_id= 1`.

---

## DB (optional)

If you run the SQL by hand (e.g. to inspect data):

```bash
# On the cloud (or wherever your DB is)
psql -U lab -d olab -c "SELECT id, user_id, name FROM theme_profiles ORDER BY user_id, id;"
psql -U lab -d olab -c "SELECT user_id, theme_profile_id, key, updated_at FROM ui_settings WHERE key != '_active_theme_profile_id' ORDER BY updated_at DESC LIMIT 20;"
```

---

## Deploy

- **server.js** is not in Git. After pulling backend changes, copy and restart:
  ```bash
  scp server/server.js root@150.241.244.130:/root/lab-trading-dashboard/server/
  ssh root@150.241.244.130 "sudo systemctl restart lab-trading-dashboard"
  ```
- Frontend: push and deploy as usual (e.g. GitHub Pages). No DB migration is required; the server creates `theme_profiles` and adds `theme_profile_id` to `ui_settings` on first use.
