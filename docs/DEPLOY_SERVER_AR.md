# نشر النظام على سيرفر Linux (أونلاين)

**آخر تحديث: 25 أكتوبر 2026 — الإصدار 1.2.4.** يغطي هذا الدليل ثلاث طرق للنشر على Linux،
مرتّبة من الأسهل إلى الأكثر تحكّمًا. لا يوجد أي اعتماد على Windows.

> **قبل أي شيء — تحذير أمني:** النظام يحمل بيانات عملاء الشركة. النشر على الإنترنت يعني
> نقل بيانات حقيقية إلى مزوّد خارجي. لا تنشر بيانات حقيقية إلا بعد: موافقة صاحب البيانات،
> HTTPS فعّال، كلمة مرور 20+ حرفًا، ونسخة احتياطية مشفّرة (`UPLOAD-DATABASES`).
> للاستخدام المحلي فقط شغّل `scripts/run.py` على الجهاز نفسه ولا تنشر.

---

## اختر مسارك

| المسار | الأفضل لمن | الوقت | HTTPS | قاعدة بيانات دائمة |
|---|---|---|---|---|
| **أ) Render Blueprint** | لا يريد إدارة سيرفر | ~5 دقائق | ✅ تلقائي | يحتاج خطة مدفوعة |
| **ب) VPS بأمر واحد** | يريد التحكم والبيانات على سيرفره | ~5 دقائق | ✅ تلقائي (Caddy) | ✅ نعم |
| **ج) Linux بدون Docker** | سيرفر قديم / سياسة تمنع Docker | ~15 دقيقة | يدوي (Caddy) | ✅ نعم |

---

# المسار أ — Render بضغطة واحدة

1. ادخل [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
2. اختر مستودع `JasonWade45/ACQ-GreenseedTX`. سيقرأ `render.yaml` الموجود في الجذر.
3. عند الطلب، أدخل **`APP_ACCESS_PASSWORD`** (12 حرفًا على الأقل، والأفضل 30).
   `SESSION_SECRET` يُولَّد تلقائيًا.
4. اضغط **Apply** وانتظر انتهاء البناء.

**مهم جدًا:** قاعدة SQLite تحتاج قرصًا دائمًا. Render يوفّر الأقراص على الخطط المدفوعة فقط.
على الخطة المجانية يُمحى نظام الملفات مع كل نشر أو إعادة تشغيل — أي **تضيع البيانات**.
إن أردت الحفظ الدائم فاستخدم `plan: starter` (المضبوط في `render.yaml`) أو المسار ب.

التحقق:
```bash
curl -s https://<اسم-الخدمة>.onrender.com/api/health
```

---

# المسار ب — VPS بأمر واحد (موصى به)

سيرفر Ubuntu 22.04/24.04 أو Debian 12، ذاكرة 2 GB، ونطاق يشير إليه (سجل `A`).

```bash
curl -fsSL https://raw.githubusercontent.com/JasonWade45/ACQ-GreenseedTX/main/deploy/install.sh \
  | sudo bash -s -- --domain acq.example.com
```

ماذا يفعل السكربت:
1. يثبّت Docker من المصدر الرسمي إن لم يكن موجودًا.
2. يستنسخ المستودع في `/opt/acq` (أو يحدّثه إن كان موجودًا).
3. يولّد كلمة مرور عشوائية + `SESSION_SECRET` ويكتب `deploy/.env` بأذون **600**.
4. يطبع كلمة المرور **مرة واحدة** — احفظها فورًا.
5. يفتح 80/443 في `ufw` إن كان مفعّلًا.
6. يبني ويشغّل الحاويتين (التطبيق + Caddy) وينتظر `/api/health`.

خيارات:

```bash
sudo ./deploy/install.sh --help
sudo ./deploy/install.sh --domain acq.example.com --dry-run    # معاينة بلا أي تغيير
sudo ./deploy/install.sh --domain acq.example.com --timezone Africa/Cairo --force
```

- إعادة التشغيل آمنة: `.env` الموجود بكلمة مرور صالحة **لا يُستبدل**، و`--force` وحده يدوّرها.
- `--dry-run` يعرض كل خطوة دون تنفيذ — مُختبَر ويعمل.

التحقق:
```bash
curl -s https://acq.example.com/api/health
```

---

# المسار ج — Linux بدون Docker (systemd)

```bash
# 1) مستخدم ومسارات
sudo useradd --system --home /opt/acq --shell /usr/sbin/nologin acq
sudo git clone --depth 1 https://github.com/JasonWade45/ACQ-GreenseedTX.git /opt/acq
cd /opt/acq
sudo mkdir -p /var/lib/acq /etc/acq
sudo chown -R acq:acq /opt/acq /var/lib/acq

# 2) بيئة Python
sudo python3 -m venv /opt/acq/.venv
sudo /opt/acq/.venv/bin/pip install -r /opt/acq/backend/requirements-lock.txt

# 3) الإعدادات
sudo cp deploy/acq.env.example /etc/acq/acq.env
python3 -c "import secrets; print(secrets.token_hex(32))"   # ضع الناتج في SESSION_SECRET
sudo nano /etc/acq/acq.env                                   # كلمة مرور 12+ حرفًا
sudo chown root:acq /etc/acq/acq.env && sudo chmod 640 /etc/acq/acq.env

# 4) الخدمة
sudo cp deploy/acq.service /etc/systemd/system/acq.service
sudo systemctl daemon-reload
sudo systemctl enable --now acq
systemctl status acq --no-pager
```

الخدمة مقيّدة الأمان (`ProtectSystem=strict`، `NoNewPrivileges`، مستخدم غير جذري) وتكتب في
`/var/lib/acq` فقط. القاعدة خارج مجلد الشيفرة، فـ`git pull` لا يمسّها أبدًا.

**ثم ضع HTTPS في المقدمة:**

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
acq.example.com {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000; includeSubDomains"
    reverse_proxy 127.0.0.1:8000 {
        header_up Host {host}
    }
}
EOF
sudo systemctl reload caddy
```

> `header_up Host {host}` ضروري: التطبيق يرفض طلبات الكتابة القادمة من أصل مختلف، فلو
> أعاد الوكيل كتابة `Host` إلى `127.0.0.1` فستفشل العمليات بالرمز 403.

---

## ⚠️ الفخ الذي يوقع الجميع: صفحة تفتح وبيانات لا تعمل

بلا `APP_ACCESS_PASSWORD` يعمل النظام في **وضع loopback**، فيرفض كل طلب `/api` يحمل `Host`
غير محلي برمز **403**، بينما الصفحة تُخدم بنجاح.

| الإعداد | الصفحة `/` | `/api/leads` |
|---|---|---|
| بلا كلمة مرور + Host عام | 200 | **403** `Loopback mode rejects non-local Host headers` |
| مع كلمة مرور + Host عام | 200 | 401 ثم يعمل بعد الدخول |

منذ 1.2.3 يطبع الخادم تحذيرًا واضحًا عند الإقلاع إذا كانت الكلمة فارغة، وحاوية Docker
تفشل عند البدء برسالة `FATAL` بدل قبول الاتصالات ثم رفضها.

---

## القاعدة والنسخ الاحتياطي

| المسار | مكان قاعدة البيانات |
|---|---|
| أ) Render | قرص دائم على `/app/data` (خطة مدفوعة) |
| ب) VPS/Docker | حجم Docker باسم `acq-assistant_app-data` |
| ج) systemd | `/var/lib/acq/acquisitions.db` |

نسخة متسّقة بأمر واحد (Docker):

```bash
cd /opt/acq/deploy
docker compose exec -T app python -c "
import sqlite3
src = sqlite3.connect('/app/data/acquisitions.db')
src.backup(sqlite3.connect('/app/data/backup.db'))
print('backup written')"
docker compose cp app:/app/data/backup.db ./backup-$(date +%F).db
gpg -c --cipher-algo AES256 ./backup-$(date +%F).db     # شفّرها قبل نقلها
```

**لا** ترفع قاعدة بيانات خامًا إلى GitHub أو Drive أو محادثة.

## التحديث

```bash
# Docker / VPS
cd /opt/acq && sudo git pull && cd deploy && sudo docker compose up -d --build

# systemd
cd /opt/acq && sudo git pull && sudo /opt/acq/.venv/bin/pip install -r backend/requirements-lock.txt
sudo systemctl restart acq
```

الترحيلات (Alembic) تُطبَّق تلقائيًا عند الإقلاع، مع نسخة استرداد خاصة قبل أي ترقية.

---

## استكشاف الأخطاء

| العَرَض | السبب | الحل |
|---|---|---|
| الحاوية تخرج فورًا برسالة `FATAL` | `APP_ACCESS_PASSWORD` فارغة أو أقصر من 12 | اضبطها في اللوحة أو `.env` |
| Caddy لا يحصل على شهادة | DNS لا يشير للسيرفر أو 80/443 مغلق | تحقّق من `dig` والجدار الناري |
| `502 Bad Gateway` | التطبيق لم يجهز بعد | `docker compose logs -f app` |
| `403 Loopback mode…` | لا توجد كلمة مرور مع ربط خارجي | اضبط كلمة المرور وأعد التشغيل |
| `403 Cross-origin mutations…` | الوكيل يعيد كتابة `Host` | أضف `header_up Host {host}` |
| البيانات تختفي بعد النشر | لا يوجد قرص دائم (Render مجاني) | استخدم خطة مدفوعة أو VPS |
| فشل رفع ملف كبير | الحد 25 م.ب | غيّر `MAX_UPLOAD_MB` |

---

## حالة التحقق من هذه الملفات

| البند | النتيجة |
|---|---|
| `deploy/install.sh` | `bash -n` نظيف؛ `--dry-run` يعمل ويطبع كل خطوة؛ منطق `.env` مُختبَر: توليد، حفظ كلمة المرور عند إعادة التشغيل، تدويرها مع `--force`، إبقاء مفاتيح مخصصة، أذون 600 |
| `deploy/docker-entrypoint.sh` | `sh -n` نظيف؛ **شُغّل فعليًا**: احترم `$PORT=8100` وخدم على 8100 لا 8000، أنشأ القاعدة في `DATA_DIR` (20 جدولًا، رأس `0a6d91cf17b2`، `integrity ok`)، ورفض كلمة مرور فارغة/قصيرة بـ`FATAL` وخروج 1 |
| `render.yaml` | YAML صالح: خدمة `web`، `runtime: docker`، `healthCheckPath: /api/health`، قرص على `/app/data`، `APP_ACCESS_PASSWORD` معلَّم `sync: false`، `SESSION_SECRET` بـ`generateValue`، ولا أسرار حرفية فيه |
| `deploy/acq.service` | وحدة systemd مع تقييد صلاحيات؛ **لم تُشغَّل** (لا systemd في بيئة الإعداد) |
| `Dockerfile` | يبني واجهة مسبقة داخل الصورة؛ **بناء الصورة لم يُنفَّذ** (لا Docker هنا) |
| تشغيل على نطاق/سيرفر حقيقي | **لم يُنفَّذ**: يلزم نطاق وسيرفر يملكه المشغّل |
| REsimpli / Groq الحيّان وقاعدتا الشركة | **لم يُتحقق منها** كما في كل إصدار |

عند أول تشغيل حقيقي راقب السجلات بحثًا عن `Application startup complete` و`Uvicorn running`
وغياب `WARNING: APP_ACCESS_PASSWORD is empty`.

---

## ملحق: Windows (اختياري، غير موصى به)

النشر على Windows مدعوم عبر `START-ONLINE-WINDOWS.cmd` و`SETUP-TUNNEL-WINDOWS.cmd`
(Cloudflare Tunnel)، لكنه ليس المسار الموصى به لبيانات الإنتاج: لا يوجد عزل حاويات،
والنسخ الاحتياطي والتحديث يدويان. استخدمه فقط إن لم يتوفر سيرفر Linux.

انظر أيضًا: `READY_SYSTEM_AR.md` (التشغيل المحلي ودمج القاعدتين)،
`PRIVATE_DATABASE_BACKUP.md` (النسخ المشفّر)، و`VERIFICATION.md`.
