# PostgreSQL على Neon — دليل التشغيل الكامل

**الحالة: مُنفَّذ ومُختبَر محليًا على PostgreSQL 16.2، ولم يُختبر على حساب Neon حقيقي من
داخل بيئة التطوير.** كل خطوة أدناه مكتوبة لتُنفَّذ من جهازك، وكل رقم فيها مأخوذ من تشغيل
فعلي على قاعدة بيانات محلية. اقرأ قسم «ما لم يُختبر» في النهاية قبل الاعتماد عليه.

---

## 1) ما الذي تغيّر في الكود

| الأمر | قبل | بعد |
|---|---|---|
| `DATABASE_URL` | ملف SQLite فقط | SQLite أو PostgreSQL (`postgres://` عادي يُقبل ويُصحَّح تلقائيًا) |
| الترحيلات | تفشل على PostgreSQL عند أول عمود منطقي | `alembic upgrade head` يعمل على قاعدة فارغة |
| النسخ الاحتياطي | نسخ ملف SQLite | PostgreSQL: ملف `ndjson.gz` واحد لكل الجداول + بيان بعدد الصفوف |
| الجدولة | مؤقت داخل العملية فقط | `APP_SCHEDULER_ENABLED=false` + `POST /api/cron/run` بمفتاح `CRON_SECRET` |
| الواجهة | نفس النطاق فقط | `VITE_API_URL` + `CORS_ORIGINS` (قائمة صريحة، بلا `*`) |
| الخصوصية | — | لا كوكيز بين النطاقات؛ الجلسة تبقى في ترويسة `Authorization` |

---

## 2) إنشاء قاعدة البيانات على Neon

1. [neon.tech](https://neon.tech) → أنشئ مشروعًا في أقرب منطقة (لنا: `us-east-1` أو `eu-central-1`).
2. **Connection string** → انسخ رابط **Pooled connection** إن كان متاحًا.
3. أضف `?sslmode=require` في نهاية الرابط إن لم يكن موجودًا.
   التطبيق **يرفض** أي مضيف غير محلي بلا `sslmode=require` (أو `verify-ca`/`verify-full`)،
   لأن رفض الاتصال غير المشفّر أهم من نجاحه.
4. الرابط النهائي يبدو هكذا:

```
DATABASE_URL=postgresql://user:pass@ep-xxx-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require
```

> **لا تضع كلمة المرور في أي ملف يُرفع إلى المستودع.** ضعها في `.env` المحلي أو في
> متغيّرات البيئة عند مزوّد الاستضافة فقط.

---

## 3) الترحيل إلى القاعدة الجديدة

```bash
cd ACQ-GreenseedTX
source .venv/bin/activate

# 1. الجداول أولًا (لا يمسّ هذا ملف SQLite إطلاقًا)
DATABASE_URL="postgresql://…?sslmode=require" python scripts/manage.py migrate

# 2. معاينة فقط: كم صفًا سيُنسخ؟ لا يكتب شيئًا
DATABASE_URL="postgresql://…?sslmode=require" \
  python scripts/migrate_sqlite_to_postgres.py --dry-run

# 3. النسخ الفعلي
DATABASE_URL="postgresql://…?sslmode=require" \
  python scripts/migrate_sqlite_to_postgres.py --confirm "MIGRATE TO POSTGRES"
```

النتيجة المطبوعة جدول بكل جدول: `read / inserted / in target`. تحقّق من:
- لا يوجد سطر عليه `<-- check` (عدد الصفوف في الهدف أقل من المصدر).
- `inserted` في التشغيل الثاني = **0** (السكربت آمن للتكرار، يتخطّى الموجود بالمفتاح الأساسي).

### ما يفعله السكربت بالضبط

- يفتح ملف SQLite بـ `mode=ro`: **مستحيل** أن يكتب فيه، ولو فشل في المنتصف.
- يحوّل الأنواع: `0/1` ← `boolean`، نص ISO ← `timestamp` بتوقيت UTC، نص JSON ← `json`،
  النصوص الرقمية ← `numeric`. بدون هذا التحويل ترفض PostgreSQL الإدراج.
- **لا يكتب فوق صف موجود** (`ON CONFLICT DO NOTHING`)، ولا يحذف شيئًا أبدًا.
- يعيد ضبط كل تسلسل (`sequence`) بعد أعلى مُعرّف منسوخ. بدون هذه الخطوة يفشل أول إدراج
  جديد بتعارض في المفتاح — وهي علّة أُصلحت واختُبرت.

### التحقّق بعد النسخ

`manage.py check` مخصّص لملفات SQLite، وعلى PostgreSQL استخدم هذا الفحص المباشر:

```bash
DATABASE_URL="postgresql://…" python - <<'PY2'
import os, sys
sys.path.insert(0, "backend")
from sqlalchemy import text
from app.db import make_engine

engine = make_engine(os.environ["DATABASE_URL"])
with engine.connect() as c:
    print("revision:", c.execute(text("select version_num from alembic_version")).scalar())
    for table in ("leads", "activities", "messages", "templates"):
        print(f"{table:<12}", c.execute(text(f"select count(*) from {table}")).scalar())
PY2
```

الأرقام يجب أن تطابق ما طبعه سكربت النسخ في العمود `in target`.

---

## 4) تشغيل التطبيق على PostgreSQL

```env
DATABASE_URL=postgresql://…?sslmode=require
APP_ACCESS_PASSWORD=<12 حرفًا على الأقل>
SESSION_SECRET=<سلسلة عشوائية طويلة>
CRON_SECRET=<سلسلة عشوائية أخرى>
APP_SCHEDULER_ENABLED=false        # لأن المضيف المجاني يوقف العملية
EPHEMERAL_FILESYSTEM=true          # لأن قرص المضيف يُمحى
CORS_ORIGINS=https://your-app.vercel.app
```

- `GET /api/health` يفحص القاعدة فعليًا ويعيد **503** لو تعذّر الوصول، مع اسم نوع الخطأ
  فقط (لا رابط ولا كلمة مرور). هذا ما يجب أن يعتمد عليه فحص المنصّة.
- `POST /api/cron/run` مع الترويسة `X-Cron-Secret` يشغّل نفس مهمة الجدولة اليومية
  (تجهيز مسوّدات للمراجعة فقط — لا إرسال). إن كان `CRON_SECRET` فارغًا فالرابط يعيد 404
  كأنه غير موجود.

مثال من أي مجدول خارجي (cron-job.org أو GitHub Actions):

```bash
curl -fsS -X POST "https://your-api.onrender.com/api/cron/run" \
  -H "X-Cron-Secret: $CRON_SECRET"
```

---

## 5) الواجهة على Vercel

```
VITE_API_URL=https://your-api.onrender.com
```

- الواجهة تُبنى بهذا المتغيّر؛ إن كان فارغًا تستخدم نفس النطاق (سلوك التطبيق المكتبي).
- على الخادم أضف **نفس** النطاق في `CORS_ORIGINS`. القائمة صريحة: أي أصل غير مذكور
  يُرفض بـ 403، ولا يوجد `*` في أي إعداد.
- لا كوكيز بين النطاقات: الجلسة تُحفظ في `sessionStorage` وتُرسل كـ `Authorization`.
  لذلك `allow_credentials=false`، ولا حاجة إلى `SameSite=None`.
- إن كنت تخدم واجهة من نطاق آخر، عدّل ترويسة `Content-Security-Policy` في
  `backend/app/security.py` إن أضفت مصادر غير `self`.

---

## 6) النسخ الاحتياطي والاستعادة

- **تلقائي**: كل ليلة (أو عبر `/api/cron/run`) يُكتب ملف
  `acquisitions-<UTC>-scheduled.ndjson.gz` داخل `BACKUP_DIR`، وبعده يُعاد قراءته
  وتُقارن أعداد الصفوف بالبيان. لا يُسمّى الملف إلا بعد نجاح التحقّق.
- **يدوي**: زر **Create a backup now**، ثم **Download** لتنزيله إلى جهازك.
  على مضيف يُمحى قرصه، زر التنزيل هو النسخة الباقية — والواجهة تقول ذلك صراحةً.
- **مجلد ثانٍ** (Google Drive مثلًا): إن كان `EPHEMERAL_FILESYSTEM=true` يرفض النظام
  النسخ إليه ويعيد السبب، لأن النسخة ستُمحى.
- **الاستعادة**:

```bash
python scripts/manage.py restore-postgres --file acquisitions-….ndjson.gz \
  --confirm "RESTORE POSTGRES DATABASE"
```

يحفظ السكربت نسخة من الوضع الحالي أولًا، ثم يحذف بترتيب معاكس للتبعية ويُدرج بنفس
الترتيب، ثم يضبط التسلسلات. أو استخدم **Point-in-time restore** من لوحة Neon نفسها.

---

## 7) الخصوصية

- لا إرسال رسائل ولا مكالمات ولا اتصال بأي بائع: المسوّدات للمراجعة والنسخ فقط.
- `messages.sent_at` حُذف من المخطط نهائيًا.
- القاعدة تحتوي بيانات عملاء: لا تضع نسخة احتياطية في مستودع عام أو قرص مشترك.

---

## 8) ما لم يُختبر

- **حساب Neon حقيقي**: لم يُتاح من بيئة التطوير. كل ما سبق اختُبر على PostgreSQL 16.2
  محليًا (ترحيل على قاعدة فارغة، نسخ 29 جدولًا، نسخ احتياطي/استعادة كاملان، إعادة
  التسلسل، تصفية JSON).
- **مجمّع اتصالات Neon**: إعدادات المجمّع (pool_size=5, recycle=300) مضبوطة للخطط
  المجانية المحدودة، لكن لم تُجرَّب تحت حمل حقيقي.
- **Vercel فعليًا**: سياسة CORS و`VITE_API_URL` مختبرتان آليًا في `backend/tests/test_postgres.py`،
  ولم تُجرَّب من نطاق Vercel منشور.
