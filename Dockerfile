# 1. lépés: Alapkép kiválasztása
FROM python:3.11-slim

# 2. lépés: Munkakönyvtár beállítása
WORKDIR /app

# 3. lépés: Környezeti változók
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 4. lépés: Függőségek telepítése
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. lépés: Az alkalmazás kódjának és az indító scriptnek a bemásolása
COPY . .

# 6. lépés: Futtathatóvá tesszük az indító scriptet
RUN chmod +x /app/entrypoint.sh

# 7. lépés: Az indítási parancs (ENTRYPOINT)
# Ez a script fog lefutni, amikor a konténer elindul.
ENTRYPOINT ["/app/entrypoint.sh"]
