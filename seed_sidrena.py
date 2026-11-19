#!/usr/bin/env python3
"""JEDNOKRATNO: upiše metafield custom.sidrena_cijena (razina PROIZVODA) = trenutna cijena
za aktivne proizvode koji ga nemaju. Postojeće vrijednosti NE dira.

Pokreni SAMO ako se cijene tih proizvoda nisu mijenjale od 10.9.2026.
Prvo s DRY_RUN=1. Zahtijeva token s write_products.
"""
import json, os, urllib.request

import urllib.parse
STORE = os.environ["SHOPIFY_STORE"]
VER = os.environ.get("SHOPIFY_API_VERSION", "2025-10"); DRY = bool(os.environ.get("DRY_RUN"))


def token():
    if os.environ.get("SHOPIFY_ADMIN_TOKEN"):
        return os.environ["SHOPIFY_ADMIN_TOKEN"]
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
        "client_id": os.environ["SHOPIFY_CLIENT_ID"],
        "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}).encode()
    r = urllib.request.Request(f"https://{STORE}/admin/oauth/access_token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(r, timeout=60))["access_token"]


def gql(q, v=None):
    r = urllib.request.Request(f"https://{STORE}/admin/api/{VER}/graphql.json",
        data=json.dumps({"query": q, "variables": v or {}}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token()})
    d = json.load(urllib.request.urlopen(r, timeout=60))
    if "errors" in d:
        raise RuntimeError(d["errors"])
    return d["data"]


Q = """query($c:String){products(first:50,after:$c,query:"status:active"){pageInfo{hasNextPage endCursor}
nodes{id title sidrena:metafield(namespace:"custom",key:"sidrena_cijena"){value}
variants(first:100){nodes{price}}}}}"""
M = """mutation($m:[MetafieldsSetInput!]!){metafieldsSet(metafields:$m){userErrors{message}}}"""

todo, c = [], None
while True:
    d = gql(Q, {"c": c})["products"]
    for p in d["nodes"]:
        if p["sidrena"]:
            continue
        prices = {float(v["price"]) for v in p["variants"]["nodes"]}
        if len(prices) > 1:
            print(f"PAZI: {p['title']} ima varijante s različitim cijenama {sorted(prices)}, uzimam najnižu")
        todo.append({"ownerId": p["id"], "namespace": "custom", "key": "sidrena_cijena",
                     "type": "number_decimal", "value": f"{min(prices):.2f}"})
        print(f"  {p['title']}: {min(prices):.2f}")
    if not d["pageInfo"]["hasNextPage"]:
        break
    c = d["pageInfo"]["endCursor"]

print(f"Proizvoda bez sidrene cijene: {len(todo)}")
for i in range(0, len(todo), 25):
    if DRY:
        continue
    r = gql(M, {"m": todo[i:i + 25]})["metafieldsSet"]["userErrors"]
    print("greške:", r) if r else print("upisano", i + len(todo[i:i + 25]))
