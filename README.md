# Discrimination Map (dxmap) — far-right incident monitor (Germany)

A live map that documents far-right incidents in Germany. A monitoring agent
scans free public sources for leads; anyone can also file a report by hand.
Every mark on the map carries **what happened, the evidence, the
possibly-applicable German statute, and the impact** — see `PLAN.md` for the
full design and honesty notes about what's automated vs. what's stubbed.

**Read this first:** automated marks are *unverified leads*, not accusations.
See "How this stays fair and lawful" below before you deploy this publicly.

## 1. Run it locally

```bash
cd dxmap
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8020
```

Open http://127.0.0.1:8020/. Run the tests any time with:

```bash
python -m pytest -q tests
```

## 2. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DXMAP_DB_PATH` | `backend/dxmap.db` | SQLite file location |
| `DXMAP_HEARTBEAT_SECONDS` | `180` | Seconds between agent scans |
| `DXMAP_SELFCHECK_SECONDS` | `900` | Seconds between self-checks |
| `DXMAP_ALLOW_ORIGINS` | `*` | CORS allow-list (set to your domain in prod) |
| `DXMAP_ENV` | `dev` | Set to `prod` on the VPS |
| `DXMAP_GEO_COUNTRY` | `de` | Nominatim country restriction |
| `DXMAP_TERMS` | (German far-right terms) | Bluesky/YouTube search terms |
| `DXMAP_MASTODON_INSTANCES` | `mastodon.social,norden.social,nrw.social` | Instances to poll |
| `DXMAP_MASTODON_TAGS` | `Rechtsextremismus,Naziaufmarsch,...` | Hashtags to poll |
| `YOUTUBE_API_KEY` | *(unset)* | Free key to activate the YouTube source |

Bluesky and Mastodon work with **zero configuration** — they're free, keyless,
and confirmed working from a datacenter IP (i.e. your VPS). YouTube activates
the moment you add a free `YOUTUBE_API_KEY`. Reddit's anonymous `.json`
endpoints are blocked on cloud/datacenter IPs as of this build, so Reddit is
not wired in as a default source — see `PLAN.md` for the honest rundown.

## 3. Deploy to your Hostinger VPS

```bash
# From your local machine:
scp -r dxmap root@YOUR_VPS_IP:/opt/

# Then, on the VPS:
ssh root@YOUR_VPS_IP
bash /opt/dxmap/deploy/deploy.sh yourdomain.com
```

That installs Python + Nginx, creates an unprivileged `dxmap` service user,
sets up a virtualenv, installs the systemd service, configures Nginx, and
(if you gave a real domain with DNS already pointed at the VPS) provisions a
free Let's Encrypt certificate.

No domain yet? Run `bash deploy/deploy.sh` with no argument — it deploys on
plain HTTP so you can test, then re-run with a domain later to add TLS.

For the specific `dxmap.nabilvs.com` deployment (SSH key, Cloudflare DNS,
coexisting with tahiafilms.com/marawan on the same VPS), see
`deploy/DEPLOY-DXMAP.md` instead of the generic steps above.

**Useful commands after deploying:**

```bash
systemctl status dxmap        # is it running?
journalctl -u dxmap -f        # live logs
cat /opt/dxmap/backend/improvements.log   # self-check findings
```

To activate YouTube later, edit `/opt/dxmap/.env`, uncomment
`YOUTUBE_API_KEY=...`, then `systemctl restart dxmap`.

## 4. How this stays fair and lawful

- **Leads, not verdicts.** Every automatically-scraped mark is stored with
  `status = unverified_lead`. The classifier (`backend/lawref.py`) only
  suggests statutes that *might* apply to the plain text of a public post —
  it never asserts guilt. Presumption of innocence applies throughout.
- **Incidents, not people.** The tool documents events and already-public
  reporting. It is not a database of private individuals, and it must not
  become one — don't extend it to store names, faces, or addresses of
  private citizens without a clear legal and safety review.
- **Human review matters.** Before treating any mark as "confirmed," check
  the evidence link yourself. Consider adding a moderation step (see
  `PLAN.md` → "explicitly out of scope") before letting the public submit
  reports on a live, publicly-linked deployment.
- **Report actual crimes to the police (110 in Germany)** — this tool is a
  documentation aid, not an emergency channel.

## 5. Project layout

```
dxmap/
├── PLAN.md                  # architecture, source status, legal framework
├── README.md                 # this file
├── backend/
│   ├── app.py                 # FastAPI app + endpoints
│   ├── agent.py                # the scraping agent (heartbeat loop)
│   ├── selfcheck.py            # tester + security audit + health + suggestions
│   ├── lawref.py                # statute reference + text classifier
│   ├── geolocate.py             # gazetteer + Nominatim, Germany-restricted
│   ├── db.py                    # SQLite persistence
│   └── requirements.txt
├── frontend/
│   └── index.html             # the map UI (single file, no build step)
├── tests/
│   └── test_api.py            # pytest suite (self-check runs this)
└── deploy/
    ├── dxmap.service            # systemd unit
    ├── nginx.conf                # reverse proxy + TLS
    ├── deploy.sh                  # one-command VPS setup
    └── DEPLOY-DXMAP.md             # dxmap.nabilvs.com-specific runbook
```

For ongoing development workflow (SSH from mobile/tablet + using Claude Code
to keep enhancing this project), see `DEVELOPMENT-WORKFLOW.md`.
