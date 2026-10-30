# النشر على Hugging Face Spaces — مجاني وبدون كارت

**البديل المعتمد بعد ما Render طلب كارت.** Hugging Face Spaces يشغّل Docker مجانًا
(CPU Basic: 2 vCPU / 16 GB)، بلا كارت، والبيانات تبقى في Neon.

> **أول حاجة — أمان:** رابط Neon اللي فيه كلمة السر اتكتب في الشات، فاعتبره مكشوفًا.
> من Neon Console → المشروع → **Roles** → `neondb_owner` → **Reset password**،
> وبعدها حدّث `DATABASE_URL` في أي منصة استخدمتها. لا تضع الرابط في الشات مرة تانية.

---

## ١) أنشئ Space

1. [huggingface.co/join](https://huggingface.co/join) — حساب بالإيميل أو GitHub، بلا كارت.
2. بعد الدخول: **+ New → New Space**.
3. املأ:
   - **Owner:** اسم حسابك.
   - **Space name:** `acq-assistant` (أو أي اسم).
   - **License:** MIT.
   - **Select the Space SDK:** **Docker** → **Blank**.
   - **Space hardware:** `CPU basic · 2 vCPU · 16 GB · FREE`.
   - **Make this Space public:** نعم (الـ private يحتاج PRO مدفوع).
4. **Create Space**.

## ٢) ارفع الكود

من جهازك، داخل مجلد المشروع:

```powershell
cd C:\Users\ATG\ACQ\_review\ACQ-GreenseedTX
pwsh -File deploy\huggingface\publish.ps1 `
  -SpaceUrl https://huggingface.co/spaces/<اسم-حسابك>/acq-assistant
```

- أول مرة هيطلب منك **username** = اسم حساب HF، و**password** = توكن من
  [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) بصلاحية **write**.
- السكربت بيصدّر الملفات المسجّلة في git فقط (مش `.env` ولا `data/`)، ويستبدل
  `README.md` بملف إعداد الـ Space، ثم يعمل push.
- راقب تبويب **Logs** في الـ Space؛ البناء بياخد 3–6 دقايق.

## ٣) اضبط الأسرار (Secrets)

من صفحة الـ Space → **Settings → Variables and secrets**. استخدم **Secrets** للحساس،
و**Variables** للعادي:

| الاسم | النوع | القيمة |
|---|---|---|
| `APP_ACCESS_PASSWORD` | Secret | كلمة مرور قوية 12+ حرف |
| `DATABASE_URL` | Secret | رابط Neon كامل مع `?sslmode=require` |
| `SESSION_SECRET` | Secret | نص عشوائي طويل |
| `APP_TIMEZONE` | Variable | `Africa/Cairo` |
| `PORT` | Variable | `7860` |
| `RESIMPLI_MODE` | Variable | `disabled` |
| `SYNC_ENABLED` | Variable | `false` |
| `CRM_WRITES_ENABLED` | Variable | `false` |
| `GROQ_ENABLED` | Variable | `false` |

بعد الحفظ الـ Space يعيد التشغيل تلقائيًا.

## ٤) افتح التطبيق

- الصفحة: `https://huggingface.co/spaces/<user>/<space>`
- رابط التطبيق: `https://<user>-<space>.hf.space`
- الصحة: `https://<user>-<space>.hf.space/api/health`

لازم تشوف:

```json
"database": "postgresql"
```

لو ظهر `sqlite`، يبقى `DATABASE_URL` مش متسجّل أو الرابط غلط. راجع Secrets وأعد التشغيل.

## ٥) حدود الخطة المجانية

- الـ Space **عام** والكود ظاهر؛ الدخول للتطبيق محمي بكلمة المرور.
- ينام بعد **48 ساعة** بدون زيارات (أفضل من Render)؛ أول طلب بعده 30–60 ثانية.
- القرص مؤقت، ولذلك قاعدة البيانات **لازم** تكون Neon — لا تعتمد على SQLite.
- لا يوجد دومين مخصص في الخطة المجانية؛ تقدر تضيفه لاحقًا (CNAME) لو حبيت.
- لا تضع مفاتيح REsimpli/Groq الحقيقية إلا بعد ضبط كلمة مرور قوية.

## لو البناء فشل

- **Logs** → آخر خطأ.
- تأكد إن `frontend/dist/index.html` موجود في الـ commit (السكربت يتحقق قبل الرفع).
- تأكد إن `Dockerfile` في جذر الـ Space (السكربت بينسخ المشروع كامل).
- لو `ModuleNotFoundError`: راجع `backend/requirements-lock.txt`.

## بديل سريع مؤقت (بدون أي حساب استضافة)

لو عايز لينك عام في دقيقة من جهازك:

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8010
```

هيديك رابط `https://xxx.trycloudflare.com` مجاني وبلا كارت، لكنه شغال فقط
طالما جهازك مفتوح والتطبيق شغال — مش استضافة دائمة.

## مراجع

- [Hugging Face Spaces — Docker](https://huggingface.co/docs/hub/spaces-sdks-docker)
- [خطة Spaces المجانية](https://huggingface.co/pricing)
- [Neon Free](https://neon.com/pricing)
