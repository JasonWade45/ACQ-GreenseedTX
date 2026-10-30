# تسليم الإصدار 1.6.0 — ملخص عربي

**التاريخ:** 2026-10-30  
**الفرع المحلي:** `merge/acquisition-os-1.6` (commit `f09bda3`) فوق `main` عند `71a8b96`  
**الإصدار:** 1.6.0 — قاعدة البيانات عند `k3l4m5n6o7p8`

## ما تم إضافته

| الميزة | أين تجدها |
|---|---|
| تسجيل المكالمات ونتائجها + المتابعة التلقائية | تبويب **Calls** داخل ملف الليد |
| سكربت مكالمة مباشر (5 خطوات + اعتراضات) بدون أي استدعاء AI | زر **Live call script** في تبويب Calls |
| Tags محلية | لوحة **Tags** في نظرة عامة على الليد |
| قواعد توزيع حسب الولاية/المدينة + Fallback | صفحة **Assignments** |
| محرك أتمتة (Stale / Warm / Dead) + سجل تنفيذ | صفحة **Automation** |
| دفع الليد إلى REsimpli (إنشاء واحد فقط) | صفحة **CRM & AI** → Push Queue |

## التشغيل المحلي (بدون Docker)

```powershell
# من مجلد المشروع
.\START-ACQ.cmd
# أو
.\.venv\Scripts\python.exe scripts\run.py --port 8010
```

ثم افتح `http://127.0.0.1:8010`. المتصفح على نفس الجهاز أو أي جهاز على نفس الشبكة (مع `APP_ACCESS_PASSWORD` قوي).

## أونلاين مجانًا وبدون كارت بنكي

المسار الموصى به: **Render Free + Neon Free** (كلاهما لا يطلب كارتًا).

1. ارفع الفرع `merge/acquisition-os-1.6` إلى GitHub ثم ادمجه في `main` (أو ادفع `main` مباشرة).
2. Neon: أنشئ حسابًا بـ GitHub → مشروعًا → انسخ connection string وأضف `?sslmode=require`.
3. Render: **New → Blueprint** → اختر المستودع → **Blueprint file path**: `render-free.yaml`.
4. اكتب `APP_ACCESS_PASSWORD` (12 حرفًا على الأقل) → Apply.
5. بعد أول نشر: Render → Environment → عدّل `DATABASE_URL` إلى رابط Neon.
6. افتح `/api/health`؛ يجب أن يظهر `"database": "postgresql"`.

التفاصيل الكاملة: `docs/FREE_HOSTING_AR.md`.

**ملاحظات:**
- Render Free ينام بعد ~15 دقيقة خمول؛ أول زيارة بعده 30–60 ثانية.
- لا تستخدم Render Free Postgres (ينتهي بعد 30 يومًا)؛ استخدم Neon.
- لا تضع مفاتيح حقيقية على رابط عام قبل ضبط كلمة مرور قوية.
- `CRM_WRITES_ENABLED=false` يبقى افتراضيًا؛ لا تفتحه إلا بعد تجربة Preview ودفعة واحدة متعمدة.

## ما تم التحقق منه

- **559 اختبار backend** (0 فشل، 29 skipped).
- **49 اختبار frontend**.
- `ruff`, `tsc -b`, `vite build` نظيفة.
- تشغيل محلي فعلي على قاعدة مؤقتة: migrations، login، Calls، Tags، Script، Assignment، Automation، `/api/health`، والواجهة + أصول JS.
- فحص متصفح Chromium (headless) للشاشات الجديدة: لا أخطاء console أو صفحة.
- لقطات: `docs/screenshots/merged/`.

## ما لم يُتحقق منه هنا

- إنشاء خدمة Render/Neon فعليًا (يحتاج حسابك).
- بناء صورة Docker محليًا (Docker daemon لم يكن يعمل على جهازك) — Render يبنيها عن بُعد.
- بناء مثبّت Windows `ACQ-Setup-1.6.0.exe` (يُبنى في GitHub Actions).
- حساب REsimpli/Groq حقيقي؛ الاختبارات بمحاكاة.
- تشغيل 20 اختبار متصفح الخاص بـ CI (لم أُعد تشغيله هنا).

## الخطوة التالية

1. راجع الفرق: `git -C C:\Users\ATG\ACQ\_review\ACQ-GreenseedTX log --oneline -2`.
2. ارفع الفرع/ادمجه.
3. انشر Render + Neon بالخطوات أعلاه.
4. سجّل مكالمة حقيقية واحدة، ثم جرّب Preview للـ CRM (بدون Push) قبل أي دفعة.
