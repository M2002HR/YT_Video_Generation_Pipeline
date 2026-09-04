# HANDOFF — Question Harvest (برای ادامه از چت جدید)

> تاریخ: 2026-09-04 (سشن دوم) · branch: `ordak` · والد: `d6626b3` · ordak: `370a975`

---

## پرامپت شروع چت بعدی (کپی کن)

```
ادامه‌ی پیاده‌سازی Question Harvest در /opt/YT_Video_Generation_Pipeline (branch ordak).

اول این سه فایل را کامل بخوان:
1. HANDOFF.md             ← وضعیت فعلی، کارهای مانده، دستورات تأیید
2. IMPLEMENTATION_PLAN.md ← پلن ۴۷ تسک + §3.5 قرارداد ورکفلو + §10 ساختار UI فلو
3. mater_prompt.md        ← اسپک اصلی

CURRENT_STATE.md قدیمی است (2026-09-02) — به آن اعتماد نکن.

قواعد مطلق: تصویر=Gemini فقط، ویدیو=Google Flow فقط، متن=ChatGPT فقط (همه با Ordak)،
هیچ provider/model/synthetic fallback، هیچ style sheet به Flow، بدون پروکسی.
هر مرحله‌ای که prompt دارد از ChatGPT گرفته شود.

⚠️ بعد از هر تغییر در services/ordak/app باید `systemctl restart ordak-api` بزنی،
وگرنه جاب با کد قدیمی اجرا می‌شود (یک‌بار ۷ credit تلف شد).

از P8 (مستندات) شروع کن، بعد P7 (اجرای واقعی end-to-end با لاگین کاربر).
گیت را خودت مدیریت کن با پیام‌های کوتاه. سریع و کامل جلو برو.
```

---

## ۱) این سشن چه چیزی تمام شد

تست‌ها: **والد 181 pass** (از ۶۹) · **ordak 140 pass** (از ۹۲ pass + ۳ fail)

### ✅ P2 — Gemini سخت‌گیرانه: کامل (به‌جز اجرای واقعی مرورگر)

| تسک | چه شد |
|-----|-------|
| **T2.2 مسیر Nano Banana Pro** | ماژول جدید `services/ordak/app/automation/gemini_pro.py`: baseline نتیجه‌ها → یافتن کنترل Pro → invoke → **تمایز مثبت** (asset id جدید + SHA-256 محاسبه‌شده **داخل صفحه** با `crypto.subtle` روی بایت‌های fetch شده + dimension). نبودن کنترل یا نتیجه‌ی غیرمتمایز → `MODEL_NOT_AVAILABLE`. NB2 هرگز به‌عنوان Pro قبول نمی‌شود. |
| **T2.4 receipt واقعی** | `GenerationReceipt` حالا **validator** دارد: `model_verified=True` بدون `actual_model_label` رد می‌شود، و `pro_regeneration_used=True` بدون note ‏`pro_distinction=…` رد می‌شود. `_build_gemini_receipt` فقط از مشاهده می‌سازد (label + source از کنترل مدل، SHA از فایل). |
| **T2.5 validation دانلود §32** | ماژول جدید `image_validation.py` (بدون dependency: هدر PNG/JPEG/WebP/GIF را خودش پارس می‌کند + ffprobe به‌عنوان نظر دوم). رد: `missing_file, too_small, undecodable, dimension_too_small, aspect_mismatch, matches_uploaded_reference, duplicate_of_previous, stale_result`. |
| **T2.7 تست compositor** | `compose_book_spread.py` بازنویسی شد: **fallback مصنوعی کتاب حذف شد** (نبود template → `FileNotFoundError`)، متادیتا حالا `right_page_box` / `world_transform` / SHA هر دو منبع را ثبت می‌کند و تست اثبات می‌کند صفحه‌ی راست **بایت‌به‌بایت** همان `ImageOps.fit(world_keyframe, box)` است. تست «هیچ glyph رندر نمی‌شود» با monkeypatch روی `ImageDraw.text`. |
| گارد جدید | `runner.image()/video()` حالا `require_verified_image_model` / `require_verified_video_model` را صدا می‌زنند: receipt بدون `model_verified` → `FAILED_MODEL_SELECTION`؛ درخواست Pro بدون `pro_regeneration_used` → همان. |

### ✅ P6 — تست‌های واقعی: کامل

- `tests/test_model_lock.py` **بازنویسی شد** — تاتولوژی‌ها (`assert "720p" != "360p"`) حذف؛ حالا قرارداد `Generation` و گاردهای واقعی را تست می‌کند (۱۵ تست)
- `services/ordak/tests/test_flow_settings_verification.py` **جدید** — mock کامل composer فلو؛ کنترلی که عوض نمی‌شود → `MODEL_SELECTION_FAILED`، مدلی که UI ندارد → `MODEL_NOT_AVAILABLE`، ۷۲۰p روی مدل ۳۶۰p-only → `MODEL_FEATURE_INCOMPATIBLE` (۱۱ تست)
- `services/ordak/tests/test_flow_credit_safety.py` **جدید** — `_reconcile_pending` در همه‌ی حالت‌های restart؛ «نه نتیجه نه فایل» → `FLOW_RECONCILIATION_REQUIRED` نه Generate دوباره (۷ تست)
- `services/ordak/tests/test_gemini_pro_path.py` (۸) + `test_image_validation.py` (۱۱) + `test_generation_receipt_evidence.py` (۸) **جدید**
- `tests/test_integration_media.py` **جدید، §97** — ۱۰ سناریو با FFmpeg واقعی (image-only قدیمی، video+video+image، crop 9:16، **صدای کلیپ مبدأ هرگز map نمی‌شود**، subtitle on/off، mp4 خراب، کلیپ کوتاه‌تر از slot، asset گم‌شده)
- `tests/test_resume_stages.py` **جدید، §78/§102** — هر stage گران با کلاینت Ordak‌ای که روی هر تماس exception می‌دهد؛ بدون مصرف credit (۱۲ تست)
- `tests/test_provider_lock.py` — تست grep تاتولوژیک با **spy واقعی** جایگزین شد: شکست Gemini/Flow ثابت می‌کند provider دیگری صدا نشده
- `scripts/check_full_stack.py` **بازنویسی شد** — هیچ `True` هاردکدی نمانده: گارد style-sheet با **درخواست پذیرش یک style role و الزام رد شدن** تست می‌شود، لاگین provider حالا `logged_in is True` می‌خواهد، advisory از failure جدا شد، exit code معنادار (0/1/2)، فلگ `--skip-providers`
- دو تست شکسته‌ی ordak درست شد (`python` هاردکد → `sys.executable`؛ تست image_generate الان مدل و PNG واقعی می‌فرستد)

### ✅ P9 — پنل / تلگرام / منابع: کامل

| تسک | چه شد |
|-----|-------|
| **T9.1 پنل ۴۱۴۱** | تأیید شد: بدون auth → **401** روی ۴۱۴۱ و ۴۱۴۳؛ `nginx-health` باز. `chmod 600` روی هر دو htpasswd زده شد (T8.2). ۴۱۴۱ به‌عنوان آدرس رسمی در docstring پنل ثبت شد. |
| **T9.2 UI/UX تک‌صفحه‌ای** | `GET /api/status` (badge سبز/زرد/قرمز provider از `/api/diagnostics` + progress هر job از `QH_RUNTIME_STATE.json`) · `GET /api/log/<job_id>?offset=N` (**tail افزایشی**، نه refresh کامل) · `POST /resume` · فیلدهای locked حالا `disabled` رندر می‌شوند · چک‌باکس commit · همه در یک صفحه بدون navigation |
| **T9.3 notify کامل** | `run_completion_pipeline.py` از **صفر** نقطه به notify شروع/پایان/مدت/artifact/خطا برای **هر** stage رسید |
| **T9.4 ویدیو + خلاصه** | ماژول جدید `scripts/episode_summary.py` — خلاصه فقط از artifactها ساخته می‌شود (مدت، تعداد بیت video/image، رزولوشن، مدل‌های **تأییدشده** از receiptها، STT backend، QC، مصرف منابع). caption تلگرام و پیام پایانی از همین می‌آید. |
| **T9.5 بودجه‌ی منابع** | `render_video.py`: `--resource-budget` (پیش‌فرض 0.8) → `threads=max(1,round(nproc*0.8))`، `nice` + `ionice` داخل خود اسکریپت، **سقف supersample** بر اساس مساحت فریم میانی (۱۲ MP)، و `render/RENDER_STATS.json` (wall time, realtime factor, peak child RSS, threads, source). اولویت: `--threads` > profile > بودجه. |
| **T9.6 git به‌عنوان stage** | بعد از **هر دو** QC اجرا می‌شود (`--commit`)، idempotent (تغییر نبود → `no_change`)، `--no-push` برای وقتی credential نیست، `--started-at` حالا ISO می‌پذیرد (قبلاً `perf_counter` بین دو پروسه بی‌معنا بود) |
| **T9.7 MUSIC_PLAN.json** | ماژول جدید `scripts/music_plan.py` — segment list مرتب/بدون gap/بدون overlap با prompt جست‌وجوی هر segment. یک bed = یک entry. `AUDIO_MIX_PROFILE.json` حالا `music.segments` دارد → segment دوم **بدون refactor** |
| **T9.8 زیرنویس دقیق** | `align_beats.py` حالا `timing/WORD_TIMINGS.json` می‌نویسد؛ `build_timeline.py` هر cue را روی **کلمات واقعی** می‌گذارد (تحمل یک کلمه‌ی افتاده)، و فقط برای chunkی که پیدا نشود proportional می‌شود — با ثبت تعداد در QC. `margin_v` از ارتفاع فریم مشتق می‌شود (۱۲٪ portrait = 230px؛ ۹۰px قبلی زیر نوار UI شورتس بود) |

### ✅ P5 — T5.6 anti-repetition: کامل

- ماژول جدید `scripts/episode_history.py`: `VIDEOS.json` حالا به‌جای رشته، برای هر قسمت entry دارد با `opening_activity / opening_location / camera_pattern / book_template_id / world_style_id` (entryهای رشته‌ای قدیمی **در جا upgrade** می‌شوند)
- stage جدید `stage_record_history` بلافاصله بعد از style anchor اجرا می‌شود (نه در publish) تا قسمتی که بعداً fail کند هم قسمت بعدی را محدود کند
- `stage_episode_director`: `avoidance_note` صریح به prompt اضافه می‌شود؛ تکرار → **یک retry با نام‌بردن دقیق تکرار**؛ تکرار دوباره → `FAILED_VALIDATION`
- `book_template_id` و `world_style_id` عمداً از قاعده‌ی تکرار مستثنا هستند (reuse آن‌ها تصمیم درست است)

### ✅ اصلاحات جانبی

- `align_beats`: بیتی که **هیچ** توکنش در transcript پیدا نشود دیگر تایمینگ proportional برنمی‌گرداند → خطا (تخمین = drift خاموش)
- `compose_book_spread`: `random.Random(hash(...))` (per-process salt) و `perspective_warp` مرده حذف شدند
- `video_control_panel`: launch و resume از **یک** سازنده‌ی command استفاده می‌کنند (`pipeline_command`)

---

## ۲) فایل‌های جدید این سشن

```
services/ordak/app/automation/gemini_pro.py          ← مسیر Nano Banana Pro
services/ordak/app/automation/image_validation.py    ← §32
services/ordak/tests/imagefixtures.py                ← PNG واقعی بدون Pillow
services/ordak/tests/test_gemini_pro_path.py
services/ordak/tests/test_image_validation.py
services/ordak/tests/test_generation_receipt_evidence.py
services/ordak/tests/test_flow_settings_verification.py
services/ordak/tests/test_flow_credit_safety.py
scripts/episode_summary.py                           ← خلاصه‌ی قسمت (T9.4)
scripts/music_plan.py                                ← MUSIC_PLAN.json (T9.7)
scripts/episode_history.py                           ← anti-repetition (T5.6)
tests/test_integration_media.py                      ← §97
tests/test_resume_stages.py                          ← §78/§102
tests/test_render_resource_budget.py                 ← T9.5
tests/test_subtitle_timing.py                        ← T9.8
tests/test_music_plan.py, tests/test_episode_history.py, tests/test_control_panel_api.py
```

بازنویسی‌شده: `compose_book_spread.py`, `check_full_stack.py`, `tests/test_model_lock.py`,
`tests/test_book_compositor.py` · تغییر یافته: `gemini_worker.py`, `schemas.py`,
`run_question_harvest_pipeline.py`, `render_video.py`, `build_timeline.py`, `align_beats.py`,
`run_completion_pipeline.py`, `publish_to_telegram.py`, `commit_video_artifacts.py`,
`video_control_panel.py`, `run_pixabay_music.py`, `run_full_video_pipeline*.py`

---

## ۳) کارهای مانده

### P8 — مستندات / دیپلوی (اولویت ۱ — تنها کار بلاک‌نشده)
- [ ] ۵ سند: `docs/QUESTION_HARVEST_PIPELINE.md`, `docs/ORDAK_GEMINI_BROWSER_AUTOMATION.md`,
      `docs/ORDAK_FLOW_BROWSER_AUTOMATION.md`, `docs/SERVER_DEPLOYMENT.md`, `docs/RECOVERY_RUNBOOK.md`
      + آپدیت `VIDEO_CONTROL_PANEL.md` (۴۱۴۱ آدرس رسمی، endpointهای جدید `/api/status`, `/api/log`, `/resume`)
      → قواعد مطلق §104 با زبان صریح؛ کشف‌های DOM فلو/جمینای که در بخش ۵ همین فایل است را منتقل کن
- [ ] T8.1 وحدت مسیر systemd: یونیت روی `/root/...` است ولی کار روی `/opt/...` — `systemctl cat ordak-api` را ببین و یکی کن
- [x] T8.2 `chmod 600` روی htpasswdها (انجام شد) — `access-credentials.txt` از قبل `600` بود
- [ ] T8.4 commit/push نهایی: ordak → pointer → والد (بلاکر #1 را ببین)

### P7 — پذیرش انتها به انتها (نیاز به لاگین کاربر — بلاک)
- [ ] **T7.1**: لاگین ChatGPT / Gemini / Flow از noVNC روی پورت **4143**. الان هر سه
      `logged_in: false` با `open_tabs: 0` هستند. تا این نشود هیچ‌کدام از موارد زیر ممکن نیست.
- [ ] **T2.2 اجرای واقعی**: یک جاب Gemini با `nano_banana_pro` → لاگ باید دو نتیجه‌ی متمایز
      نشان دهد و receipt `pro_regeneration_used=true` با note ‏`pro_distinction=…`
      ⚠️ **نکته‌ی مهم**: needleهای کنترل Pro در `gemini_pro.PRO_ACTION_VERBS` /
      `PRO_QUALITY_TOKENS` از اسپک حدس زده شده‌اند، **روی UI واقعی تأیید نشده‌اند**.
      اولین کار بعد از لاگین: `find_pro_control` را روی یک نتیجه‌ی واقعی اجرا کن و اگر
      برنگشت، متن واقعی دکمه را ببین و لیست را اصلاح کن.
- [ ] **T2.6**: ساخت واقعی `book_design_sheet.png` با Gemini Pro (کد stage آماده است) + بازبینی بصری
- [ ] T7.2–T7.5: تولید واقعی Gemini، Flow Clip A/B، smoke غیرتولیدی تا QC
- [ ] یک اجرای کامل: ChatGPT → Gemini(Pro) → Flow A/B → ElevenLabs → Ajil → trim → music
      → mixed render → QC → publish. **هنوز انجام نشده.**
- [ ] یک جاب Flow با status نهایی `completed` (خط `update_status("completed")` اضافه شده ولی
      با جاب واقعی تأیید نشده)

### باقی‌مانده‌های کوچک
- [ ] `--commit` هنوز از پنل پیش‌فرض روشن نیست (چک‌باکس دارد) چون push والد ۴۰۳ می‌دهد
- [ ] mixer صدا هنوز فقط `music.file` را می‌خواند؛ `music.segments` نوشته می‌شود ولی
      مصرف‌کننده‌ی چند-segment در `polish_audio.py` وقتی segment دوم لازم شد باید اضافه شود

---

## ۴) بلاکرها

1. **push مخزن والد رد می‌شود** — `gh` روی سرور با حساب `AliBalash` است و به
   `M2002HR/YT_Video_Generation_Pipeline` دسترسی write ندارد (HTTP 403).
   کامیت‌ها لوکال محفوظ‌اند. راه‌حل: collaborator کردن `AliBalash` یا token با write.
   (push به `AliBalash/ordak` کار می‌کند.)
2. **هیچ provider لاگین نیست** — `logged_in: false` برای هر سه، `open_tabs: 0`.
   کل P7 و اجرای واقعی به این گره خورده. از `http://<host>:4143` (noVNC، basic auth) وارد شو.
3. **مصرف credit فلو** — هر جاب واقعی ۷ credit. برای هر تست واقعی **اول** `systemctl restart ordak-api`.
4. **رمز basic auth پنل** — در `/root/.config/yt-video-pipeline/access-credentials.txt` است.
   من عمداً محتوایش را چاپ نکردم؛ تست `200 with auth` را خودت بزن.

---

## ۵) دستورات تأیید

```bash
cd /opt/YT_Video_Generation_Pipeline

# تست‌ها — باید 181 pass
PYTHONPATH=.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -q

# تست‌های ordak — باید 140 pass
cd services/ordak && .venv/bin/python -m pytest tests/ -q; cd ../..

# full stack — advisory فقط لاگین provider و working tree باید باشد
.venv/bin/python scripts/check_full_stack.py --skip-providers   # exit 0
.venv/bin/python scripts/check_full_stack.py                    # exit 1 تا لاگین نشود

# هیچ synthetic نماند
grep -rn "allow_synthetic\|synthetic_fallback\|_dummy_\|\[MODEL:" scripts/   # → خالی

# پنل تک‌صفحه‌ای
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4141/          # 401
curl -s http://127.0.0.1:4142/api/status | python3 -m json.tool | head -20
curl -s "http://127.0.0.1:4142/api/log/00000000-0000-0000-0000-000000000000?offset=0"

# خلاصه‌ی یک قسمت واقعی
.venv/bin/python scripts/episode_summary.py videos/009_vikings_history --caption

# لاگین سه provider (هر سه باید True شود)
curl -s http://127.0.0.1:8000/api/diagnostics | python3 -c "
import json,sys
for p,s in (json.load(sys.stdin).get('provider_sessions') or {}).items():
    print(p, s.get('logged_in'), s.get('login_state'), len(s.get('open_tabs') or []))"

# capability زنده‌ی فلو (بدون مصرف credit) — تب فلو باید روی flow/project/<id> باز باشد
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.flow_settings as fs
i=[t for t in list_google_chrome_tabs() if 'flow/project/' in (getattr(t,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(i,'window_id',0), tab_id=getattr(i,'tab_id',0), target_id=getattr(i,'target_id',None))
print(json.dumps(fs.read_capabilities(r).to_dict(), indent=1)); fs.close_settings_menu(r)
PY

# کنترل Pro جمینای روی UI واقعی (بدون مصرف credit) — needleها را همین‌جا تأیید کن
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.gemini_pro as gp
i=[t for t in list_google_chrome_tabs() if 'gemini.google.com' in (getattr(t,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(i,'window_id',0), tab_id=getattr(i,'tab_id',0), target_id=getattr(i,'target_id',None))
print('results:', [x.to_dict() for x in gp.read_result_identities(r)])
print('pro control:', gp.find_pro_control(r))
PY

# گیت
git log --oneline -6; git -C services/ordak log --oneline -3
```

**نکته:** `YT_ORDAK_FLOW_URL` به `.../project/36400b0f-605e-484b-95c5-48e727479dfc` pin است
(به‌جای base URL) تا هر جاب پروژه‌ی جدید نسازد و baseline نتیجه‌ها معنا داشته باشد.

---

## ۶) کشف‌های DOM (verified 2026-09-04، پایه‌ی همه‌ی کد — به سند P8 منتقل شود)

### Flow
- **Frames mode**: ردیف slot = `parent` دکمه‌ی `Swap first and last frames`؛ فرزندان `[start, swap, end]`؛
  slot خالی متن `Start`/`End` و بدون `<img>`؛ پرشده = یک `<img>` با src `media.getMediaUrlRedirect` و لیبل `cancel`
- **Ingredients mode**: دکمه‌ی `add_2` در composer
- **آپلود**: کلیک روی هدف → `[role="dialog"]` → `DOM.setFileInputFiles` روی تک
  `input[type="file"][accept*="image"]` → asset جدید **auto-select** می‌شود و `Add to Prompt` فعال → کلیک confirm
  (⚠️ کلیک روی ردیف در این حالت selection را **لغو** می‌کند)
- **نتیجه‌ها**: `video.src` هر نتیجه شناسه‌ی یکتا دارد → «کدام نتیجه جدید است» با set-difference
- **دانلود**: `Browser.setDownloadBehavior` فقط روی **browser endpoint** و فقط تا وقتی همان
  websocket باز است کار می‌کند؛ `behavior=allowAndName` فایل را با GUID می‌نویسد
- Frames و Ingredients **انحصاری**‌اند (یک tablist، یک active) → Clip B فقط `first_frame` + `last_frame`
- گروه‌های تنظیمات با **محتوای گزینه‌ها** شناسایی می‌شوند نه index (`GROUP_SIGNATURES`)
- لیبل مدل‌ها: `Omni 1.1 Flash`, `Veo 3.1 - Lite/Fast/Quality` (با خط تیره)
- viewport مرورگر 7644×3952 با dpr=0.25 (مختصات CSS = پیکسل اسکرین‌شات × 4)

### Gemini
- لیبل مدل **فقط** از خود کنترل خوانده می‌شود، هرگز از `document.body.innerText`
  (نام مدل‌ها داخل dropdown بسته هم match می‌شود)
- SHA-256 نتیجه را می‌توان **داخل صفحه** حساب کرد: `fetch(src)` → `crypto.subtle.digest`
  (`_linux_execute_javascript` با `awaitPromise: true` اجرا می‌کند، پس async IIFE کار می‌کند)
- URL نتیجه‌ها query param گذرا دارد → identity = بخش قبل از `?`
- ⚠️ **تأیید نشده**: متن دکمه‌ی Pro regeneration

---

## ۷) قواعدی که نباید نقض شوند

- تصویر = **Gemini فقط** · ویدیو = **Google Flow فقط** · متن = **ChatGPT فقط** (همه با Ordak)
- **هیچ** provider/model/synthetic fallback — نه در media، نه در تایمینگ، نه در template کتاب
- به Flow **هیچ style sheet** نمی‌رود
- Frames و Ingredients **انحصاری**‌اند
- `outputs=x1` اجباری
- blind duplicate Generate = **صفر**
- بدون پروکسی، اتصال مستقیم
- `model_verified` فقط با شاهد UI؛ Pro فقط با تمایز مثبت
- هیچ ادعای «کامل شد» بدون تست واقعی مرورگر
- **بعد از تغییر کد ordak، سرویس را restart کن**
