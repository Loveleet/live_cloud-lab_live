# Action password (Auto-Pilot, Execute, End Trade, etc.)

The dashboard uses **two different passwords**:

| Purpose | Where it's stored | Used for |
|--------|--------------------|----------|
| **Login password** | `users.password_hash` (hashed) | Sign in to the dashboard |
| **Action password** | `lab_settings` table, key `action_password` | Auto-Pilot, Execute, End Trade, Hedge, Stop, +Inv, Clear |

The modal that appears when you click **Auto Enable**, **Execute**, etc. asks for the **action password**, not your login password. Even if you use the same string for both, you must **set the action password in the database** once.

---

## Set the action password on the cloud

1. SSH to the cloud server:
   ```bash
   ssh root@150.241.244.130
   ```

2. Connect to PostgreSQL (use the same database as your app, e.g. `olab` or `labdb2`). Check your app’s config or `/etc/lab-trading-dashboard.secrets.env` for `DB_NAME`:
   ```bash
   sudo -u postgres psql -d olab
   ```
   If your database name is different (e.g. `labdb2`), replace `olab` with that name.

3. Set the action password (replace `YourActionPassword` with the password you want to type in the Auto-Pilot/Execute modal):
   ```sql
   INSERT INTO lab_settings (key, value, updated_at)
   VALUES ('action_password', 'YourActionPassword', NOW())
   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
   ```

4. Exit psql:
   ```sql
   \q
   ```

After this, when the modal asks for the password, enter **exactly** the same string you put in `'YourActionPassword'` (e.g. if you want it to match your login password, use that same string in the SQL).

**Security:** The action password is stored in plain text in `lab_settings`. Use a strong password and restrict who can access the database.
