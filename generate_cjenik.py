#!/usr/bin/env python3
"""Dnevni cjenik (CSV) za Shopify trgovinu prema Odluci o objavi cjenika.

- Povlači aktivne proizvode i varijante iz Shopify Admin GraphQL API-ja.
- Sidrena cijena dolazi iz metafielda custom.sidrena_cijena (po varijanti).
- Vodi povijest cijena (history.json) i računa najnižu cijenu u 30 dana prije akcije.
- Sprema CSV s propisanim nazivom, briše datoteke starije od 30 dana, gradi docs/cjenik/index.html.

Samo standardna biblioteka. Env: SHOPIFY_STORE, SHOPIFY_ADMIN_TOKEN (vidi README).
Test bez Shopifya: MOCK=1 python3 generate_cjenik.py
"""
import csv, json, os, re, sys, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CFG = {
    "STORE": os.environ.get("SHOPIFY_STORE", "annyfit.store"),  # npr. xxxx.myshopify.com
    "TOKEN": os.environ.get("SHOPIFY_ADMIN_TOKEN", ""),
    "API_VERSION": os.environ.get("SHOPIFY_API_VERSION", "2025-10"),
    "FORMAT": os.environ.get("CJENIK_OBLIK", "WEBSHOP"),        # oblik prodajnog objekta
    "ADRESA": os.environ.get("CJENIK_ADRESA", "ULICA1"),        # npr. VLASKA68
    "MJESTO": os.environ.get("CJENIK_MJESTO", "MJESTO"),        # npr. LJUBUSKI... (grad sjedišta)
    "OZNAKA": os.environ.get("CJENIK_OZNAKA", "P1"),            # oznaka prodajnog objekta
    "BROJ": os.environ.get("CJENIK_BROJ_POHRANE", "01"),        # broj pohrane
    "ANCHOR_DATE": "2026-09-10",
    "RETENTION_DAYS": 30,
}
TZ = ZoneInfo("Europe/Zagreb")
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "cjenik")
HIST = os.path.join(ROOT, "history.json")
NAME_RE = re.compile(r"_(\d{8})_(\d{4})\.CSV$")

QUERY = """
query($cursor: String) {
  products(first: 50, after: $cursor, query: "status:active") {
    pageInfo { hasNextPage endCursor }
    nodes {
      title vendor
      sidrena: metafield(namespace: "custom", key: "sidrena_cijena") { value }
      variants(first: 100) { nodes {
        id sku barcode title price compareAtPrice availableForSale
      } }
    }
  }
}"""


def ascii_up(s):
    s = unicodedata.normalize("NFKD", s.replace("Đ", "D").replace("đ", "d"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def get_token():
    """Token iz SHOPIFY_ADMIN_TOKEN, ili (Dev Dashboard app) client credentials: važi 24 h."""
    if CFG["TOKEN"]:
        return CFG["TOKEN"]
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["SHOPIFY_CLIENT_ID"],
        "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}).encode()
    req = urllib.request.Request(f"https://{CFG['STORE']}/admin/oauth/access_token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["access_token"]


def gql(query, variables):
    url = f"https://{CFG['STORE']}/admin/api/{CFG['API_VERSION']}/graphql.json"
    req = urllib.request.Request(
        url, data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": get_token()})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def money(v):
    """Metafield money ({"amount":"49.0",...}) ili decimal ("49.00") -> float; None ako nema."""
    if v in (None, ""):
        return None
    try:
        return float(json.loads(v)["amount"])
    except Exception:
        try:
            return float(v)
        except Exception:
            return None


def fetch_variants():
    if os.environ.get("MOCK"):
        return [
            {"naziv": "ANNY CROP TOP - S", "sifra": "CT-S", "marka": "ANNY", "barkod": "3850000000011",
             "price": 35.0, "compare": None, "avail": True, "sidrena": 35.0, "id": "gid://mock/1"},
            {"naziv": "ANNY AKTIV TAJICE - M", "sifra": "AT-M", "marka": "ANNY", "barkod": "",
             "price": 39.0, "compare": 49.0, "avail": False, "sidrena": 49.0, "id": "gid://mock/2"},
        ]
    out, cursor = [], None
    while True:
        d = gql(QUERY, {"cursor": cursor})["products"]
        for p in d["nodes"]:
            for v in p["variants"]["nodes"]:
                name = p["title"] if v["title"] == "Default Title" else f"{p['title']} - {v['title']}"
                out.append({
                    "naziv": name, "sifra": v["sku"] or v["id"].rsplit("/", 1)[-1],
                    "marka": p["vendor"], "barkod": v["barcode"] or "",
                    "price": float(v["price"]),
                    "compare": float(v["compareAtPrice"]) if v["compareAtPrice"] else None,
                    "avail": bool(v["availableForSale"]),
                    "sidrena": money((p["sidrena"] or {}).get("value")), "id": v["id"],
                })
        if not d["pageInfo"]["hasNextPage"]:
            return out
        cursor = d["pageInfo"]["endCursor"]


def main():
    now = datetime.now(TZ)
    today = now.date()
    state = json.load(open(HIST)) if os.path.exists(HIST) else {}
    rows, warnings = [], []

    for v in fetch_variants():
        s = state.setdefault(v["id"], {"hist": {}, "sale": None})
        sid = v["sidrena"]
        if sid is None:
            sid = v["compare"] or v["price"]
            warnings.append(f"{v['sifra']} {v['naziv']}: nema metafield sidrena_cijena, upisano {sid:.2f}")
        if not s["hist"]:  # prvi put: početna točka povijesti je sidrena cijena na referentni datum
            s["hist"][CFG["ANCHOR_DATE"]] = sid
        on_sale = v["compare"] is not None and v["compare"] > v["price"]
        lowest = ""
        if on_sale:
            if not s["sale"]:
                cutoff = (today - timedelta(days=30)).isoformat()
                prev = [p for d, p in s["hist"].items() if cutoff <= d < today.isoformat()]
                s["sale"] = {"start": today.isoformat(), "ref": min(prev) if prev else sid}
            lowest = f"{s['sale']['ref']:.2f}"
        else:
            s["sale"] = None
        s["hist"][today.isoformat()] = v["price"]
        keep = (today - timedelta(days=60)).isoformat()
        s["hist"] = {d: p for d, p in s["hist"].items() if d >= keep}
        rows.append([v["naziv"], v["sifra"], v["marka"], "kom", f"{v['price']:.2f}", f"{v['price']:.2f}",
                     "Akcija" if on_sale else "", f"{sid:.2f}", v["barkod"], "DA" if v["avail"] else "NE", lowest])

    os.makedirs(OUT, exist_ok=True)
    fname = (f"{CFG['FORMAT']}_{ascii_up(CFG['ADRESA'])}_{ascii_up(CFG['MJESTO'])}_{CFG['OZNAKA']}_"
             f"{CFG['BROJ']}_{now:%d%m%Y_%H%M}.CSV")
    header = ["naziv", "sifra", "marka", "jedinica_mjere", "cijena_za_jedinicu_mjere", "mpc",
              "posebni_oblik_prodaje", "sidrena_cijena", "barkod", "dostupnost", "najniza_cijena_30_dana"]
    with open(os.path.join(OUT, fname), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    with open(os.path.join(OUT, "cjenik-latest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)

    # čuvanje 30 dana
    limit = now - timedelta(days=CFG["RETENTION_DAYS"])
    files = []
    for n in sorted(os.listdir(OUT)):
        m = NAME_RE.search(n)
        if not m:
            continue
        ts = datetime.strptime(m.group(1) + m.group(2), "%d%m%Y%H%M").replace(tzinfo=TZ)
        if ts < limit:
            os.remove(os.path.join(OUT, n))
        else:
            files.append((ts, n))
    files.sort(reverse=True)
    entries = [{"name": n, "date": f"{ts:%d.%m.%Y.}", "time": f"{ts:%H:%M}", "url": n} for ts, n in files]
    json.dump(entries, open(os.path.join(OUT, "arhiva.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    items = "\n".join(
        f'<li><a href="{e["url"]}" download>{e["name"]}</a> <span>({e["date"]})</span></li>' for e in entries)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(
        "<!doctype html><html lang='hr'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<title>Arhiva 30 dana</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:720px;margin:40px auto;"
        "padding:0 16px;color:#111}h1{font-weight:600}li{margin:6px 0}a{color:#111}span{color:#666}</style>"
        f"<h1>Arhiva 30 dana</h1><ul>{items}</ul></html>")

    json.dump(state, open(HIST, "w"), indent=1)
    print(f"OK: {fname}, redaka: {len(rows)}, u arhivi: {len(files)}")
    for w_ in warnings:
        print("UPOZORENJE:", w_)


if __name__ == "__main__":
    sys.exit(main())
