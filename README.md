# Automatski dnevni cjenik (annyfit.store)

Svako jutro u 05:00 UTC (06:00 zimi / 07:00 ljeti, prije 8:00) GitHub Actions:
1. povuče aktivne proizvode iz Shopifya,
2. složi CSV s propisanim poljima i nazivom datoteke,
3. obriše cjenike starije od 30 dana,
4. objavi sve na GitHub Pages: `https://<korisnik>.github.io/<repo>/cjenik/` (+ `cjenik-latest.csv`).

## Postavljanje (jednokratno, ~20 min)
1. **Shopify**: Settings > Apps > Develop apps > Create app. Admin API scope: `read_products` (za seed i `write_products`). Instaliraj i kopiraj Admin API access token.
2. **Metafield**: Već postoji: product metafield `custom.sidrena_cijena` (Decimal).
3. **GitHub**: napravi repozitorij i uploadaj ove datoteke. Settings > Pages > Source: branch `main`, folder `/docs`. (Pages na privatnom repou traži plaćeni plan; u repou nema osobnih podataka, samo cijene i history.json.)
4. Settings > Secrets and variables > Actions:
   - Secrets: `SHOPIFY_STORE` (npr. `xxxx.myshopify.com`), `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` (iz Shopify Dev Dashboarda)
   - Variables: `CJENIK_ADRESA` (npr. `Vlaška 68`), `CJENIK_MJESTO`, `CJENIK_OZNAKA` (npr. `P1`), `CJENIK_BROJ_POHRANE` (npr. `01`)
5. **Sidrene cijene**: ako se cijene nisu mijenjale od 10.9.2026., pokreni jednom lokalno
   `DRY_RUN=1 SHOPIFY_STORE=... SHOPIFY_ADMIN_TOKEN=... python3 seed_sidrena.py`, pa isto bez `DRY_RUN`.
   Inače ručno upiši pravu cijenu s 10.9. u metafield (nove proizvode nakon 10.9.: prva cijena prodaje).
6. Actions > Dnevni cjenik > Run workflow (probni run). Provjeri `docs/cjenik/`.
7. **Na webu**: u Shopify podnožje dodaj link "Cjenik (CSV)" na Pages adresu.

## Kako radi akcija
Akcija = `Compare at price` veći od `Price`. Tada je `posebni_oblik_prodaje` = "Akcija", a `najniza_cijena_30_dana` je najniža cijena u 30 dana prije početka akcije (iz history.json, koji se vodi od prvog runa; početna točka je sidrena cijena). Na stranici proizvoda i dalje moraš prikazati sve tri cijene (to cjenik ne rješava).

## Napomene
- Ako varijanta nema metafield, skripta upiše trenutnu cijenu i ispiše UPOZORENJE u logu.
- Struktura CSV-a nije službeno propisana (samo obavezna polja); koristi se `;` i UTF-8. Dodana je kolona `najniza_cijena_30_dana`.
- Provjeri s računovođom/Ministarstvom što upisati kao oblik, adresu i oznaku prodajnog objekta za web trgovinu.
- GitHub može zakasniti cron nekoliko minuta; ako je kritično, pomakni na `0 4 * * *`.
- Test bez Shopifya: `MOCK=1 python3 generate_cjenik.py`.
