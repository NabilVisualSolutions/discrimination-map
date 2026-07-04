# Hermes Map — far-right incident monitor (Germany)

A live map that documents far-right incidents in Germany. A background agent
("Hermes") scans free public sources for leads; anyone can also file a report
by hand. Every mark on the map carries **what happened, the evidence, the
possibly-applicable German statute, and the impact** — see `PLAN.md` for the
full design and honesty notes about what's automated vs. what's stubbed.

**Read this first:** automated marks are *unverified leads*, not accusations.
See "How this stays fair and lawful" below before you deploy this publicly.

## 1. Run it locally

```bash
cd hermes-map
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/. Run the tests any time with:

```bash
python -m pytest -q tests
```

## 2. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_DB_PATH` | `backend/hermes.db` | SQLite file location |
| `HERMES_HEARTBEAT_SECONDS` | `180` | Seconds between agent scans |
| `HERMES_SELFCHECK_SECONDS` | `900` | Seconds between self-checks |
| `HERMES_ALLOW_ORIGINS` | `*` | CORS allow-list (set to your domain in prod) |
| `HERMES_ENV` | `dev` | Set to `prod` on the VPS |
| `HERMES_GEO_COUNTRY` | `de` | Nominatim country restriction |
| `HERMES_TERMS` | (German far-right terms) | Bluesky/YouTube search terms |
| `HERMES_MASTODON_INSTANCES` | `mastodon.social,norden.social,nrw.social` | Instances to poll |
| `HERMES_MASTODON_TAGS` | `Rechtsextremismus,Naziaufmarsch,...` | Hashtags to poll |
| `YOUTUBE_API_KEY` | *(unset)* | Free key to activate the YouTube source |

Bluesky and Mastodon work with **zero configuration** — they're free, keyless,
and confirmed working from a datacenter IP (i.e. your VPS). YouTube activates
the moment you add a free `YOUTUBE_API_KEY`. Reddit's anonymous `.json`
endpoints are blocked on cloud/datacenter IPs as of this build, so Reddit is
not wired in as a default source — see `PLAN.md` for the honest rundown.

## 3. Deploy to your Hostinger VPS

```bash
# From your local machine:
scp -r hermes-map root@YOUR_VPS_IP:/opt/

# Then, on the VPS:
ssh root@YOUR_VPS_IP
bash /opt/hermes-map/deploy/deploy.sh yourdomain.com
```

That installs Python + Nginx, creates an unprivileged `hermes` service user,
sets up a virtualenv, installs the systemd service, configures Nginx, and
(if you gave a real domain with DNS already pointed at the VPS) provisions a
free Let's Encrypt certificate.

No domain yet? Run `bash deploy/deploy.sh` with no argument — it deploys on
plain HTTP so you can test, then re-run with a domain later to add TLS.

**Useful commands after deploying:**

```bash
systemctl status hermes        # is it running?
journalctl -u hermes -f        # live logs
cat /opt/hermes-map/backend/improvements.log   # self-check findings
```

To activate YouTube later, edit `/opt/hermes-map/.env`, uncomment
`YOUTUBE_API_KEY=...`, then `systemctl restart hermes`.

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
hermes-map/
├── PLAN.md                  # architecture, source status, legal framework
├── README.md                 # this file
├── backend/
│   ├── app.py                 # FastAPI app + endpoints
│   ├── hermes.py               # the scraping agent (heartbeat loop)
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
    ├── hermes.service           # systemd unit
    ├── nginx.conf                # reverse proxy + TLS
    └── deploy.sh                  # one-command VPS setup
```

For ongoing development workflow (SSH from mobile/tablet + using Claude Code
to keep enhancing this project), see `DEVELOPMENT-WORKFLOW.md`.
