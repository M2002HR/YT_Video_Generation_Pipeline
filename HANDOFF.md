# HANDOFF — Question Harvest (برای ادامه از چت جدید)

> تاریخ: 2026-09-04 · branch: `ordak` · والد: `707ee2e` · ordak: `852a284`

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

⚠️ مهم: بعد از هر تغییر در services/ordak/app باید `systemctl restart ordak-api` بزنی،
وگرنه جاب با کد قدیمی اجرا می‌شود (یک‌بار ۷ credit تلف شد).

از P2 (مسیر Nano Banana Pro) ادامه بده، بعد P6/P9/P8.
گیت را خودت مدیریت کن با پیام‌های کوتاه. سریع و کامل جلو برو.
```

---

## ۱) این سشن چه چیزی تمام شد (با شاهد واقعی مرورگر)

### ✅ P3 — Flow واقعی: **کامل و تست‌شده روی مرورگر**

| تسک | شاهد |
|-----|------|
| T3.1 capability snapshot | `FLOW_CAPABILITY.json` در پوشه‌ی هر جاب نوشته می‌شود |
| T3.2 select+verify تنظیمات | لاگ واقعی: `Omni 1.1 Flash · 720p · 4s · 9:16 · Ingredients · x1 (credits: 7)` |
| T3.3 آپلود frame با نقش | ماژول جدید `flow_references.py` — Start/End روی UI واقعی پر و **تأیید بصری** شد |
| T3.3b نقش کانونیکال | Clip A = Ingredients + `character_sheet` · Clip B = Frames + `first_frame`/`last_frame` |
| T3.4 credit safety | `PENDING_GENERATE.json` **قبل از** Generate نوشته می‌شود؛ reconcile اجباری؛ blind retry = صفر |
| T3.5 دانلود قطعی | `download_to()` + `allowAndName` → فایل با GUID داخل پوشه‌ی مخصوص جاب |
| T3.6/T3.7 login/credits | `FLOW_LOGIN_REQUIRED` / `FLOW_CREDITS_EXHAUSTED` ساختاری |
| receipt واقعی | `FLOW_RECEIPT.json` با `model_verified=true`, `actual_duration_seconds=4`, `credits_required=7` |

**ویدیوی واقعی تولیدشده:** `services/ordak/app/storage/outputs/3110b55a-.../3110b55a-....mp4`
→ ffprobe: **4.01s · 720x1280 · h264 · 1.85MB** (دقیقاً همان قراردادی که خواسته شد)

### ✅ کشف‌های DOM فلو (پایه‌ی همه‌ی کد، verified 2026-09-04)
- **Frames mode**: ردیف slot = `parent` دکمه‌ی `Swap first and last frames`؛ فرزندان `[start, swap, end]`؛
  slot خالی متن `Start`/`End` و بدون `<img>`؛ پرشده = یک `<img>` با src `media.getMediaUrlRedirect` و لیبل `cancel`
- **Ingredients mode**: دکمه‌ی `add_2` در composer
- **آپلود**: کلیک روی هدف → `[role="dialog"]` → `DOM.setFileInputFiles` روی تک
  `input[type="file"][accept*="image"]` → asset جدید **auto-select** می‌شود و `Add to Prompt` فعال → کلیک confirm
  (⚠️ کلیک روی ردیف در این حالت selection را **لغو** می‌کند)
- **نتیجه‌ها**: `video.src` هر نتیجه شناسه‌ی یکتا دارد → «کدام نتیجه جدید است» با set-difference حل شد
- **تایل نتیجه**: نزدیک‌ترین ancestor بزرگ‌تر از 60px از `img/video` با آن src (یک `BUTTON` 150×267)
- **دانلود**: `Browser.setDownloadBehavior` فقط روی **browser endpoint** و فقط تا وقتی همان
  websocket باز است کار می‌کند؛ `behavior=allowAndName` فایل را با GUID می‌نویسد
- viewport مرورگر 7644×3952 با dpr=0.25 (مختصات CSS = پیکسل اسکرین‌شات × 4)

### ✅ P4 — حذف کامل synthetic
`grep -rn "allow_synthetic\|synthetic_fallback\|_dummy_\|\[MODEL:" scripts/` = **صفر**

- `run_question_harvest_pipeline.py` **کامل بازنویسی شد** (1415 خط) روی `ordak_jobs.OrdakJobs`
  با state machine (`PENDING/RUNNING/DONE/REUSED/PAUSED_*/FAILED_*`)، کلاس `Runner`،
  notify تلگرام برای هر stage، receipt واقعی از provider، `stage_book_design_sheet` جدید
- `run_full_video_pipeline_qh_wrapper.py` بازنویسی شد — جعل STT حذف شد،
  `word_timing_is_usable()` واقعاً `backend∈{ajil,local}` و `timestamp_source=="word"` را چک می‌کند
- `generate_character_sheet.py` بازنویسی شد — بدون fallback، exit 2 در خطا
- `video_control_panel.py` — چک‌باکس allow_synthetic حذف شد، QH همیشه از wrapper با `--publish`

### ✅ P5 — سینک روایت (بخش عمده)
- `01_script_writer.md` و `02_retention_editor.md` → خروجی **JSON ساختاریافته**
  (`opening_question_spark`/`book_transition`/`body[]`/`optional_closing`/`cta`/`full_narration`)
- `validate_script_plan()` تأیید می‌کند `full_narration` **دقیقاً** الحاق segmentها است
  (وگرنه تریم روی کلماتی حساب می‌شود که گفته نشده‌اند)
- `align_beats.py` + `align_segments()`/`write_opening_timing()` → `timing/OPENING_TIMING.json`
  با `spark_end`/`transition_end`/`clip_a_target_seconds`/`clip_b_target_seconds`
- `trim_opening_clips.py` **کامل بازنویسی** — هدف از `OPENING_TIMING.json`، بدون clamp/stretch،
  گارد drift 0.12s، خروج غیرصفر `FAILED_VALIDATION`
- `build_timeline.py` — `scale = remaining/audio_duration` **حذف شد**؛ `start_at` اضافه شد؛
  گارد `|video_total − transition_end| < 0.05s`؛ fallback به source untrimmed حذف شد
- `render_video.py` — fail-fast اگر کلیپ کوتاه‌تر از slot خودش باشد (`VIDEO_SLOT_TOLERANCE=0.04`)

### ✅ اصلاح مهم قرارداد Clip B
Flow حالت `Frames` و `Ingredients` را **انحصاری** نشان می‌دهد (یک tablist، یک active).
پس Clip B نمی‌تواند هم‌زمان `book_design_sheet` (ingredient) و frame داشته باشد.
→ `build_flow_uploads(clip="B")` الان فقط `first_frame` + `last_frame` می‌فرستد.
هویت کتاب از طریق `book_spread_frame` (که خودش composite شده) می‌رسد.
`book_design_sheet` در واژگان policy می‌ماند (مصرفش سمت Gemini است).

### ✅ تست‌ها: **69 pass** (از ۶۵)
- `tests/test_mixed_timeline.py` کامل بازنویسی شد: ۶ تست، شامل
  «هر تصویر باید وسط گفتار خودش را در بر بگیرد»، رد drift، رد نبود OPENING_TIMING،
  رد استفاده از source untrimmed
- `test_provider_lock.py::test_pipeline_has_no_synthetic_or_fallback_path` جای تست قبلی
- `test_flow_reference_policy.py` برای قرارداد جدید Clip B آپدیت شد

---

## ۲) فایل‌های جدید/بازنویسی‌شده

```
services/ordak/app/automation/flow_references.py     ← جدید: attach/verify/clear مراجع فلو
services/ordak/app/automation/flow_worker.py         ← بازنویسی کامل (~1000 خط)
services/ordak/app/automation/existing_chrome.py     ← + set_file_input_files / download_to / _linux_cdp_call
services/ordak/app/automation/gemini_worker.py       ← _map_login_error حالا provider-aware
services/ordak/app/job_manager.py                    ← OrdaKError دیگر کدش را از دست نمی‌دهد
scripts/run_question_harvest_pipeline.py             ← بازنویسی کامل
scripts/run_full_video_pipeline_qh_wrapper.py        ← بازنویسی کامل
scripts/trim_opening_clips.py                        ← بازنویسی کامل
scripts/generate_character_sheet.py                  ← بازنویسی کامل
scripts/align_beats.py                               ← + segment alignment + OPENING_TIMING
scripts/build_timeline.py                            ← حذف rescale + گاردها
scripts/render_video.py                              ← fail-fast کلیپ کوتاه
scripts/flow_reference_policy.py, content_projects.py ← قرارداد Clip B
tests/test_mixed_timeline.py                         ← بازنویسی کامل
.env                                                 ← YT_ORDAK_FLOW_URL به یک project واقعی pin شد
```

---

## ۳) کارهای مانده (به ترتیب اولویت)

### P2 — Gemini سخت‌گیرانه (اولویت ۱)
- [ ] **T2.2 مسیر Nano Banana Pro**: submit → نتیجه‌ی اول → یافتن کنترل «Redo with Pro»/Pro
      → invoke → **تمایز مثبت** نتیجه (node id + SHA + dimension) → فقط Pro بپذیر،
      وگرنه `MODEL_NOT_AVAILABLE`. الان `pro_regeneration_used` همیشه false است.
- [ ] **T2.4 receipt واقعی**: `model_verified` فقط با شاهد UI؛ تست: receipt با
      `model_verified=True` بدون فیلد شاهد → رد
- [ ] **T2.5 validation دانلود §32**: رد SHA تکراری با تصویر قبلی، رد thumbnail آپلود کاربر، رد نتیجه‌ی stale
- [ ] **T2.6 `book_design_sheet.png`** واقعی با Gemini Pro (کد stage آماده است:
      `stage_book_design_sheet` در QH pipeline) + بازبینی بصری
- [ ] **T2.7** تست compositor: صفحه‌ی راست دقیقاً همان world_keyframe

### P6 — تست‌های واقعی (اولویت ۲)
- [ ] `tests/test_model_lock.py` هنوز تاتولوژیک است (`assert "720p" != "360p"`) → تست رفتار
      واقعی توابع verify با DOM mock
- [ ] `scripts/check_full_stack.py` مقدار هاردکد `True` دارد → چک واقعی + exit code معنادار
- [ ] integration media §97 (۷ سناریو) + resume tests §78/§102 (بدون مصرف credit)
- [ ] تست unit برای `flow_worker._reconcile_pending` (restart وسط جاب → reconcile نه Generate)

### P9 — پنل / تلگرام / منابع (اولویت ۳)
- [ ] پنل روی **4141**: تأیید auth + websocket؛ ثبت ۴۱۴۱ به‌عنوان آدرس رسمی در مستندات
- [ ] UI/UX تک‌صفحه‌ای بهتر: گروه‌بندی Content/Voice/Engines/Advanced، status badge provider
      از `/api/diagnostics`، tail زنده‌ی لاگ، دکمه‌ی resume
- [ ] `run_completion_pipeline.py` هنوز **صفر** نقطه‌ی notify دارد → به سطح QH برسان
- [ ] ارسال ویدیوی نهایی + خلاصه (مدت، تعداد بیت، مدل‌های تأییدشده، مصرف منابع) به تلگرام
- [ ] **بودجه‌ی منابع**: سرور ۲ vCPU / ۷GB → `threads=max(1,round(nproc*0.8))` + `nice`/`ionice`
      + سقف supersample + `render/RENDER_STATS.json` + knob `--resource-budget 0.8`
- [ ] git به‌عنوان stage اتوماسیون بعد از QC (idempotent، بدون secret)
- [ ] `MUSIC_PLAN.json` با ساختار segment-list + prompt جست‌وجوی موسیقی از ChatGPT
- [ ] زیرنویس دقیق از word timestamps با margin درست (وقتی روشن باشد)
- [ ] T5.6 ثبت anti-repetition §35 در `VIDEOS.json` (`_recent_history()` آماده است، نوشتن مانده)

### P7 — پذیرش انتها به انتها (اولویت ۴)
- [ ] یک اجرای کامل واقعی: ChatGPT → Gemini(Pro) → Flow A/B → ElevenLabs → Ajil → trim
      → music → mixed render → QC. **هنوز انجام نشده.**
- [ ] یک جاب Flow با status نهایی `completed` (خط `runtime.update_status("completed")`
      اضافه شد ولی با جاب واقعی تأیید نشده — آخرین جاب قبل از این fix، `failed` ثبت شد
      در حالی که ویدیو سالم روی دیسک بود)

### P8 — مستندات / دیپلوی
- [ ] ۵ سند: `QUESTION_HARVEST_PIPELINE.md`, `ORDAK_GEMINI_BROWSER_AUTOMATION.md`,
      `ORDAK_FLOW_BROWSER_AUTOMATION.md`, `SERVER_DEPLOYMENT.md`, `RECOVERY_RUNBOOK.md`
- [ ] وحدت مسیر systemd (`/root/...` vs `/opt/...`)
- [ ] `chmod 600` روی htpasswdها + `access-credentials.txt`

---

## ۴) بلاکرها

1. **push مخزن والد رد می‌شود** — `gh` روی سرور با حساب `AliBalash` است و به
   `M2002HR/YT_Video_Generation_Pipeline` دسترسی write ندارد (HTTP 403).
   کامیت‌ها لوکال محفوظ‌اند. راه‌حل: collaborator کردن `AliBalash` یا token با write.
   (push به `AliBalash/ordak` کار می‌کند.)
2. **مصرف credit فلو** — این سشن ۳ جاب واقعی (۲۱ credit) مصرف شد؛ یکی از آن‌ها
   به‌خاطر restart نکردن سرویس تلف شد. برای هر تست واقعی اول restart.

---

## ۵) دستورات تأیید

```bash
cd /opt/YT_Video_Generation_Pipeline

# تست‌ها (باید 69 pass)
PYTHONPATH=.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -q

# هیچ synthetic نماند
grep -rn "allow_synthetic\|synthetic_fallback\|_dummy_\|\[MODEL:" scripts/   # → خالی

# سلامت + لاگین سه provider (هر سه باید True)
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/diagnostics | python3 -c "
import json,sys
for p,s in (json.load(sys.stdin).get('provider_sessions') or {}).items():
    print(p, s.get('logged_in'), s.get('login_state'), len(s.get('open_tabs') or []))"

# capability زنده‌ی فلو (بدون مصرف credit)
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.flow_settings as fs
i=[t for t in list_google_chrome_tabs() if 'flow/project/' in (getattr(t,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(i,'window_id',0), tab_id=getattr(i,'tab_id',0), target_id=getattr(i,'target_id',None))
print(json.dumps(fs.read_capabilities(r).to_dict(), indent=1)); fs.close_settings_menu(r)
PY

# آپلود frame روی UI واقعی (بدون مصرف credit)
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from pathlib import Path
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.flow_settings as fs, app.automation.flow_references as fr
i=[t for t in list_google_chrome_tabs() if 'flow/project/' in (getattr(i,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(i,'window_id',0), tab_id=getattr(i,'tab_id',0), target_id=getattr(i,'target_id',None))
fs._select_tab_option(r, "reference_mode", "Frames"); fs.close_settings_menu(r)
print(json.dumps(fr.read_frame_slots(r)))
PY

# جاب واقعی فلو (⚠️ ۷ credit) — اول systemctl restart ordak-api
# اسکریپت آماده: /tmp/flow_e2e_test.py

# گیت
git log --oneline -5; git -C services/ordak log --oneline -3
```

**نکته:** تب فلو باید روی `flow/project/<id>` باز باشد.
`YT_ORDAK_FLOW_URL` الان به `.../project/36400b0f-605e-484b-95c5-48e727479dfc` pin است
(به‌جای base URL) تا هر جاب پروژه‌ی جدید نسازد و baseline نتیجه‌ها معنا داشته باشد.

---

## ۶) قواعدی که نباید نقض شوند

- تصویر = **Gemini فقط** · ویدیو = **Google Flow فقط** · متن = **ChatGPT فقط** (همه با Ordak)
- **هیچ** provider/model/synthetic fallback
- به Flow **هیچ style sheet** نمی‌رود
- Frames و Ingredients **انحصاری**‌اند — یک کلیپ یا frame دارد یا ingredient
- `outputs=x1` اجباری (هر output اضافه credit را چند برابر می‌کند)
- blind duplicate Generate = **صفر**
- بدون پروکسی، اتصال مستقیم
- هیچ ادعای «کامل شد» بدون تست واقعی مرورگر
- **بعد از تغییر کد ordak، سرویس را restart کن**
