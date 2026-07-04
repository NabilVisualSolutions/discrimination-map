# Development Workflow: Mobile Access + Claude Code

How to (1) reach your VPS and your dev machine ("dragon") from your phone and
tablet, and (2) use Claude Code to keep enhancing Hermes Map on a regular
schedule, safely.

**The core recommendation, up front:** develop on **dragon** (your computer),
not on the production VPS. Use Claude Code with git there, review its
changes, then deploy the reviewed result to the VPS. Don't point an
autonomous coding agent directly at your live, public-facing server — that's
the same "review before it ships" principle this project's own self-check
loop follows (see `PLAN.md` §4). The VPS should mostly just run `git pull` +
restart the service.

---

## 1. SSH access from your phone and tablet

You have two different things you might want to reach remotely, and they
need different tools:

| You want to... | Use |
|---|---|
| Run shell commands on the **VPS** (check logs, restart the service, quick edits) | A regular **SSH client app** |
| Continue an active **Claude Code coding session on dragon** from your phone | Claude Code's **Remote Control** feature (§3) — better fit than raw SSH for this |

This section covers plain SSH; §3 covers Remote Control.

### 1.1 Generate a dedicated key per device

Don't copy one private key onto every device. Generate a separate keypair
per device so you can revoke one without breaking the others.

**On dragon**, for each device you want to grant access from:

```bash
ssh-keygen -t ed25519 -C "phone" -f ~/.ssh/hermes_vps_phone
ssh-keygen -t ed25519 -C "tablet" -f ~/.ssh/hermes_vps_tablet
```

This produces `hermes_vps_phone` (private, stays on your phone only) and
`hermes_vps_phone.pub` (public, goes on the VPS). Copy each public key to the
VPS:

```bash
ssh-copy-id -i ~/.ssh/hermes_vps_phone.pub root@YOUR_VPS_IP
ssh-copy-id -i ~/.ssh/hermes_vps_tablet.pub root@YOUR_VPS_IP
```

Then transfer the matching **private** key to each device (e.g. AirDrop,
a cable, or a password manager's secure notes — never email or chat it) and
import it into the SSH app below. Once both keys work, harden the VPS:

```bash
# On the VPS: disable password login, keep only key-based auth
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

### 1.2 SSH client apps

Recommendations as of mid-2026 — check current pricing/availability before
installing, since app stores change:

- **iPhone/iPad:** **Blink Shell** (one-time purchase, excellent terminal,
  supports Mosh so a dropped WiFi-to-cellular handoff doesn't kill your
  session — genuinely useful on a tablet on the move) or **Termius** if you
  want the same app/sync on desktop too (subscription for sync/SFTP).
- **Android:** **ConnectBot** (free, open source, no subscription) or
  **Termius** for cross-platform sync.

Setup in any of these is the same shape: add a new host (VPS IP or domain),
set the username, import the device's private key file instead of a
password, and connect.

### 1.3 SSH into "dragon" itself (optional)

If dragon is usually on your home network, you can also SSH into it directly
(e.g. to grab a file or start Claude Code remotely), but home networks
usually sit behind NAT without a public IP. The practical options:
- **Tailscale** or **ZeroTier** (free tiers): install on dragon and on your
  phone/tablet; they create a private mesh network so you can SSH to
  `dragon` by its Tailscale hostname from anywhere, no port forwarding or
  public IP needed. This is the option most people should use.
- Port-forwarding SSH on your home router works but exposes a port to the
  internet — only do this with key-only auth and ideally fail2ban installed.

---

## 2. Install Claude Code on dragon

```bash
# macOS / Linux / WSL
curl -fsSL https://claude.ai/install.sh | bash

# Windows PowerShell
irm https://claude.ai/install.ps1 | iex
```

No Node.js required with this native installer. Verify, then log in:

```bash
claude --version
claude doctor      # confirms install + auth health
```

Running `claude` for the first time opens a browser to sign in. Claude Code
needs a Pro, Max, Team, Enterprise, or Console account — the free Claude.ai
plan doesn't include it.

### Point it at this project

```bash
cd /path/to/hermes-map
claude
```

Inside the session, run `/init` once. It scans the repo and writes a starter
`CLAUDE.md` — build/test commands, structure, conventions — that loads
automatically into every future session, so you don't have to re-explain the
project each time. Given what's already in `PLAN.md` and `README.md`, it
should pick up most of the context on its own; skim the generated file and
add anything it missed (e.g. the "leads, not verdicts" rule from §4 of the
README — worth pinning explicitly so it's never accidentally weakened by a
future change).

---

## 3. Remote Control: use Claude Code from your phone/tablet

This is Anthropic's built-in bridge between a Claude Code session running on
dragon and the Claude app on your phone or tablet. It's a sync layer, not a
cloud migration: the session keeps executing on dragon the whole time (full
access to this repo, your git setup, everything on disk); your phone is just
a window into it. Availability depends on your plan (currently rolling out;
check the Claude app if you don't see it yet).

**Start a remote session on dragon:**

```bash
cd /path/to/hermes-map
claude --remote-control
```

This prints a session URL and (on macOS, press spacebar) a QR code.

**Connect from your phone or tablet:**
1. Open the Claude app → **Code** tab.
2. Find the session in the list (or scan the QR code), and tap in.
3. You now see the same conversation and can send prompts from the couch,
   the train, wherever — Claude Code keeps running and editing files on
   dragon in real time.

Two things worth knowing:
- Closing the terminal or putting dragon to sleep ends the session — it
  needs to stay running and awake.
- Approve tool actions as they come up, same as any interactive session;
  Remote Control doesn't change what Claude is allowed to do, just where you
  watch it from.

If you don't have the Claude app yet, run `/mobile` inside a Claude Code
session for a download QR code.

---

## 4. A sustainable enhancement cadence

Two tiers, from safest to most automated. Start with the first; only add the
second for narrow, well-scoped, reviewed tasks.

### Tier 1 (recommended): a regular interactive session, human-reviewed

Pick a cadence — weekly works well for a side project. Each session:

```bash
cd /path/to/hermes-map
git pull                                   # if you also edit from elsewhere
cat backend/improvements.log | tail -50    # see what self-check flagged
claude
```

Ask Claude Code to work through what the self-check log surfaced (a low
mapped ratio, a slow source, a new statute you want covered), or hand it a
feature. Review the diff, run `python -m pytest -q tests`, commit:

```bash
git add -A
git commit -m "Describe what changed and why"
git push          # if you have a remote — see §5
```

Then deploy the reviewed change (see §5).

### Tier 2 (optional): headless mode for narrow, bounded tasks

Claude Code can run non-interactively with `-p`, which is genuinely useful
for a recurring, scoped check — but keep it tightly bounded, and run it on
**dragon**, not the VPS:

```bash
claude -p "Run the test suite. If anything fails, describe the failure in
one paragraph and append it to backend/improvements.log. Do not modify any
other files." \
  --allowedTools "Bash(python -m pytest*)" "Read" "Write(backend/improvements.log)" \
  --max-turns 8 \
  --max-budget-usd 0.50
```

`--allowedTools` is what makes this safe: it's an allow-list, so the run
literally cannot touch git, the deploy scripts, or anything outside what you
named. `--max-turns` and `--max-budget-usd` are circuit breakers against a
runaway loop. Schedule it with cron on dragon if you want it fully hands-off:

```bash
# crontab -e  (on dragon)
0 9 * * 1 cd /path/to/hermes-map && claude -p "..." --allowedTools "Read" "Bash(python -m pytest*)" --max-turns 8 --max-budget-usd 0.50 >> /tmp/hermes-weekly-check.log 2>&1
```

**Don't** run headless Claude Code with broad tool access directly against
the VPS, and don't use `--dangerously-skip-permissions` on anything that can
reach production. If you want an agent to open pull requests instead of
editing files directly, that's a further step up in safety — worth doing
before you give any automation write access to a public-facing app.

---

## 5. Getting changes from dragon onto the VPS

The cleanest path is a git remote in between, so the VPS never runs
unreviewed code:

```bash
# One-time: create an empty private repo (GitHub, GitLab, or self-hosted),
# then on dragon:
cd /path/to/hermes-map
git remote add origin git@github.com:you/hermes-map.git
git push -u origin main
```

**On the VPS**, instead of re-copying files with `scp` every time, clone
once and pull thereafter:

```bash
# First time (replaces the scp step from README.md §3):
git clone git@github.com:you/hermes-map.git /opt/hermes-map
bash /opt/hermes-map/deploy/deploy.sh yourdomain.com

# Every deploy after that:
cd /opt/hermes-map
git pull
sudo systemctl restart hermes
```

No GitHub/GitLab account? Skip the middle step and go back to `scp -r` from
README.md — just make sure you only `scp` a version you've already reviewed
and tested on dragon, never a directory an unattended headless run just
finished touching.

---

## 6. Quick reference

| Task | Where | How |
|---|---|---|
| Check on the VPS from your phone | Phone | SSH app (Blink Shell / Termius / ConnectBot) |
| Reach dragon from your phone (no public IP) | Phone | Tailscale/ZeroTier, then SSH normally |
| Keep developing from your phone | Phone + dragon | Claude Code Remote Control |
| Weekly feature work / fixes | Dragon | Interactive `claude` session, then git push |
| Narrow recurring check (e.g. "did tests break?") | Dragon (cron) | `claude -p` with `--allowedTools` + budget caps |
| Ship a reviewed change | VPS | `git pull && systemctl restart hermes` |
