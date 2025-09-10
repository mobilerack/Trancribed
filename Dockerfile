# 1. lépés: Válasszunk egy hivatalos Python alap-image-et
FROM python:3.11-slim

# 2. lépés: Telepítsük a rendszerfüggőségeket (pl. ffmpeg az audio feldolgozáshoz)
# A 'apt-get update' frissíti a csomaglistát, a '-y' automatikusan igennel válaszol
# A '&& rm -rf /var/lib/apt/lists/*' a végén kitakarít, hogy kisebb legyen az image
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 3. lépés: Hozzunk létre egy munkakönyvtárat a konténeren belül
WORKDIR /app

# 4. lépés: Másoljuk be a függőségeket leíró fájlt
# Ezt külön csináljuk, mert a Docker gyorsítótárazza a rétegeket. Ha a requirements.txt nem változik,
# nem fogja újra telepíteni a csomagokat minden buildnél.
COPY requirements.txt .

# 5. lépés: Telepítsük a Python függőségeket
# A '--no-cache-dir' opcióval elkerüljük a felesleges cache fájlokat, így ismét méretet csökkentünk
RUN pip install --no-cache-dir -r requirements.txt

# 6. lépés: Másoljuk be a projekt többi fájlját a munkakönyvtárba
COPY . .

# 7. lépés: Adjunk meg egy környezeti változót a portnak, amin a Gunicorn figyelni fog
ENV PORT 10000

# 8. lépés: Tegyük elérhetővé a konténer portját a külvilág számára
EXPOSE 10000

# 9. lépés: Indítsuk el az alkalmazást a Gunicorn-nal (ez egy production-ready szerver)
# A 'main:app' azt jelenti, hogy a 'main.py' fájlban keresse az 'app' nevű Flask objektumot
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "main:app"]
