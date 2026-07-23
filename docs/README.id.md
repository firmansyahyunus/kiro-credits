# kcredits

Laporan pemakaian credit Kiro CLI dari data lokal dengan batas privasi yang
jelas.

`kcredits` membaca metadata credit dari session Kiro milik user OS yang sedang
aktif, lalu mengelompokkannya per project, model, dan hari. Command report
bersifat read-only, tidak membutuhkan Kiro API key, tidak mengirim telemetry,
dan tidak mempunyai dependency runtime pihak ketiga.

> **Project komunitas:** project ini tidak berafiliasi, dikelola, atau didukung
> secara resmi oleh Kiro maupun Amazon Web Services.

[English](../README.md)

## Yang perlu disiapkan

- Kiro CLI sudah login dan minimal satu response sudah selesai.
- Python 3.12 atau lebih baru.
- Jalankan dengan user OS yang sama dengan user yang menjalankan Kiro CLI.

## Cara cepat

### Windows PowerShell

```powershell
git clone https://github.com/firmansyahyunus/kiro-credits.git
Set-Location .\kiro-credits

py -3.12 .\kcredits.py doctor
py -3.12 .\kcredits.py report month
```

### macOS atau Linux

```bash
git clone https://github.com/firmansyahyunus/kiro-credits.git
cd kiro-credits

python3 ./kcredits.py doctor
python3 ./kcredits.py report month
```

## Command utama

```text
kcredits doctor
kcredits report today
kcredits report week
kcredits report month
kcredits report all
kcredits report all --project example-project
kcredits report month --json
kcredits report month --json --safe-share
kcredits doctor --safe-share
```

Jika menjalankan langsung dari source, ganti `kcredits` dengan
`py -3.12 .\kcredits.py` di Windows atau `python3 ./kcredits.py` di macOS/Linux.

## Privasi

- `report` dan `doctor` hanya membaca data Kiro lokal.
- Tool tidak mengirim data session, path project, atau metadata credit ke
  jaringan.
- Isi prompt dan response tidak dimasukkan ke laporan.
- Snapshot opsional hanya menulis ke `~/.kcredits/usage.csv`, kecuali lokasi
  diganti sendiri melalui `KCREDITS_DATA_DIR`.
- Gunakan `--safe-share` atau `--redact-paths` sebelum menyalin output ke issue,
  chat, screenshot, atau log. Opsi ini mengganti path lokal dengan label
  sintetis.
- Jangan upload session asli, archive CSV, atau screenshot yang masih
  memperlihatkan path pribadi ke GitHub issue.

Lihat [SECURITY.md](../SECURITY.md) dan
[PUBLIC-RELEASE-CHECKLIST.md](../PUBLIC-RELEASE-CHECKLIST.md) sebelum
repository dibuat public.

## Lisensi

[MIT](../LICENSE)
