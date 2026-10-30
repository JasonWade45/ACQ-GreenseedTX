# النشر على Hugging Face Spaces — مجاني وبدون كارت (Gradio SDK)

**البديل المعتمد بعد ما Render طلب كارت، وبعد ما Docker Spaces ظهر عليها Paid في HF.**
Hugging Face ما زال يوفّر **Gradio Spaces** مجانًا (CPU Basic)، و`app.py` في المشروع
بيشغّل نفس FastAPI على المنفذ 7860 بدون أي واجهة Gradio. البيانات في Neon.

> **أول حاجة — أمان:** رابط Neon اللي فيه كلمة السر اتكتب في الشات، فاعتبره مكشوفًا.
> من Neon Console → المشروع → **Roles** → `neondb_owner` → **Reset password**،
> وبعدها حدّث `DATABASE_URL` في الـ Space. لا تضع الرابط في الشات مرة تانية.

---

## ١) أنشئ Space

1. [huggingface.co/join](https://huggingface.co/join) — حساب بالإيميل أو GitHub، بلا كارت.
2. بعد الدخول: **+ New → New Space**.
3. املأ:
   - **Owner:** `jasonwade`.
   - **Space name:** `acq-assistant`.
   - **License:** MIT.
   - **Select the Space SDK:** **Gradio** (مش Docker — الـ Docker عليه Paid).
   - **Gradio template:** **Blank**.
   - **Space hardware:** **CPU basic · 2 vCPU · 16 GB · FREE** (لو مختار ZeroGPU بدّل لـ CPU Basic).
   - **Storage Bucket:** None.
   - **Visibility:** **Public** (Protected/Private يحتاجون PRO).
4. **Create Space**.

## ٢) ارفع الكود

من جهازك:

```powershell
cd C:\Users\ATG\ACQ\_review\ACQ-GreenseedTX
pwsh -File deploy\huggingface\publish.ps1 `
  -SpaceUrl https://huggingface.co/spaces/jasonwade/acq-assistant
```

- أول مرة هيطلب **username:** `jasonwade` و**password:** توكن من
  [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) بصلاحية **write**.
- السكربت بيصدّر الملفات المسجّلة في git فقط (مش `.env` ولا `data/`)، ويستبدل
  `README.md` بإعداد الـ Space (`sdk: gradio`, `app_file: app.py`).
- الـ Space هيبني ويشغّل `app.py`، اللي بيشغّل FastAPI على `PORT=7860`.

## ٣) الأسرار (Secrets)

من **Settings → Variables and secrets**:

| الاسم | النوع | القيمة |
|---|---|---|
| `APP_ACCESS_PASSWORD` | Secret | كلمة مرور 12+ حرف |
| `DATABASE_URL` | Secret | رابط Neon الجديد مع `?sslmode=require` |
| `SESSION_SECRET` | Secret | نص عشوائي طويل |
| `APP_TIMEZONE` | Variable | `Africa/Cairo` |
| `PORT` | Variable | `7860` |
| `RESIMPLI_MODE` | Variable | `disabled` |
| `SYNC_ENABLED` | Variable | `false` |
| `CRM_WRITES_ENABLED` | Variable | `false` |
| `GROQ_ENABLED` | Variable | `false` |

لو Neon رفض الاتصال: شيل `channel_binding=require` وسيب `?sslmode=require` فقط.

## ٤) افتح التطبيق

- الصفحة: `https://huggingface.co/spaces/jasonwade/acq-assistant`
- التطبيق: `https://jasonwade-acq-assistant.hf.space`
- الصحة: `https://jasonwade-acq-assistant.hf.space/api/health`

لازم يظهر:

```json
"database": "postgresql"
```

## ٥) حدود الخطة

- Space **عام** والكود ظاهر؛ التطبيق محمي بكلمة المرور.
- ينام بعد **48 ساعة** بدون زيارات؛ أول طلب بعده ~30 ثانية.
- القرص مؤقت → قاعدة البيانات **لازم** Neon.
- لا دومين مخصص في الخطة المجانية.
- لا تضع مفاتيح REsimpli/Groq الحقيقية قبل ضبط كلمة مرور قوية.

## لو ظهرت مشكلة

- **Build failed:** تبويب Logs. تأكد إن `app.py` و`requirements.txt` في جذر الـ Space.
- **`ModuleNotFoundError`:** `requirements.txt` بيشير إلى `backend/requirements-lock.txt`؛
  تأكد إن المجلد مرفوع.
- **`APP_ACCESS_PASSWORD is required`:** أضف الـ Secret وأعد التشغيل.
- **`database: sqlite`:** `DATABASE_URL` مش متسجل أو الرابط غلط.

## بديل مؤقت بدون أي حساب

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8010
```

لينك `https://xxx.trycloudflare.com` مجاني وبلا كارت، شغال فقط طالما جهازك مفتوح.

## مراجع

- [Hugging Face Spaces — Gradio](https://huggingface.co/docs/hub/spaces-sdks-gradio)
- [خطة Spaces](https://huggingface.co/pricing)
- [Neon Free](https://neon.com/pricing)
