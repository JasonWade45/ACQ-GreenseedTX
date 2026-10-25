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

## تشغيله على سيرفر Windows (بدون Docker)

1. ثبّت Python 3.11+ وأضفه إلى `PATH`.
2. فك ضغط الحزمة `ACQ-GreenseedTX-v1.2.2.zip`.
3. أنشئ `.env` بجانب المشروع بالمحتوى التالي:

```ini
APP_HOST=127.0.0.1
APP_PORT=8000
APP_ACCESS_PASSWORD=كلمة-مرور-طويلة
SESSION_SECRET=سلسلة-عشوائية-64-حرفًا
APP_TIMEZONE=Africa/Cairo
```

4. شغّل `START-WINDOWS.cmd` — يعمل على `127.0.0.1` فقط (غير مكشوف للإنترنت).
5. للنشر الخارجي استخدم **نفقًا موثوقًا** (Cloudflare Tunnel أو Tailscale Funnel) بدل فتح
   المنفذ مباشرة. هذا هو الخيار الذي يوصي به المشروع: TLS + مصادقة بدون كشف IP السيرفر.

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
| `deploy/docker-compose.yml` | YAML صالح: خدمتان (`app`, `caddy`)، ثلاثة أحجام، بيئة التطبيق كاملة |
| `Dockerfile` | يتحقق من وجود `frontend/dist/index.html`، يعمل بمستخدم غير جذري (uid 10001)، فحص صحة على `/api/health` |
| حارس كلمة المرور | مؤكَّد: `0.0.0.0` بكلمة أقل من 12 حرفًا يُرفض، و12+ حرفًا يبدأ بنجاح |
| تسريب الأسرار | مؤكَّد: `deploy/.env` لا يدخل حزمة الإصدار، و`compose.env.example` يدخل |
| `deploy/Caddyfile` | HTTPS تلقائي، يمرّر `Host` الأصلي ليبقى فحص الكتابة عبر الأصل فعّالًا |
| **بناء الصورة نفسها** | **لم يُنفَّذ**: لا يوجد Docker في بيئة الإعداد ولا وصول لمزوّدي الاستضافة |
| التشغيل على سيرفر حقيقي | **لم يُنفَّذ**: يلزم نطاق وسيرفر تملكه |

أول من يشغّل هذا على سيرفره: راقب `docker compose logs -f app` أثناء أول إقلاع للتأكد من
اكتمال الترحيلات، ثم `docker compose logs caddy` للتأكد من إصدار الشهادة.
