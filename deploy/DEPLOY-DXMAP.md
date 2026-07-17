# Deploying to dxmap.nabilvs.com

Connects the live Germany/far-right build to a real subdomain of nabilvs.com,
on the same VPS that already runs tahiafilms.com and marawan. Do this from
**dragon** (or wherever you actually have a way to reach the VPS) — the SSH
config on the machine this doc was written on is a template with no real IP.

A dedicated deploy key was generated for this specifically (not reusing the
`vps`/`tahia`/`marawan` key), so a leak or revoke on this one doesn't touch
the others: `~/.ssh/id_ed25519_dxmap` (public key below). `~/.ssh/config` on
that machine already has a `Host dxmap-vps` block wired to it — you just need
to fill in the real `HostName`.

## 0. What you need before starting

- The VPS's IP address (same VPS `vps`/`tahia`/`marawan` already point at —
  check Hostinger's panel if you don't have it memorized).
- Working root SSH access to that VPS from *somewhere* (dragon, or the
  Hostinger browser console) to add the new key.
- Access to the Cloudflare dashboard for nabilvs.com (nameservers are already
  Cloudflare — confirmed via `dig NS nabilvs.com`).

## 1. Add the new key to the VPS

The public half (safe to paste anywhere):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFzpgw68sXrdGa201DNKuvnIyzX8uPtnTZ6D3ZffRJg2 nabil@dxmap-deploy-20260717
```

From a machine that already has working SSH access to the VPS:

```bash
ssh vps "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFzpgw68sXrdGa201DNKuvnIyzX8uPtnTZ6D3ZffRJg2 nabil@dxmap-deploy-20260717' >> ~/.ssh/authorized_keys"
```

(Or paste it into Hostinger's SSH Keys panel if it offers one, or open a
browser console session on the VPS and append it to `/root/.ssh/authorized_keys`
by hand — any of these work, you only need to do it once.)

## 2. Fill in the real IP

On whichever machine will run the deploy (dragon), edit `~/.ssh/config` and
replace `YOUR_VPS_IP_HERE` under `Host dxmap-vps` with the real IP. Test it:

```bash
ssh dxmap-vps "hostname; docker ps --format '{{.Names}} {{.Ports}}'; ss -tlnp | grep -E ':(80|443|8020) '"
```

Eyeball that output yourself — confirm nothing's already on port 8020, and
see what tahiafilms/marawan are actually using so you know what you're
sharing the box with.

## 3. Point dxmap.nabilvs.com at the VPS (Cloudflare dashboard)

1. dash.cloudflare.com → nabilvs.com → DNS → Add record.
2. Type `A`, Name `dxmap`, IPv4 address = the VPS IP, **Proxy status: DNS
   only (grey cloud)** for the first deploy — Certbot's HTTP challenge needs
   to reach the VPS directly. You can switch it to Cloudflare-proxied
   (orange cloud) after the certificate is issued, if you want Cloudflare's
   CDN/WAF in front of it too.
3. Save. DNS propagation is usually fast on Cloudflare (minutes), but give
   it up to 30 min before assuming something's wrong.

Verify from anywhere:

```bash
dig +short dxmap.nabilvs.com A   # should print the VPS IP
```

## 4. Ship the code and deploy

```bash
# From dragon, in the hermes-map project directory:
scp -r . dxmap-vps:/opt/hermes-map

ssh dxmap-vps
bash /opt/hermes-map/deploy/deploy.sh dxmap.nabilvs.com
```

`deploy.sh` now refuses to run if port 8020 is already taken by something
that isn't itself, and warns (without blocking) if it spots a
tahia/marawan-looking container — read those messages if they show up
instead of re-running blindly.

This installs its own systemd service (`hermes`) bound to
`127.0.0.1:8020`, its own Nginx site file
(`/etc/nginx/sites-available/hermes-map`, proxying `dxmap.nabilvs.com` →
that port), and — since you passed a real domain — attempts a free Let's
Encrypt cert via Certbot automatically.

## 5. Verify

```bash
curl -sI https://dxmap.nabilvs.com/          # expect 200
curl -s https://dxmap.nabilvs.com/api/health # expect {"status":"ok",...}
systemctl status hermes                       # active (running)
nginx -t                                       # syntax ok, and didn't touch
                                                # tahiafilms/marawan's site files
```

Then open `https://dxmap.nabilvs.com` in a browser — same live map you saw
locally on port 8010, now public, real data, real agent, correctly labeled
"Discrimination Map" (title/H1 fixed 2026-07-17).

## 6. The website side is already done

`nabilvs.com`'s portfolio case-study page
(`Nabil Visual Solutions/src/app/portfolio/discrimination-map/page.tsx`)
already links "Open the live map" to `https://dxmap.nabilvs.com` in a new
tab — nothing more to change there once steps 1–5 are live. Until then that
button 404s/times out, which is expected — it'll start working the moment
DNS + deploy are done.

## Rollback / re-run safety

Every step here is idempotent — re-running `deploy.sh` is safe (it'll just
restart the service and reload Nginx). To pull it entirely:

```bash
ssh dxmap-vps
systemctl disable --now hermes
rm /etc/nginx/sites-enabled/hermes-map
nginx -t && systemctl reload nginx
```

Tahiafilms/marawan are untouched by any of this — they live in their own
systemd units / containers and Nginx site files, never referenced above.
