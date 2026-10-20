# Instagram autopilotas – Success Hunters

Kasdien 3 karuselės iš Google Drive į Instagram, JAV piko metu:

| Slotas | Niujorkas | Lietuva |
|---|---|---|
| 1 (`01_…` aplankas) | 13:00 | 20:00 |
| 2 (`02_…` aplankas) | 17:00 | 00:00 |
| 3 (`03_…` aplankas) | 21:00 | 04:00 |

Laikas skaičiuojamas pagal Niujorką, todėl laikrodžių sukiojimas (LT spalio 25, JAV lapkričio 1) nieko nesugadina.

**Kaip veikia vienas postas:**
1. GitHub Actions pasileidžia nustatytu laiku.
2. Drive'e randa `Instagram/2026.10/21.10.2026/03_…`.
3. Paima nuotraukas eilės tvarka (01, 02, 03 … 13), konvertuoja į JPG (Instagram nepriima PNG).
4. Iš `instagram_caption*.pdf` ištraukia aprašymą (jei yra `_updated`, ima jį).
5. Publikuoja kaip karuselę (iki 20 nuotraukų).
6. Atsiunčia į Telegram: nuorodą į postą + **kurią dainą pridėti** iš tavo Saved.

Muziką prie karuselės Instagram leidžia pridėti tik programėlėje: postas → ⋯ → **Edit** → **Add music**. Apie 15 sekundžių.

**Apsaugos:** kiekvienas slotas paleidžiamas du kartus (jei GitHub vėluoja ar praleidžia), bet tas pats postas niekada neišeina dukart. Jei kažkas nepavyksta (nėra aplanko, nėra PDF, Instagram klaida), gauni pranešimą su priežastimi.

---

## Setup (apie 45 min., vieną kartą)

### 1. GitHub repozitorija
1. Susikurk paskyrą [github.com](https://github.com), jei neturi.
2. **New repository** → pavadinimas `ig-autopost` → **Public** → Create.
   *Kodėl viešas:* Instagram turi pats atsisiųsti nuotraukas iš viešos nuorodos. Kode nėra jokių slaptažodžių, jie laikomi atskirai (Secrets).
3. **Add file → Upload files** → įkelk viską iš šio archyvo (įskaitant `.github` aplanką) → Commit.
4. **Settings → Actions → General → Workflow permissions** → pažymėk **Read and write permissions** → Save.

### 2. Google Drive prieiga
Paprasčiausias kelias (veikia, kol aplankas bendrinamas „visi, turintys nuorodą"):
1. [console.cloud.google.com](https://console.cloud.google.com) → sukurk projektą.
2. **APIs & Services → Library** → „Google Drive API" → **Enable**.
3. **APIs & Services → Credentials → Create credentials → API key**. Nukopijuok.
4. Rekomenduojama: paspausk ant rakto → **API restrictions** → pasirink tik „Google Drive API".

Saugesnis kelias (leidžia aplanką padaryti privatų): **Credentials → Create credentials → Service account** → atsisiųsk JSON raktą → Drive'e pasidalink aplanku `Instagram` su to service account el. paštu (Viewer). Tada vietoj `GOOGLE_API_KEY` naudosi `GOOGLE_SERVICE_ACCOUNT_JSON`.

### 3. Instagram (Meta) prieiga
Paskyra turi būti **Creator** arba **Business** (tavo yra Creator ✓). Facebook puslapio nereikia.
1. [developers.facebook.com](https://developers.facebook.com) → prisijunk → **My Apps → Create app**.
2. Use case: **Manage messaging & content on Instagram** → toliau → Create.
3. Kairėje **Instagram → API setup with Instagram login**.
4. **App roles → Roles → Add people → Instagram Tester** → įvesk savo Instagram vardą. Tada Instagram programėlėje: **Settings → Website permissions / Apps and websites → Tester invites** → Accept.
5. Grįžk į **API setup with Instagram login** → **Generate access tokens → Add account** → prisijunk Instagram paskyra → leisk teises → **Generate token**. Nukopijuok tokeną (galioja 60 d., sistema jį atnaujina kas pirmadienį).

App lieka „Development" režime. Savo paskyrai publikuoti to pakanka, Meta peržiūros nereikia.

### 4. Discord pranešimai (rekomenduojama)
1. Discord'e savo serveryje sukurk kanalą, pvz. `#instagram`.
2. Kanalo ⚙️ **Edit Channel → Integrations → Webhooks → New Webhook** → **Copy Webhook URL**.
3. Įdėk kaip secret `DISCORD_WEBHOOK_URL`.

### 5. Secrets GitHub'e
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Pavadinimas | Ką įdėti |
|---|---|
| `IG_ACCESS_TOKEN` | Instagram tokenas (3 žingsnis) |
| `IG_USER_ID` | gausi 6 žingsnyje, kol kas praleisk |
| `GOOGLE_API_KEY` **arba** `GOOGLE_SERVICE_ACCOUNT_JSON` | 2 žingsnis (JSON įklijuok visą) |
| `DISCORD_WEBHOOK_URL` | 4 žingsnis |
| `GH_PAT` | kad tokenas atsinaujintų automatiškai: GitHub → Settings → Developer settings → Fine-grained tokens → tik šis repo → **Secrets: Read and write** |

### 6. Patikrinimas
1. Repo → **Actions → Check setup / refresh token → Run workflow** (action: `check`).
2. Atsidaryk rezultatą. Turi matyti `✓ @tavo_vardas`, `user_id = …` ir artimiausių 3 dienų postus.
3. Tą `user_id` įrašyk į secret `IG_USER_ID` ir paleisk patikrinimą dar kartą → `ALL GOOD`.

### 7. Bandomasis paleidimas (nieko nepublikuoja)
**Actions → Publish Instagram post → Run workflow** → data `2026-10-21`, slot `1`, **Dry run ✓**.
Apačioje **Artifacts → preview** atsisiųsi paruoštas JPG nuotraukas eilės tvarka ir `caption.txt`. Patikrink, ar viskas teisinga.

### 8. Gyvas testas
Tas pats, tik **Dry run** nuimtas. ⚠️ Postas iškart išeina viešai. Nuo šios akimirkos grafikas veikia savaime.

---

## Kasdienis naudojimas
- Tiesiog kelk aplankus į Drive kaip dabar: `2026.11/1.11.2026/01_…, 02_…, 03_…`. Kitam mėnesiui sukurk `2026.11`.
- Nuotraukų tvarka = skaičius failo pradžioje (`01_`, `02_` …).
- Aplankai kaip `8.10.2026 vol. 2` ar `…_Store_Test` **ignoruojami** (gausi įspėjimą).
- Išpublikuotų postų sąrašas: `state/published.json`.
- Norint pakartotinai išleisti tą patį postą: Run workflow su **Force ✓**.

## Muzika
`music/library.json` – tavo Saved dainos su nuotaikomis, pagal kurias parenkama daina:
```json
[{"title": "Daina", "artist": "Atlikėjas", "tags": ["calm", "dark", "focus"]}]
```
Nuotaikos: `calm, focus, dark, epic, cinematic, spiritual, intense, aggressive, hype, confident, hip-hop, motivational`.
Konkrečiam postui gali nurodyti dainą ranka `music/plan.json`: `{"2026-10-21#1": "Daina – Atlikėjas"}`.

## Techninė dalis
- `autopost/publish.py` – pagrindinė eiga · `drive.py` – Drive · `captions.py` – PDF → aprašymas · `images.py` – JPG · `instagram.py` – Instagram API · `schedule.py` – laikas · `music.py` – dainos · `notify.py` – Discord
- Testai: `pip install -r requirements.txt && pytest`
- Jei Instagram atmestų 3:4 formatą, sistema automatiškai bando dar kartą su 4:5 (prideda plonas šonines juostas, piešinio nekarpo).
