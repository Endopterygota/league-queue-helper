# League Queue Helper

A small Windows app with one Play button. It:

1. starts **Find Match** for your current League lobby;
2. waits for the ready check and accepts it;
3. stops and resets itself after accepting.

## Install with Git

Open PowerShell or Command Prompt and run:

```powershell
git clone https://github.com/Endopterygota/league-queue-helper.git
cd league-queue-helper
```

The helper uses only Python's standard library, so there are no packages to install.

## Run it

1. Install Python 3.10 or newer from <https://www.python.org/downloads/windows/>. During setup, enable **Add Python to PATH**.
2. Open League of Legends and sign in.
3. Create a lobby and choose the queue, role(s), and any other settings you want.
4. Double-click `run.bat`, then press **Play**.

You can also start it from the cloned folder with:

```powershell
python app.py
```

Use **Stop & Reset** to stop waiting. It does not cancel an already-running League queue; cancel that in the League client if needed.

## How it works

The helper talks only to the local League Client interface on `127.0.0.1`. It reads the temporary client lockfile to authenticate, and does not send the token or any account information elsewhere. No extra Python packages are required.

Riot does not publish this local interface as a stable public API, so a future League patch may change it. Use the helper only if it is permitted by Riot's current rules for your account and region.

### Custom installs

The app normally finds a running client automatically. If it cannot, set the `LEAGUE_LOCKFILE` environment variable to your League lockfile, for example:

```text
C:\Riot Games\League of Legends\lockfile
```
