# ويندوز — أدوات مؤرشفة (غير مدعومة)

**لا تستخدم هذا المجلد للنشر.** النشر صار على Linux فقط: `deploy/install.sh` أو
`render.yaml` / `render-free.yaml`. القرار موثّق في `docs/DEPLOY_SERVER_AR.md`.

## ما الذي يعمل على ويندوز الآن؟

ملف واحد فقط: **`START-ACQ.cmd`** في جذر المشروع. يشغّل النظام على جهازك، ويعطيك
لينك تفتحه من الموبايل أو أي جهاز على نفس الشبكة. الشرح في `docs/DESKTOP_LAN_AR.md`.

## ما الموجود هنا؟

| الملف | كان يفعل |
|---|---|
| `START-WINDOWS.cmd` | تشغيل محلي على `127.0.0.1:8010` — استُبدل بـ`START-ACQ.cmd` |
| `START-ONLINE-WINDOWS.cmd` + `SETUP-TUNNEL-WINDOWS.cmd` | نشر عبر نفق Cloudflare من جهاز ويندوز — **مرفوض** |
| `UPDATE-WINDOWS.*` | تحديث نسخة قديمة مع الحفاظ على البيانات |
| `MERGE-WORKSPACES.*` | دمج قاعدتي العمل القديمتين مع مراجعة يدوية |
| `UPLOAD-DATABASES.*` / `RESTORE-DATABASES.*` | نسخ احتياطي مشفّر إلى مستودع خاص |
| `scripts/*.ps1` | السكربتات التي تستدعيها الملفات أعلاه |

## لو احتجت أداة منها فعلًا

هذه الملفات تفترض أنها في **جذر المشروع**. انسخها من هنا إلى الجذر ثم شغّلها:

```powershell
Copy-Item .\legacy\windows\*.ps1, .\legacy\windows\*.cmd . -Force
Copy-Item .\legacy\windows\scripts\*.ps1 .\scripts\ -Force
```

لم تُختبر أي أداة من هذه على ويندوز حقيقي في بيئة البناء، وهي غير مدعومة: لا تُصلح
ولا تُحدَّث. النسخ الاحتياطي صار تلقائيًا داخل النظام (Settings → Runtime & backups)،
وهو الطريق الموصى به بدلًا من `UPLOAD-DATABASES`.
