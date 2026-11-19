# OpenThai OCR-Text บน Hostinger KVM2

รันโมเดล **OpenThai2.0-OCR-Text** (ตอนนี้ชื่อบน Hugging Face คือ
[`iapp/OpenThai2.1-OCR-Text-20261118`](https://huggingface.co/iapp/OpenThai2.1-OCR-Text-20261118) ชื่อเดิมยัง redirect มาที่นี่ได้)
เป็น API + หน้าเว็บ บน VPS แบบ CPU ล้วน ไม่ต้องใช้ GPU

| | |
|---|---|
| โมเดล | ONNX ~6.5 MB (detector + recognizer 2 ตัว) ล็อกเวอร์ชันที่ `v2.1.4` และตรวจ SHA256 ตอน build |
| RAM | ~450 MB ต่อ worker → KVM2 (2 vCPU / 8 GB) ใช้ 2 workers ได้สบาย |
| ความเร็ว | ประมาณ 0.3–1 วินาทีต่อหน้า A4 (ทดสอบบน Mac: รูป 1 หน้า 261 ms, PDF 2 หน้า 555 ms) |
| รองรับ | PNG, JPG, WEBP, BMP, TIFF, PDF (หลายหน้า) ภาษาไทย + อังกฤษ ตัวพิมพ์ |

## โครงสร้าง

```
app/main.py            FastAPI: POST /ocr, GET /health, หน้าเว็บ /
app/static/index.html  หน้าเว็บทดลองอัปโหลดไฟล์
Dockerfile             build image + ดาวน์โหลดโมเดล (pinned v2.1.4)
docker-compose.yml     ocr + caddy (reverse proxy, HTTPS อัตโนมัติ)
Caddyfile
.env.example           ค่าตั้ง (DOMAIN, API_KEY, workers, ลิมิต)
scripts/setup-vps.sh   ติดตั้ง Docker + firewall + รันทุกอย่างในคำสั่งเดียว
scripts/download_model.py
```

## ติดตั้งบน KVM2 (ทีละขั้น)

### 1. เตรียม VPS ใน hPanel
- OS: **Ubuntu 24.04** (หรือ template "Ubuntu 24.04 with Docker" ก็ได้)
- จด IP ของ VPS และรหัส root / ใส่ SSH key
- ถ้าเปิด Firewall ของ Hostinger ใน hPanel ไว้ ให้อนุญาตพอร์ต **22, 80, 443**

### 2. อัปโหลดโปรเจกต์ขึ้น VPS
จากเครื่อง Mac (ในโฟลเดอร์นี้):

```bash
rsync -av --exclude .env --exclude models ./ root@<VPS-IP>:/opt/openthai-ocr/
```

### 3. SSH เข้าไปแล้วรันสคริปต์ติดตั้ง

```bash
ssh root@<VPS-IP>
```

```bash
cd /opt/openthai-ocr && bash scripts/setup-vps.sh
```

สคริปต์จะ: ติดตั้ง Docker → เปิด firewall (22/80/443) → สร้าง `.env` พร้อม **API key สุ่มให้** →
build image (ดาวน์โหลดโมเดลและตรวจ checksum) → start → รอจนพร้อม แล้วพิมพ์ URL ให้
(build ครั้งแรกใช้เวลาประมาณ 3–5 นาที)

ดู API key ที่สร้างให้:

```bash
grep API_KEY /opt/openthai-ocr/.env
```

### 4. เปิดใช้งาน
- หน้าเว็บ: `http://<VPS-IP>/` (ใส่ API key ในช่องด้านบน)
- เอกสาร API: `http://<VPS-IP>/docs`

### 5. (แนะนำ) ใช้โดเมน + HTTPS
1. ตั้ง DNS: A record เช่น `ocr.yourdomain.com` → IP ของ VPS
2. แก้ `.env` ให้ `DOMAIN=ocr.yourdomain.com`
3. รีสตาร์ต Caddy — มันจะขอใบรับรอง Let's Encrypt ให้เอง:

```bash
cd /opt/openthai-ocr && docker compose up -d
```

## การเรียกใช้ API

ข้อความล้วน:

```bash
curl -H "X-API-Key: <KEY>" -F file=@page.jpg "https://ocr.yourdomain.com/ocr?format=text"
```

JSON (ข้อความ + กล่องพิกัดและความมั่นใจของทุกบรรทัด/คำ):

```bash
curl -H "X-API-Key: <KEY>" -F file=@document.pdf https://ocr.yourdomain.com/ocr
```

```json
{
  "model": "iapp/OpenThai2.1-OCR-Text-20261118@v2.1.4",
  "pages": 1, "ms": 261,
  "text": "ใบเสร็จรับเงิน บริษัท ตัวอย่าง จำกัด\n...",
  "results": [{ "page": 1, "text": "...", "confidence": 0.97, "ms": 250,
                "lines": [{ "text": "...", "confidence": 0.95, "row": 0, "box": [[x,y],...], "words": [...] }] }]
}
```

Python:

```python
import requests
r = requests.post("https://ocr.yourdomain.com/ocr",
                  headers={"X-API-Key": "<KEY>"},
                  files={"file": open("page.png", "rb")})
print(r.json()["text"])
```

พารามิเตอร์: `format=json|text`, `dpi=72..400` (ความละเอียดตอนแปลง PDF, ค่าเริ่มต้น 200)
ส่ง key ได้ทั้ง `X-API-Key: <KEY>` หรือ `Authorization: Bearer <KEY>`

## ค่าตั้งใน `.env`

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `DOMAIN` | `:80` | โดเมน (HTTPS อัตโนมัติ) หรือ `:80` = HTTP ผ่าน IP |
| `API_KEY` | (สุ่มโดย setup) | ว่าง = ไม่ต้องใช้ key (ไม่แนะนำบนเซิร์ฟเวอร์สาธารณะ) |
| `OCR_WORKERS` | `2` | จำนวน process = จำนวน vCPU |
| `MAX_UPLOAD_MB` | `25` | ขนาดไฟล์สูงสุด |
| `MAX_PDF_PAGES` | `50` | จำนวนหน้า PDF สูงสุดต่อคำขอ |
| `PDF_DPI` | `200` | ความละเอียดตอนแปลง PDF เป็นภาพ |

แก้แล้วรัน `docker compose up -d` ใหม่

## ดูแลระบบ

ดู log:

```bash
cd /opt/openthai-ocr && docker compose logs -f ocr
```

อัปเดตโค้ด (rsync ใหม่แล้ว build):

```bash
cd /opt/openthai-ocr && docker compose up -d --build
```

เปลี่ยนเวอร์ชันโมเดล: แก้ `ARG MODEL_REVISION` ใน `Dockerfile` (เช่น `v2.0.0`) แล้ว build ใหม่

ตรวจสถานะ: `curl http://<VPS-IP>/health`

## รันโมเดลบนเครื่องตัวเองโดยตรง (ไม่มีเซิร์ฟเวอร์ ไม่ใช้เน็ต)

```bash
.venv/bin/python ocr_local.py page.jpg
```

```bash
.venv/bin/python ocr_local.py เอกสาร.pdf โฟลเดอร์สแกน/ -o ผลลัพธ์/
```

`--json` ได้กล่องพิกัด + ความมั่นใจ, `--dpi 300` ความละเอียด PDF, `--paragraphs` เว้นบรรทัดระหว่างย่อหน้า
ผลลัพธ์แบบโฟลเดอร์จะได้ไฟล์ชื่อ `<ชื่อไฟล์เดิม>.txt` เช่น `page.pdf.txt`

## รันเป็นเว็บ/API บนเครื่องตัวเอง (ไม่ใช้ Docker)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python scripts/download_model.py --out models/openthai-ocr
```

```bash
MODEL_DIR=models/openthai-ocr .venv/bin/uvicorn app.main:app --port 8000
```

## ข้อจำกัดของโมเดล
- อ่าน **ตัวพิมพ์** เท่านั้น ลายมือและข้อความในภาพถ่ายฉากทั่วไปอ่านได้ไม่ดี
- ไม่ได้ส่งออกเป็นตาราง/Markdown (ถ้าต้องการ ใช้ OpenThai2.1-OCR-Markdown ซึ่งต้องใช้ GPU)
- ตราประทับจะถูกอ่านเป็นข้อความด้วย

ไลเซนส์โมเดล: Apache-2.0 (iApp Technology / PaddlePaddle PP-OCRv6)
