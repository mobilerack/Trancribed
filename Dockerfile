# 1. lépés: Alapkép kiválasztása
# Egy karcsú, hivatalos Python 3.11-es image-et használunk.
FROM python:3.11-slim

# 2. lépés: Munkakönyvtár beállítása a konténeren belül
WORKDIR /app

# 3. lépés: Környezeti változók beállítása
# Megakadályozza, hogy a Python .pyc fájlokat írjon a lemezre
ENV PYTHONDONTWRITEBYTECODE 1
# Biztosítja, hogy a Python kimenete pufferelés nélkül jelenjen meg a logokban
ENV PYTHONUNBUFFERED 1

# 4. lépés: Függőségek telepítése
# Először csak a requirements.txt-t másoljuk be és telepítjük.
# Ez a Docker "caching" miatt hatékony: ha a kód változik, de a függőségek nem,
# a Dockernek nem kell újra telepítenie mindent.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. lépés: Az alkalmazás kódjának bemásolása
COPY . .

# 6. lépés: Az indítási parancs (CMD)
# Ez a parancs fog lefutni, amikor a Render elindítja a konténeredet.
# Gunicorn-t használunk, és a ${PORT} változóval a Render által megadott porton indítjuk el.
CMD gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:${PORT} main:app

