#!/usr/bin/env python3
"""
Risolve gli UUID SCIM di Netskope (estratti dai log di audit) negli utenti corrispondenti.

Il file di input può contenere un UUID per riga oppure direttamente le righe copiate
dall'audit log: gli UUID vengono estratti via regex e deduplicati mantenendo l'ordine.

Uso:
  python resolve_scim_ids.py --tenant xxx.goskope.com --file ids.txt
  python resolve_scim_ids.py --tenant xxx.goskope.com --file ids.txt --out risultati.csv

Token: --token, oppure variabile d'ambiente NETSKOPE_TOKEN, altrimenti viene chiesto
a prompt (consigliato, così non finisce nella history della shell).
Il token REST API v2 deve avere permesso di lettura su /api/v2/scim/Users.
"""

import argparse
import csv
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
FIELDS = ["id", "userName", "displayName", "email", "externalId", "active", "groups", "status"]
MAX_RETRIES = 3


def load_ids(path):
    with open(path, encoding="utf-8") as f:
        found = UUID_RE.findall(f.read())
    # dedup mantenendo l'ordine
    return list(dict.fromkeys(i.lower() for i in found))


def get_user(base_url, token, uid):
    req = urllib.request.Request(
        f"{base_url}/api/v2/scim/Users/{uid}",
        headers={"Netskope-Api-Token": token, "Accept": "application/json"},
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp), "OK"
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                wait = int(e.headers.get("Retry-After", 5))
                print(f"  429 rate limit su {uid}, attendo {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                sys.exit(f"Errore {e.code}: token non valido o senza permessi su /api/v2/scim/Users")
            return None, f"HTTP {e.code}"
        except urllib.error.URLError as e:
            return None, f"Errore rete: {e.reason}"
    return None, "HTTP 429 (retry esauriti)"


def to_row(uid, data, status):
    if data is None:
        return {"id": uid, "status": status}
    emails = data.get("emails") or []
    primary = next((m.get("value") for m in emails if m.get("primary")), None)
    if primary is None and emails:
        primary = emails[0].get("value")
    groups = data.get("groups") or []
    return {
        "id": data.get("id", uid),
        "userName": data.get("userName", ""),
        "displayName": data.get("displayName", ""),
        "email": primary or "",
        "externalId": data.get("externalId", ""),
        "active": data.get("active", ""),
        "groups": "; ".join(g.get("display") or g.get("value", "") for g in groups),
        "status": status,
    }


def main():
    p = argparse.ArgumentParser(description="Risolve UUID SCIM Netskope in utenti")
    p.add_argument("--tenant", required=True, help="es. xxx.goskope.com")
    p.add_argument("--file", required=True, help="txt con UUID o righe di audit log")
    p.add_argument("--token", help="token REST API v2 (alternativa: env NETSKOPE_TOKEN o prompt)")
    p.add_argument("--out", help="salva anche in CSV")
    args = p.parse_args()

    token = args.token or os.environ.get("NETSKOPE_TOKEN") or getpass.getpass("Token Netskope: ")
    tenant = args.tenant.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    base_url = f"https://{tenant}"

    ids = load_ids(args.file)
    if not ids:
        sys.exit("Nessun UUID trovato nel file.")
    print(f"{len(ids)} UUID da risolvere\n", file=sys.stderr)

    rows = [to_row(uid, *get_user(base_url, token, uid)) for uid in ids]

    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV salvato in {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
