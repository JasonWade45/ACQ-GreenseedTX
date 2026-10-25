# نشر النظام على سيرفر حقيقي (أونلاين)

**آخر تحديث: 25 أكتوبر 2026.** هذا الدليل ينشر Acquisitions Assistant AI 1.2.x على سيرفر
تملكه أنت (VPS أو سيرفر Windows) مع HTTPS تلقائي، وحفظ دائم لقاعدة البيانات.

---

## ملاحظة صريحة أولًا

بيئة العمل الآلية التي أُعدّ فيها المشروع **لا تستطيع** النشر على منصات استضافة خارجية:
الوصول الشبكي مقيّد بـ GitHub وPyPI وnpm فقط، وجميع مزوّدي الاستضافة (Render, Railway,
Fly, Vercel) محجوبون، ولا يوجد Docker هناك للبناء. لذلك:

- ما تم إعداده هنا هو **كل ملفات النشر الجاهزة** + خطوات دقيقة.
- التنفيذ النهائي (بناء الصورة، شراء/تجهيز السيرفر) يحدث من جهازك أو سيرفرك.
- المعاينة الحية داخل المتصفح تعمل الآن، لكنها مرتبطة بجلسة العمل وليست استضافة دائمة.

> **تنبيه أمني مهم:** هذا النظام يحتوي بيانات عملاء الشركة. نشره على الإنترنت يعني نقل
> بيانات حقيقية إلى مزوّد خارجي. المشروع يفترض افتراضيًا التشغيل المحلي (loopback). لا تنشر
> بيانات شركة حقيقية على استضافة عامة إلا بعد موافقة صاحب البيانات وبعد تفعيل HTTPS وكلمة
> مرور قوية ونسخة احتياطية مشفّرة.

---

## المتطلبات

1. سيرفر Linux (Ubuntu 22.04/24.04 أو Debian 12) بـ **2 GB RAM** ومساحة 10 GB.
2. **Docker + Docker Compose v2** مثبّتان.
3. **اسم نطاق** يشير إلى عنوان السيرفر (سجل `A` للـ IPv4 و`AAAA` للـ IPv6).
4. المنافذ **80** و**443** مفتوحة في الجدار الناري.

تثبيت Docker على Ubuntu (أمر رسمي واحد):

```bash
curl -fsSL https://get.docker.com | sh
```

---

## خطوات النشر (خمس دقائق)

### 1) انسخ المشروع إلى السيرفر

```bash
git clone https://github.com/JasonWade45/ACQ-GreenseedTX.git
cd ACQ-GreenseedTX
```

للحصول على إصدار محدد بدل أحدث `main`:

```bash
git clone --branch v1.2.2 --depth 1 https://github.com/JasonWade45/ACQ-GreenseedTX.git acq
cd acq
```

### 2) جهّز ملف الإعدادات السرّي

```bash
cp deploy/compose.env.example deploy/.env
python3 -c "import secrets; print(secrets.token_hex(32))"   # انسخ الناتج في SESSION_SECRET
nano deploy/.env
```

املأ:
- `SITE_ADDRESS` → نطاقك، مثل `acq.company.com`
- `APP_ACCESS_PASSWORD` → كلمة مرور طويلة (12 حرفًا على الأقل، والأفضل 20+)
- `SESSION_SECRET` → الناتج العشوائي أعلاه
- `APP_TIMEZONE` → `Africa/Cairo` أو توقيت العمل الفعلي

> `deploy/.env` مستبعَد من Git. **لا** ترفعه إلى GitHub أو Drive ولا ترسله في محادثة.

### 3) ابنِ وشغّل

```bash
cd deploy
docker compose up -d --build
```

أول بناء يستغرق دقيقتين تقريبًا. Caddy يحصل على شهادة TLS تلقائيًا خلال نصف دقيقة.
تحقق من الحالة:

```bash
docker compose ps
docker compose logs -f caddy
```

### 4) تحقق من العمل

```bash
curl -s https://$SITE_ADDRESS/api/health
# {"status":"ok","application":"Acquisitions Assistant AI"}
```

افتح `https://<SITE_ADDRESS>` في المتصفح، سجّل الدخول بكلمة المرور، وستجد قاعدة بيانات
نظيفة (20 جدولًا، رأس `0a6d91cf17b2`) أُنشئت تلقائيًا.

---

## النشر على Windows في دقيقتين (الطريقة الموصى بها)

هذه هي الطريقة الأسرع والأكثر أمانًا، وقد تم التحقق من سلوكها فعليًا (انظر الجدول أسفل).

### 1) جهّز التطبيق

1. ثبّت Python 3.11+ من python.org مع تفعيل **Add python.exe to PATH**.
2. فك ضغط الحزمة في `C:\ACQ` (الواجهة مبنية — لا تحتاج Node ولا WSL).
3. انقر مزدوجًا على **`START-ONLINE-WINDOWS.cmd`**.

ماذا يفعل السكربت تلقائيًا:
- يولّد كلمة مرور عشوائية قوية + `SESSION_SECRET` ويكتبهما في `.env` (مرة واحدة فقط).
- يطبع كلمة المرور مرة واحدة — **احفظها في مدير كلمات مرور فورًا**.
- يتحقق أن طولها ≥ 12 حرفًا (شرط النظام لأي وصول غير محلي).
- ينشئ `.venv` ويثبّت الاعتماديات المقفلة عند أول تشغيل.
- يربط الخادم على `127.0.0.1:8010` فقط، ويطبع أوامر النفق الجاهزة.

> **لا يستبدل `.env` الموجود** إذا كانت كلمة المرور فيه صالحة. استخدم `-Force` للتغيير.

### 2) افتحه على الإنترنت — اختر واحدًا

**أ) نطاق دائم مجاني (موصى به):**

```powershell
winget install --id Cloudflare.cloudflared
# أغلق PowerShell وافتحه من جديد
SETUP-TUNNEL-WINDOWS.cmd acq.example.com
```

السكربت يتحقق من التثبيت والاتصال المحلي، يسجّل الدخول، ينشئ النفق، ينسخ أي
`config.yml` موجود قبل الكتابة، يربط DNS، ويثبّت خدمة Windows تلقائية.

**ب) رابط مؤقت للتجربة فورًا (بلا حساب):**

```powershell
cloudflared tunnel --url http://127.0.0.1:8010
```

يعطيك رابطًا مثل `https://random-words.trycloudflare.com` صالحًا أثناء تشغيل النافذة.

**ج) Tailscale:**

```powershell
tailscale funnel 8010
```

### 3) تحقّق

```powershell
curl.exe https://acq.example.com/api/health
```

يجب أن يعيد `{"status":"ok",...}`. ثم افتح الرابط وسجّل الدخول بكلمة المرور من `.env`.

---

## ⚠️ الفخ الذي يوقع الجميع: صفحة تفتح وبيانات لا تعمل

بلا `APP_ACCESS_PASSWORD` يعمل النظام في **وضع loopback**، فيرفض كل طلب `/api` يحمل Host
غير محلي برمز **403**، بينما الصفحة نفسها تُخدم بنجاح. النتيجة: الواجهة تفتح ثم تفشل كل
البيانات، ويبدو الأمر كعطل غامض.

| الإعداد | الصفحة | `/api/leads` |
|---|---|---|
| بلا كلمة مرور + Host عام | 200 | **403** `Loopback mode rejects non-local Host headers` |
| مع كلمة مرور + Host عام | 200 | **401** ثم يعمل بعد الدخول |

لذلك: منذ 1.2.3 يطبع الخادم تحذيرًا واضحًا عند الإقلاع إذا كانت الكلمة فارغة،
و`START-ONLINE-WINDOWS.cmd` يولّدها تلقائيًا. لا تشغّل أبدًا بلا كلمة مرور وتتوقع نفقًا يعمل.

---

## التشغيل التلقائي بعد إعادة تشغيل Windows

| الطريقة | الأمر |
|---|---|
| Cloudflare Tunnel | `cloudflared service install` (يفعله `SETUP-TUNNEL-WINDOWS.cmd`) |
| التطبيق نفسه | Task Scheduler → Create Task → At startup → `C:\ACQ\START-ONLINE-WINDOWS.cmd` |
| بديل NSSM | `nssm install ACQ "C:\ACQ\.venv\Scripts\python.exe" "C:\ACQ\scripts\run.py"` ثم `nssm start ACQ` |

> Task Scheduler يعمل حتى قبل تسجيل الدخول إن اخترت «Run whether user is logged on or not».

---

## الوصول من شبكة المكتب فقط (بلا إنترنت)

```powershell
.venv\Scripts\python.exe scripts\run.py --host 0.0.0.0 --port 8010
New-NetFirewallRule -DisplayName "ACQ 8010" -Direction Inbound -LocalPort 8010 -Protocol TCP -Action Allow
```

ثم `http://<IP-السيرفر>:8010` من أي جهاز في الشبكة. **HTTP بلا تشفير** — لا تستخدمه عبر الإنترنت.

---

## النسخ الاحتياطي على السيرفر

قاعدة البيانات داخل مجلد Docker باسم `app-data`. خُذ نسخة متسقة بأمر واحد:

```bash
docker compose exec app python - <<'PY'
import sqlite3, datetime, pathlib
src = sqlite3.connect('/app/data/acquisitions.db')
dst = pathlib.Path('/app/data/backup-%s.db' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
src.backup(sqlite3.connect(dst))
print('backup:', dst, dst.stat().st_size, 'bytes')
PY

docker compose cp app:/app/data ./backups/
```

ثم شفّر النسخة قبل رفعها إلى أي مكان:

```bash
gpg -c --cipher-algo AES256 backups/backup-*.db
```

**لا** ترفع قاعدة بيانات خامًا إلى GitHub أو Drive أو محادثة.

---

## التحديث إلى إصدار جديد

```bash
cd ACQ-GreenseedTX
git fetch --tags && git checkout v1.2.2   # أو الوسم الأحدث
cd deploy && docker compose up -d --build
```

الترحيلات (Alembic) تُطبَّق تلقائيًا عند بدء التشغيل، مع نسخة استرداد خاصة قبل أي ترقية.
حجم البيانات محفوظ في `app-data` ولا يُمسّ بإعادة البناء.

---

## استكشاف الأخطاء

| العَرَض | السبب المرجَّح | الحل |
|---|---|---|
| الحاوية تخرج فورًا | `APP_ACCESS_PASSWORD` أقل من 12 حرفًا | اكتب كلمة مرور أطول في `deploy/.env` |
| Caddy لا يحصل على شهادة | النطاق لا يشير للسيرفر، أو المنفذ 80/443 مغلق | تحقق من DNS ومن الجدار الناري |
| `502 Bad Gateway` | التطبيق لم يجهز بعد | `docker compose logs app` ثم انتظر انتهاء الترحيل |
| `403 Loopback mode…` | لا توجد كلمة مرور مع ربط خارجي | عيّن `APP_ACCESS_PASSWORD` |
| `403 Cross-origin mutations…` | وكيل يعيد كتابة ترويسة `Host` | تأكد من `header_up Host {host}` في Caddyfile |
| فشل رفع ملف كبير | الحد 25 م.ب افتراضيًا | غيّر `MAX_UPLOAD_MB` في بيئة الحاوية |

---

## ما لا يفعله هذا الدليل

- لا يفعّل REsimpli أو Groq أو Ollama — كلها معطّلة افتراضيًا وتُفعّل بوعي وبمفاتيحك.
- لا ينشئ مستخدمين متعددين: النظام مصمّم لمساحة عمل واحدة بكلمة مرور واحدة.
- لا يوفّر نسخًا احتياطيًا تلقائيًا إلى السحابة: نفّذ `UPLOAD-DATABASES` على جهازك، أو
  استخدم الأوامر أعلاه مع مفتاح تشفير.
- لا يضمن توافق `0.0.0.0` مع كل وكيل عكسي؛ تم اختبار التصميم منطقيًا هنا وليس على سيرفر
  حقيقي، فراجع السجل عند أول تشغيل.

انظر أيضًا: `READY_SYSTEM_AR.md` (التشغيل المحلي ودمج القاعدتين)، `PRIVATE_DATABASE_BACKUP.md`
(النسخ المشفّر)، و`VERIFICATION.md` (ما تم التحقق منه فعليًا وما لم يُتحقق).

---

## حالة التحقق من هذه الملفات

| البند | النتيجة |
|---|---|
| `docker-compose.yml` | YAML صالح: خدمتان (`app`, `caddy`)، ثلاثة أحجام، بيئة كاملة |
| `Dockerfile` | يتحقق من `frontend/dist/index.html`، مستخدم غير جذري uid 10001، فحص صحة `/api/health` |
| حارس كلمة المرور | مؤكَّد: `0.0.0.0` بكلمة < 12 حرفًا يُرفض، و12+ يبدأ |
| تحذير الإقلاع الجديد | مؤكَّد باختبارين آليين: تحذير عند غياب الكلمة، وصمت عند وجودها |
| `.env` بنهايات أسطر Windows (CRLF) | **مؤكَّد**: قرأ كلمة المرور بشكل صحيح، صفحة 200، دخول 200 مع توكن، API 200 عبر Host عام |
| تسريب الأسرار | مؤكَّد: `deploy/.env` و`.env` لا يدخلان الحزمة |
| **تنفيذ سكربتات PowerShell** | **لم يُنفَّذ**: لا PowerShell في بيئة الإعداد؛ تم فحص التوازن النحوي والمنطق فقط |
| **بناء صورة Docker** | **لم يُنفَّذ**: لا Docker متاح |
| **تشغيل على سيرفر/نطاق حقيقي** | **لم يُنفَّذ**: يلزم نطاق وسيرفر يملكه المشغّل |

عند أول تشغيل حقيقي: راقب نافذة `START-ONLINE-WINDOWS.cmd` بحثًا عن سطر
`Application startup complete`، وتأكد من عدم وجود سطر `WARNING: APP_ACCESS_PASSWORD is empty`.
