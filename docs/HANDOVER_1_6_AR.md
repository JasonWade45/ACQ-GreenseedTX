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

**تنبيه:** Render قد يطلب كارتًا لبعض الحسابات. البديل الموصى به الآن: **Hugging Face Spaces + Neon** (بلا كارت) — `deploy/huggingface/PUBLISH_AR.md`. مسار Render مذكور كبديل.

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

---

## تحديث 2026-10-30 (بعد النشر)

### ترحيل البيانات القديمة
تم ترحيل قاعدة `acquisition-crm-hub` إلى نفس مخطط التطبيق ثم إلى Neon:

| العنصر | العدد |
|---|---|
| Leads | **852** |
| Properties | 818 |
| Phones | 851 |
| Follow-ups | 1,505 |
| Checklist items | 10,224 |
| Stage history | 1,704 |
| Tags | 1 |

السكربت: `scripts/migrate_hub_to_unified.py` (dry-run افتراضيًا، idempotent). القاعدة القديمة لم تُعدّل.

### AI Mapping + سكربت + CRM
- **Import Center → Suggest mapping**: يقرأ الهيدرز و5 صفوف، ويستخدم Groq (`openai/gpt-oss-20b`) مع fallback للقواعد المحلية. لا يكتب أي شيء.
- **Lead profile → Call script**: سكربت 5 خطوات + اعتراضات من بيانات الليد فقط، مع Save as note ونسخ.
- **Preview CRM push**: يعرض body الذي سيُرسل، ويقبل نص السكربت كـ `comment` عند إنشاء الليد.
- **CRM**: REsimpli API key + adapter + account defaults مضبوطة، و`CRM_WRITES_ENABLED=true`. الوضع `review` ويطلب كتابة `PUSH TO CRM`.
- الليدز القديمة موجودة أصلًا في REsimpli؛ الـ preview سيقول `exists_in_crm` ويقترح Link بدل إنشاء نسخة ثانية. لا تعمل Batch push للـ 852.

### تنبيه أمني
كلمة سر Neon القديمة ظهرت في الشات. اعمل Reset من Neon → Roles → `neondb_owner`، وحدّث `DATABASE_URL` في HF Space → Settings → Variables and secrets.

### Lead brief (2026-10-30)
كل ليد — قديم أو جديد — له Brief في Notes:
- ملخص سريع (النوع، equity، priority، الحالة).
- خمسة أسئلة Lead Manager: motivation، asking price، condition، closing timeline، هل المالك الوحيد على الـ deed.
- Playbook حسب النوع: Code Violation، Foreclosure، Inheritance/Probate، Tax Lien، Divorce، Lis Pendens، Tax Deed، HOA Lien، General.
- الـ Brief بيتحط كـ `comment` عند إنشاء ليد جديد في REsimpli. الليدز اللي اتعملت قبل التحديث مينفعش يتضاف لها note من API (v6 ماعندهوش note endpoint)، لكن الـ brief موجود في تبويب Notes داخل التطبيق.
- تم عمل backfill لـ 1,226 ليد.

### CRM activity notes (2026-10-30)
REsimpli أضاف `POST /activity/add` في تحديث 28 أكتوبر. تم استخدامه لإضافة الـ Brief كـ Activity على كل ليد موجود:
- 1,221 ليد اتصاف لهم Activity بالـ Brief.
- 5 ليدز لم يتم إرسالها: 4 بدون رقم هاتف + 1 ليد تجريبي محلي.
- السكربت: `scripts/add_lead_brief_activities.py` (idempotent، workers، يتوقف ويعيد المحاولة عند rate limit).
- الليدز الجديدة: الـ Brief يروح كـ comment عند الإنشاء، ويمكن إضافة Activity بنفس الطريقة لو مطلوب.
