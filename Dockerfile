# Gunakan image dasar Python
FROM python:3.11-slim

# Tetapkan direktori kerja di dalam container
WORKDIR /app

# Salin file requirements.txt dan instal dependensi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin semua kode aplikasi ke dalam container
COPY . .

# Cloud Run menggunakan variabel PORT. Kita perlu memastikan bot berjalan di port ini.
ENV PORT 8080

# Jalankan perintah startup bot
CMD ["python", "main.py"]
