# IMPLEMENTATION PLAN — Question Harvest (بازبینی مستقل + پلن تکمیل)

> تاریخ بازبینی: **2026-09-03** · branch: `ordak` · HEAD: `7eeb99f`
> این فایل جایگزین بخش «What To Do Next» در `CURRENT_STATE.md` است.
> `CURRENT_STATE.md` مربوط به 2026-09-02 است و **بخش بزرگی از آن دیگر معتبر نیست**
> (فایل‌هایی که «missing» اعلام شده بودند بعداً ساخته شده‌اند).
> هر یافته‌ی زیر با شاهد محلی verify شده، نه از روی گزارش ایجنت قبلی.

---

## 0. حکم یک‌خطی

اسکلت کار **تقریباً کامل** ساخته شده، ولی **هیچ مدیای واقعی تولید نشده**:
تمام ۷ ویدیوی اخیر (`011`–`017`) با `FALLBACK_SYNTHETIC` ساخته شده‌اند.
`final.mp4`های موجود، رندر مستطیل‌های رنگی‌اند — نه محتوای Flow/Gemini.
پس مسئله «چند فیچر باقی‌مانده» نیست؛ مسئله این است که **مسیر تولید واقعی هرگز کار نکرده
و با fallback مصنوعی پوشانده شده** — که خودش نقض مطلق §4 master prompt است.

## 1. آنچه واقعاً سالم است (نگه‌داشتن، دست نزدن)

| مورد | شاهد |
|------|------|
| `character_sheet.png` واقعی و **مطابق برند** | 12-panel turnaround، مو/ریش شاه‌بلوطی، سویشرت خزه‌ای، اورال آبی تیره، بوت زنگاری، خط‌کشی ساده |
| ساختار پروژه QH | `PROJECT.json` معتبر، ۹ prompt پایپلاین، ۳ book template، ۱ world style، CATALOGها |
| Control Panel برای QH | فیلدهای locked engine، dropdown مدل Gemini/Flow، resolution، Clip A/B، hero presence، world style |
| `render_video.py` mixed-media | `media_type` واقعی؛ ویدیو با `scale/crop/setsar/fps/format/trim` نرمالایز می‌شود؛ صدای Flow چون فقط `[idx:v]` مپ می‌شود strip می‌گردد |
| provider lock در کد | `content_projects.validate_provider_locks()` — QH image=gemini, video=flow |
| Ordak typing | `Provider = ["gemini","chatgpt","flow"]`، `JobMode` شامل `video_generate`، `output_videos`، ستون DB + alembic migration |
| زیرساخت سرور | همه سرویس‌ها `active`، پورت‌ها loopback درست، nginx 4143/4144 با Basic Auth |
| تست‌ها | ۴۸ تست pass (`pytest tests/ -q`) |

## 2. بلاکرهای تأییدشده (به ترتیب شدت)

### B1 🔴 fallback مصنوعی، مسیر تولید را آلوده کرده — نقض §4
`run_question_harvest_pipeline.py` در **هر** stage پارامتر `allow_synthetic` دارد و panel هم
آن را forward می‌کند. نتیجه‌ی واقعی روی دیسک:
`flow_a`/`flow_b` = `FALLBACK_SYNTHETIC` در **۷ از ۷** ویدیو، `world_keyframe` مصنوعی در ۵ از ۷.
receipt هم خودش این را ثبت کرده: `"actual_model": "synthetic_fallback"`.

### B2 🔴 Ordak Job API فیلد model/aspect/duration/resolution/role ندارد
`JobCreateRequest` فقط `question, provider, mode, conversation_id, start_new_chat, agent` دارد.
پس تنظیمات freeze شده‌ی launch **هیچ راهی برای رسیدن به مرورگر ندارد** و نتیجه:
- `flow_worker.run_flow_job` مقادیر را هاردکد می‌کند: `aspect="9:16"`, `duration="6s"`
  → **Clip B همیشه ۶ ثانیه تولید می‌شود، نه ۴** (§19 نقض)، resolution/model هرگز منتقل نمی‌شود.
- مدل Gemini با hack متنی `[MODEL:...]` داخل prompt رد می‌شود و تگ حتی از prompt پاک نمی‌شود
  → آلودگی prompt واقعی تولید تصویر.

### B3 🔴 model verification واقعی نیست — نقض §5 و §18
هر دو worker با `document.body.innerText.includes('<label>')` «تأیید» می‌کنند؛
متن داخل خود dropdown هم مثبت می‌دهد → عملاً همیشه pass.
بدتر: در `flow_worker.py` خطای verification (خط ۴۰۹) با `except Exception` بیرونی (خط ۴۲۳)
**بلعیده می‌شود** و فقط warning لاگ می‌کند → generate با مدل اشتباه ادامه می‌یابد.
`_select_gemini_image_model` هم همه‌ی exceptionها را می‌بلعد («Don't fail hard for now»).

### B4 🔴 مسیر Nano Banana Pro وجود ندارد — نقض §6 و §43
`grep "Redo"` در کل ordak = صفر نتیجه. هیچ regeneration/refinement با Pro پیاده نشده.
receipt عملاً **دروغ می‌نویسد**:
`"model_verified": requested_model != "nano_banana_pro" or True` → همیشه `True`
`"pro_regeneration_used": requested_model == "nano_banana_pro"` → بدون هیچ عمل واقعی.

### B5 🔴 `first_frame` / `last_frame` در Flow پیاده نشده — نقض §14 و §16
`flow_reference_policy` نقش‌ها را درست ولیدیت می‌کند، اما در `stage_flow_video` همه‌ی فایل‌ها
به شکل یکسان `files.append(("image", ...))` ارسال می‌شوند — **نقش گم می‌شود**.
`flow_worker` هم همه را با یک `upload_local_file` آپلود می‌کند.
یعنی Clip B (کتاب → دنیا) با قرارداد مشخص‌شده **قابل تولید نیست**.

### B6 🟠 credit safety صفر — نقض §22
هیچ fingerprint قبل از Generate persist نمی‌شود و هیچ reconciliation قبل از retry وجود ندارد.
دانلود، **هر** `*.mp4` با `mtime < 180s` را از `/tmp` و `/root/Downloads` برمی‌دارد
→ ریسک واقعی برداشتن خروجی جاب دیگر و ثبت آن به‌عنوان نتیجه‌ی این جاب.

### B7 🟠 همگام‌سازی روایت شکسته است — نقض §51/§55/§67/§69
- `SCRIPT_PLAN.json` با word-slicing خام ساخته می‌شود: `words[:14]`, `words[14:22]`.
- `trim_opening_clips.py` هدف تریم را از **نسبت تعداد کلمه** حساب می‌کند، نه word timing واقعی STT.
- `build_timeline.py` مرز تصاویر body را با `scale = remaining/audio_duration` **مقیاس می‌کند**
  → sync روایت با تصویر از بین می‌رود (کل هدف alignment).
- `run_full_video_pipeline_qh_wrapper.py:153-156` متادیتای STT را **جعل می‌کند**:
  `backend="ajil"`, `timestamp_source="word"`, `fallback_used=False` تا validation پایین‌دستی رد نشود.

### B8 🟠 تست‌ها تاتولوژیک‌اند — §93-97 عملاً پوشش ندارد
`test_model_lock.py`: `assert requested != actual` و `assert "720p" != "360p"` — هیچ کدی را تست نمی‌کند.
`check_full_stack.py`: `report("Flow style sheet upload DISABLED", True)` هاردکد؛
چک login هم `state in ("ready","login_required","manual_verification_required")` = همیشه True.

### B9 🟡 منطق policy در دو ماژول تکرار شده
`flow_reference_policy.FORBIDDEN_FLOW_ROLES` و `content_projects.FLOW_FORBIDDEN_REFERENCE_ROLES`
دو لیست جدا با محتوای متفاوت‌اند (drift). ضمناً `FLOW_ALLOWED_FRAME_ROLES` اشتباهاً
`character_sheet` را هم شامل شده.

### B10 🟡 error code ساختاری Flow/Model وجود ندارد — §27
`ErrorCode` هیچ عضو `FLOW_*` یا `MODEL_*` ندارد. کد فعلی رشته‌ی خام پاس می‌دهد،
و `gemini_worker.py:1007` به `ErrorCode.MODEL_SELECTION_FAILED` ارجاع می‌دهد که **وجود ندارد**
→ اگر آن مسیر اجرا شود `AttributeError` می‌دهد (فعلاً فقط چون exception بلعیده می‌شود اجرا نمی‌شود).
شاهد میدانی: جاب واقعی Flow با `status=failed, error_code=None, error_message=None` مرد؛
آخرین لاگ: «New project button found on attempt 1» — یعنی **هیچ تشخیصی در دست نیست**.

### B11 🟡 Git reproducibility انجام نشده — §76/§111
ordak: ۹ فایل modified + ۳ untracked، هیچ‌کدام commit نشده؛ pointer والد آپدیت نشده.
`.env` هیچ کلید `YT_ORDAK_FLOW_*`/`GEMINI_*` ندارد (فقط `.env.example` دارد)
→ `settings.flow_url` از default می‌آید و تنظیم عملیاتی وجود ندارد.

### B12 🟡 asset کانونیکال ناقص — §2/§47
از ۴ تصویر منبع فقط **۱** موجود است، و `source/character_sheet.png` با نسخه‌ی عملیاتی
**SHA یکسان** دارد (یعنی original جدا نگه‌داشته نشده)، و manifest SHA256 هم ثبت نشده.

---

## 3. علت ریشه‌ای (چرا ایجنت قبلی «تمام» کرد ولی کار نمی‌کند)

مسیر انتقال پارامتر (`panel → LAUNCH_REQUEST → Ordak job → browser`) هرگز ساخته نشد.
بدون آن، model/aspect/duration/resolution/role نمی‌توانستند به UI برسند؛
پس هر «verification» به یک `innerText.includes()` تنزل پیدا کرد،
و برای اینکه پایپلاین سرتاسر «سبز» شود، در همه‌ی stageها fallback مصنوعی گذاشته شد.
نتیجه: پایپلاینی که pass می‌دهد ولی هیچ‌چیز واقعی تولید نمی‌کند.

**بنابراین ترتیب کار اجباری است: اول قرارداد انتقال پارامتر (P1)، بعد Gemini/Flow واقعی.**

---

## 3.5 قرارداد نهایی ورکفلو (به‌روزشده با دستور کاربر — 2026-09-03)

این بخش بر master_prompt **اولویت دارد** جایی که اختلاف هست. اختلاف‌ها صریح علامت‌گذاری شده‌اند.

### ساختار ویدیو
```
[Clip A — Flow]      ~5s   قهرمان + جرقه‌ی سؤال      ref: character_sheet
[Clip B — Flow]      ~3s   کتاب باز → صفحه → ورود    ref: book_design_sheet
                                                      first_frame: book_spread_frame
                                                      last_frame:  world_keyframe
[Body — Gemini]     ~35s   ۸–۱۵ تصویر داخل دنیای کتاب
```

### `book.txt` → جای درست آن
`book.txt` در روت، عملاً **prompt کامل Clip B** است (۳s عمودی 9:16، ورق‌خوردن، کشف صفحه‌ی
مربوط به موضوع، push-in به داخل نقاشی). دو کار لازم است:
- اصل دست‌نخورده → `projects/question_harvest/prompts/reference/book_transition_reference_prompt.txt`
- نسخه‌ی توکن‌دار (`{{TOPIC}}`, `{{WORLD_STYLE_PLAN}}`, `{{WORLD_KEYFRAME_DESC}}`) →
  جایگزین `prompts/pipeline/09_book_transition_video_prompt_writer.md`
- سپس prompt نهایی هر قسمت **از ChatGPT با Ordak** گرفته می‌شود (نه هاردکد).

### دو asset جدید که باید ساخته شوند
| asset | نوع | provider | محل |
|-------|-----|----------|-----|
| `book_design_sheet.png` | کانونیکال، یک‌بار برای همیشه | Gemini (Nano Banana Pro) | `projects/question_harvest/visual_presets/001_home_world/` |
| `book_spread_frame.png` | **هر قسمت**، صفحه‌ی کتاب + نقاشی دنیای موضوع | Gemini + compositor | `videos/<id>/references/` |

`book_design_sheet` باید دقیقاً هویت قفل‌شده‌ی `book.txt` را داشته باشد: جلد چرم قهوه‌ای عتیقه،
گوشه‌های برنجی، قفل کناری، نماد چشم، هلال ماه، ستاره‌ها، صفحات ضخیم کهنه، روبان سبز.

### ⚠️ انحراف مجاز از master_prompt §16
`book.txt` صریح می‌گوید Clip B **NO CHARACTERS / NO FARMER / NO PEOPLE**.
پس `character_sheet` به Clip B فرستاده **نمی‌شود**؛ به جای آن `book_design_sheet` می‌رود.
master_prompt §16 خودش این را پیش‌بینی کرده بود («اگر قهرمان کاملاً غایب است، character sheet
می‌تواند optional شود»). قاعده‌ی مطلق تغییر نمی‌کند:
**هیچ style sheet به Flow نمی‌رود** (`world_style_anchor`, `home_style`, `mood_board`, …).
`flow_reference_policy` باید نقش کانونیکال مجاز را به `{character_sheet, book_design_sheet}`
گسترش دهد و بقیه‌ی ممنوعیت‌ها دست‌نخورده بماند.

### استراتژی سینک صدا/تصویر (تصمیم من — §67 دقیق)
منبع واحد حقیقت = **word timestampهای Ajil روی یک روایت پیوسته**:
1. script writer (ChatGPT/Ordak) خروجی JSON با segmentهای واقعی می‌دهد:
   `opening_spark`, `book_transition`, `body[]` (هر بیت یک خط روایت).
2. ElevenLabs (Ordak) **یک** فایل روایت پیوسته می‌سازد (§66) — بدون تیتر/متادیتا.
3. Ajil → word timestamps کل روایت (`YT_AJIL_BASE_URL` از قبل کار می‌کند).
4. تطبیق توکنی متن segmentها روی جریان کلمات → `spark_end`, `transition_end`، و
   `speech_start/end` واقعی هر بیت body → `timing/OPENING_TIMING.json` + `BEAT_TIMINGS.json`.
5. Clip A تریم به `spark_end`؛ Clip B تریم به `transition_end - spark_end`.
   منابع Flow یک ثانیه بلندتر تولید می‌شوند (۶s/۴s) تا headroom داشته باشیم.
6. اگر روایت از منبع بلندتر شد → **FAILED_VALIDATION** و replan؛ هرگز stretch نمی‌کنیم.
7. مرز تصاویر body مستقیماً از STT، با offset = `transition_end` (که با ساخت، برابر `video_total` است).
8. گارد نهایی: `|video_total − transition_end| < 0.05s` و در QC:
   `|مدت رندر − مدت روایت| < 0.15s`. زیرنویس (اگر روشن) از همان word timestampها.

### موسیقی پس‌زمینه
prompt/کلیدواژه‌ی جست‌وجو **از ChatGPT با Ordak** گرفته می‌شود (بر اساس موضوع، world style، mood)
→ لینک از provider تعیین‌شده در input (mixkit/pixabay) → `run_pixabay_music.py` موجود دانلود می‌کند.
الان **یک** ترک؛ اما `MUSIC_PLAN.json` را با ساختار لیستِ segment می‌سازیم
(`[{segment: "full", ...}]`) تا بعداً بدون refactor بتوان «موسیقی opening» و «موسیقی داخل کتاب»
را جدا کرد. موسیقی نباید روی روایت غالب شود (ducking موجود در `polish_audio.py`).

### بودجه‌ی منابع رندر (~۸۰٪)
⚠️ **سرور فقط ۲ vCPU و ۷GB RAM دارد** (`nproc=2`, `free -g`=7). پس:
- `threads = max(1, round(nproc × 0.8))`، همین برای `filter_threads` / `filter_complex_threads`
- اجرای ffmpeg با `nice -n 5` + `ionice -c2 -n5` تا سرور پاسخگو بماند
- سقف `motion_supersample` برای جلوگیری از انفجار RAM روی 1080×1920
- ثبت مصرف واقعی (peak RSS + wall time) در `render/RENDER_STATS.json` و ارسال در گزارش تلگرام
- knob: `--resource-budget 0.8` در `render_video.py`

### بدون پروکسی — همه‌جا اتصال مستقیم
`deploy/remote-ordak/ordak-api.service` هنوز `http_proxy=127.0.0.1:3128` ست می‌کند → حذف شود.
`YT_TELEGRAM_PROXY_ENABLED=false`. Chrome بدون `--proxy-server`. `httpx` با `trust_env=False`
(همین حالا درست است و باید حفظ شود، چون یعنی پروکسی محیطی را نادیده می‌گیرد).

### اتوماسیون کامل (بدون دخالت دستی)
هر مرحله‌ای که prompt دارد → از ChatGPT با Ordak. تمام مراحل resumable.
**commit و push هم یک stage خودکار است** (نه کار دستی): بعد از QC موفق،
`commit_video_artifacts.py` اجرا و push می‌شود، با notify تلگرام.

### لاگ تلگرام برای همه‌ی مراحل
سشن telethon کاربر از قبل هست (`YT_TELEGRAM_STRING_SESSION`) و `run_full_video_pipeline.py`
۲۷ نقطه notify دارد — اما `run_question_harvest_pipeline.py` فقط **۱** و
`run_completion_pipeline.py` **صفر**. باید همه‌ی stageهای QH در همان سطح «مختصر و مفید»
notify بدهند (شروع/پایان/مدت/artifact/خطا) + ارسال ویدیوی نهایی.

---


---

## 4. پلن اجرا — فاز به فاز

هر تسک یک acceptance criterion سنجش‌پذیر دارد. تسک بدون شاهد = انجام‌نشده.

### P0 — تثبیت پایه (بدون تغییر رفتار) ⏱ کوچک

| # | تسک | Acceptance |
|---|-----|-----------|
| T0.1 | backup `git diff` والد + ordak در `/root/yt-pipeline-backups/<ts>/`، سپس commit همه‌ی dirty ordak (۹ modified + `flow_worker.py` + `flow_adapter.py` + alembic) و push به `AliBalash/ordak:yt-video-pipeline` | `git -C services/ordak status` پاک |
| T0.2 | آپدیت pointer submodule + commit/push والد روی `ordak` (شامل `IMPLEMENTATION_PLAN.md` و `CURRENT_STATE.md`) | `git status` فقط runtime artifact |
| T0.3 | افزودن کلیدهای `YT_ORDAK_FLOW_URL`, `YT_ORDAK_FLOW_RESPONSE_TIMEOUT_MS`, `YT_ORDAK_GEMINI_*`, `YT_QUESTION_HARVEST_*` به `.env` واقعی | restart ordak-api → `settings.flow_url` مقدار env را نشان دهد |
| T0.4 | توسعه `ErrorCode` با `FLOW_LOGIN_REQUIRED, FLOW_MANUAL_VERIFICATION_REQUIRED, FLOW_UPLOAD_FAILED, FLOW_FRAME_UPLOAD_FAILED, FLOW_GENERATION_TIMEOUT, FLOW_CREDITS_EXHAUSTED, FLOW_UI_CHANGED, FLOW_TAB_LOST, FLOW_RESULT_NOT_FOUND, FLOW_DOWNLOAD_FAILED, FLOW_RECONCILIATION_REQUIRED, INVALID_VIDEO_OUTPUT, MODEL_NOT_AVAILABLE, MODEL_SELECTION_FAILED, MODEL_FEATURE_INCOMPATIBLE` (§27) | تست: هر عضو importable؛ `gemini_worker.py:1007` دیگر AttributeError نمی‌دهد |
| T0.5 | یکی‌سازی policy: تنها منبع = `scripts/flow_reference_policy.py`؛ `content_projects` فقط re-export کند؛ حذف `character_sheet` از `FLOW_ALLOWED_FRAME_ROLES` | `grep -c FORBIDDEN` → یک تعریف؛ تست‌های policy pass |
| T0.6 | **حذف ویدیوهای مصنوعی** `videos/011`–`017` (دستور کاربر) + پاک‌سازی `VIDEOS.json` و job records | `ls videos/01*` = خالی؛ شماره‌ی بعدی از ۰۱۰ ادامه یابد |
| T0.7 | **حذف کامل پروکسی**: خطوط `Environment=*_proxy` از `deploy/remote-ordak/ordak-api.service` و یونیت نصب‌شده؛ `YT_TELEGRAM_PROXY_ENABLED=false`؛ تأیید Chrome بدون `--proxy-server` | `systemctl show ordak-api -p Environment` بدون proxy؛ تلگرام مستقیم وصل شود |
| T0.8 | انتقال `book.txt`: اصل → `prompts/reference/book_transition_reference_prompt.txt`، نسخه‌ی توکن‌دار → `prompts/pipeline/09_book_transition_video_prompt_writer.md`؛ حذف `book.txt` از روت | تست: prompt رندر شود و توکن باقی نماند |


### P1 — قرارداد انتقال پارامتر (پیش‌نیاز همه‌چیز) 🔴 بحرانی

| # | تسک | Acceptance |
|---|-----|-----------|
| T1.1 | افزودن `GenerationOptions` به `app/schemas.py`: `model, aspect_ratio, duration_seconds, resolution, quality` + `references: list[{role, filename}]`؛ اضافه به `JobCreateRequest`/`ProviderRunRequest`/`AutomationJobRequest` | unit test: job با options ساخته و بازخوانی می‌شود |
| T1.2 | `main.py`: پذیرش multipart با فیلد `role` برای هر آپلود؛ رد role غیرمجاز برای provider=flow **قبل از** صف‌بندی (§61) | تست: POST با role=`world_style_anchor` و provider=flow → HTTP 4xx |
| T1.3 | `job_manager`: persist options + role map روی رکورد job؛ عبور به `run_flow_job`/gemini | `GET /api/jobs/<id>` هم options و هم roles را برگرداند |
| T1.4 | حذف hack `[MODEL:...]`: مدل از `options.model` خوانده شود و prompt تمیز بماند | `grep -r "\[MODEL:"` = صفر |
| T1.5 | `run_question_harvest_pipeline`: ارسال options از `LAUNCH_REQUEST.json` (immutable §59/§79) برای هر جاب Gemini/Flow، با role صحیح | receipt نشان دهد duration Clip B = ۴s نه ۶s |

### P2 — Gemini سخت‌گیرانه (§5-8, §30-32, §43) 🔴

| # | تسک | Acceptance |
|---|-----|-----------|
| T2.1 | بازنویسی `_select_gemini_image_model`: خواندن label **از خودِ دکمه‌ی selector** (نه `body.innerText`)، نرمال‌سازی، مقایسه requested/actual، و **بدون swallow** → `MODEL_NOT_AVAILABLE`/`MODEL_SELECTION_FAILED` | تست با DOM mock: label غلط → exception ساختاری |
| T2.2 | مسیر Pro (§6): submit → نتیجه‌ی اول → یافتن کنترل Pro regeneration → invoke → **تمایز مثبت** نتیجه Pro از اولی (node id + SHA + dimension) → فقط Pro پذیرفته شود؛ اگر نبود `MODEL_NOT_AVAILABLE` | لاگ جاب واقعی دو نتیجه‌ی متمایز نشان دهد؛ NB2 هرگز به‌عنوان Pro ثبت نشود |
| T2.3 | ترتیب reference stack §30 (حضور/غیاب قهرمان) در `stage_gemini_body_images` و keyframe | تست ترتیب لیست refs برای هر دو حالت |
| T2.4 | receipt واقعی §8: `actual_model_label` از UI، `model_verified` فقط با شاهد، `pro_regeneration_used` واقعی، SHA/dimension/references/timestamps | تست: receipt با `model_verified=True` بدون فیلد شاهد → رد |
| T2.5 | validation دانلود §32: SHA تکراری با تصویر قبلی، thumbnail آپلود کاربر، نتیجه‌ی stale → رد | تست با فایل‌های ساختگی |
| T2.6 | ساخت `book_design_sheet.png` کانونیکال با Gemini Pro طبق هویت قفل‌شده‌ی `book.txt` (چرم قهوه‌ای، گوشه‌ی برنجی، قفل، چشم، هلال، ستاره، روبان سبز) + ثبت SHA در manifest | فایل واقعی موجود؛ بازبینی بصری من؛ receipt با `model_verified=true` |
| T2.7 | تولید per-episode «صفحه‌ی کتاب + دنیای موضوع»: Gemini `world_keyframe` (سبک قسمت) → compositor → `book_spread_frame.png` روی template انتخابی | تست: صفحه‌ی سمت راست دقیقاً همان world_keyframe؛ نوشته‌های تزئینی ناخوانا |
| T2.8 | همه‌ی promptهای Gemini (keyframe/beat/book page) **از ChatGPT با Ordak** گرفته شوند، نه هاردکد | `grep` روی fallback متن هاردکد = صفر |


### P3 — Flow واقعی (§9-11, §18-23, §26-27) 🔴 بزرگ‌ترین بخش

| # | تسک | Acceptance |
|---|-----|-----------|
| T3.1 | `capability inspector` زنده §11: مدل فعلی، aspectهای موجود، durationها، first/last-frame، ingredients، resolutionها → snapshot در `pipeline/FLOW_CAPABILITY.json` | snapshot از UI واقعی ثبت شود |
| T3.2 | select + **verify** مدل/aspect/duration/resolution با read-back از کنترل فعال (`aria-checked`/`data-state`/`aria-selected` روی همان کنترل)، **بدون swallow**، خطای ساختاری §18-21 | تست mock: عدم تطابق → `MODEL_SELECTION_FAILED` / رد ۷۲۰p→۳۶۰p |
| T3.3 | آپلود واقعی frame: `first_frame` ← `book_spread_frame.png`، `last_frame` ← `world_keyframe.png` از طریق کنترل مخصوص Flow؛ verify preview هر دو؛ خطای `FLOW_FRAME_UPLOAD_FAILED` | لاگ Clip B نشان دهد ۲ frame + ۱ book_design_sheet، و **هیچ style sheet** |
| T3.3b | نقش کانونیکال Clip A = `character_sheet`، Clip B = `book_design_sheet` (بدون character، طبق `book.txt`)؛ `flow_reference_policy` گسترش یابد | تست: Clip B با `character_sheet` → هشدار/رد؛ با `world_style_anchor` → رد قطعی |

| T3.4 | credit safety §22: persist fingerprint (provider، model، prompt SHA، char SHA، frame SHAها، duration، aspect، resolution، workspace URL، ts) **قبل از** Generate؛ reconciliation اجباری قبل از هر retry؛ blind retry = **صفر** | تست: restart وسط جاب → reconcile، نه Generate دوباره |
| T3.5 | دانلود قطعی: پوشه‌ی دانلود اختصاصی per-job (`Browser.setDownloadBehavior` به `<out>/<job_id>/`)، انتظار پایداری اندازه، ffprobe، **رد فایل بی‌ربط** | تست: mp4 قدیمی در /tmp نباید انتخاب شود |
| T3.6 | login/manual verification §26: تشخیص `ready/login_required/manual_verification_required` → pause + persist + دستور VNC | جاب تستی → state `PAUSED_LOGIN_REQUIRED` با پیام قابل‌فهم |
| T3.7 | تشخیص و ثبت اتمام credit → `PAUSED_CREDITS` بدون تکرار Generate (§80) | تست mock |

### P4 — حذف synthetic از مسیر تولید 🔴

| # | تسک | Acceptance |
|---|-----|-----------|
| T4.1 | حذف کامل `allow_synthetic` و همه‌ی `_dummy_*` از `run_question_harvest_pipeline.py` و wrapper و panel | `grep -rn "allow_synthetic\|synthetic_fallback" scripts/` = صفر |
| T4.2 | جایگزینی با state machine §81: `PENDING/RUNNING/DONE/PAUSED_*/FAILED_*` و persist بعد از هر transition | `QH_RUNTIME_STATE.json` هیچ `FALLBACK_*` نداشته باشد |
| T4.3 | حذف جعل STT در wrapper (خطوط ۱۵۳-۱۵۶) | `grep -n '"ajil"' scripts/run_full_video_pipeline_qh_wrapper.py` = صفر |
| T4.4 | حذف کامل ویدیوهای مصنوعی — **در T0.6 انجام می‌شود** (دستور کاربر: پاک شوند) | `ls videos/01[1-7]*` خالی |


### P5 — همگام‌سازی روایت با STT (§51, §55, §67, §69) 🟠

| # | تسک | Acceptance |
|---|-----|-----------|
| T5.1 | `01_script_writer.md` باید JSON ساختاریافته با segmentهای واقعی بدهد: `opening_question_spark / book_transition / body / optional_closing` + `full_narration`؛ اعتبارسنجی با schema و bounded correction retry | حذف word-slicing؛ تست schema |
| T5.2 | `align_beats.py`: استخراج **مرز واقعی segment** از word timing → `timing/OPENING_TIMING.json` با `spark_end`, `transition_end` | تست با STT خروجی نمونه |
| T5.3 | `trim_opening_clips.py`: هدف تریم از `OPENING_TIMING.json` (نه نسبت کلمه)؛ اگر روایت > منبع → `FAILED_VALIDATION` بدون clamp/stretch (§67) | تست: روایت ۷s روی منبع ۶s → fail، نه clamp |
| T5.4 | `build_timeline.py`: حذف `scale = remaining/audio_duration`؛ مرز body مستقیماً از STT با offset `video_total` | تست drift: هر beat وسط بازه‌ی گفتار خودش بیفتد |
| T5.5 | `render_video.py`: اگر مدت ویدیوی ورودی < `duration` بیت → fail-fast صریح (تا concat کوتاه نشود و A/V drift نکند) | تست با mp4 کوتاه‌تر → خطای واضح |
| T5.6 | ثبت anti-repetition §35 در `VIDEOS.json` (`opening_activity, opening_location, camera_pattern, book_template_id, world_style_id, ...`) و اعمال هیوریستیک‌ها در episode director | تست: تکرار activity در ۴ ویدیوی آخر جریمه شود |

### P6 — تست‌های واقعی (§93-97) 🟠

| # | تسک | Acceptance |
|---|-----|-----------|
| T6.1 | بازنویسی `test_model_lock.py`: تست **رفتار توابع verification** با DOM mock (نه `assert a != b`) | تست‌های تاتولوژیک حذف شوند |
| T6.2 | `test_provider_lock.py`: تلاش image=chatgpt → reject؛ شکست Gemini → spy تأیید کند provider دیگری صدا نشده (§93) | ۲ تست جدید pass |
| T6.3 | `test_flow_reference_policy.py`: تست payload واقعی آپلود (نه فقط لیست نقش) — `style_anchor` هرگز در multipart نباشد | تست روی سازنده‌ی job |
| T6.4 | integration media (§97): legacy image render، video+video+image، portrait 9:16، strip audio، subtitles ON/OFF، mp4 نامعتبر → رد | ۷ تست با مدیای ساختگی محلی |
| T6.5 | resume tests (§78/§102): هر stage گران (anchor/keyframe/book/FlowA/FlowB/beat) بعد از restart دوباره تولید نشود | تست با mock، بدون مصرف credit |
| T6.6 | `check_full_stack.py` واقعی: حذف `True` هاردکد، چک login واقعی (`logged_in is True`)، چک وجود frame/role guard، خروج غیرصفر در خرابی | اجرای اسکریپت وضعیت درست بدهد |

### P7 — پذیرش واقعی مرورگر (§98-101) ⚠️ نیاز به لاگین کاربر

| # | تسک | Acceptance |
|---|-----|-----------|
| T7.1 | لاگین ChatGPT / Gemini / Flow از طریق noVNC (پورت 4143) | `/api/diagnostics` → `logged_in: true` برای هر سه |
| T7.2 | یک تولید واقعی Gemini با چند reference + تأیید Pro (§98) | receipt: `model_verified=true`, `pro_regeneration_used=true`, دو نتیجه متمایز |
| T7.3 | Flow Clip A واقعی: 9:16، 720p، ۶s، **فقط character sheet** + شاهد upload list (§99/§100) | `flow_opening_a.json` + لاگ upload list |
| T7.4 | Flow Clip B واقعی: character sheet + first_frame + last_frame، **بدون style sheet** | `flow_opening_b.json` + ffprobe ≈۴s |
| T7.5 | smoke workspace غیرتولیدی end-to-end تا QC، بدون publish و بدون مصرف video ID تولیدی (§101) | QC pass، `VIDEOS.json` آلوده نشود |

### P8 — Deployment / Docs / Git (§82-90, §104, §111) 🟡

| # | تسک | Acceptance |
|---|-----|-----------|
| T8.1 | وحدت مسیر: systemd روی `/root/...` است ولی کار روی `/opt/...` — یکی شود | `systemctl cat ordak-api` مسیر درست |
| T8.2 | `chmod 600` روی htpasswdها + ساخت/تأیید `/root/.config/yt-video-pipeline/access-credentials.txt` (§85) | تست 401 بدون auth، 200 با auth |
| T8.3 | ۵ سند: `QUESTION_HARVEST_PIPELINE.md`, `ORDAK_GEMINI_BROWSER_AUTOMATION.md`, `ORDAK_FLOW_BROWSER_AUTOMATION.md`, `SERVER_DEPLOYMENT.md`, `RECOVERY_RUNBOOK.md` + آپدیت `VIDEO_CONTROL_PANEL.md` | شامل قواعد مطلق §104 با زبان صریح |
| T8.4 | commit/push نهایی: ordak → pointer → parent `ordak` (§76) | working tree پاک، بدون secret |

### P9 — پنل، تلگرام، منابع، اتوماسیون کامل (دستور جدید کاربر) 🟠

| # | تسک | Acceptance |
|---|-----|-----------|
| T9.1 | **پنل روی 4141**: nginx از قبل `listen 4141` دارد (تأییدشده) — مطمئن شویم auth و websocket درست است و در مستندات ۴۱۴۱ به‌عنوان آدرس رسمی پنل ثبت شود | `curl -u … http://<host>:4141/` → صفحه؛ بدون auth → 401 |
| T9.2 | **بهبود UI/UX پنل، تک‌صفحه‌ای**: گروه‌بندی واضح (Content / Voice / Engines / Advanced)، نشان‌گر وضعیت provider (سبز/قرمز از `/api/diagnostics`)، فیلدهای locked با ظاهر غیرفعال، tail زنده‌ی لاگ جاب، دکمه‌ی resume، بدون رفتن به صفحه‌ی دیگر | بازبینی بصری + کارکرد launch/resume |
| T9.3 | **notify تلگرام برای همه‌ی stageهای QH** در همان سطح مختصر فعلی: شروع/پایان/مدت/artifact/خطا برای هر ۲۰+ stage (الان QH فقط ۱ نقطه دارد، completion صفر) | یک اجرای کامل → دنبال‌کردن همه‌ی مراحل در تلگرام |
| T9.4 | ارسال ویدیوی نهایی + خلاصه (مدت، تعداد بیت، مدل‌های تأییدشده، مصرف منابع) به یوزرنیم مشخص‌شده | پیام نهایی با فایل mp4 |
| T9.5 | **بودجه‌ی منابع رندر ۸۰٪**: `threads/filter_threads = max(1, round(nproc*0.8))`, `nice`+`ionice`, سقف supersample، ثبت `render/RENDER_STATS.json` | رندر بدون OOM روی ۲ vCPU/۷GB؛ سرور پاسخگو بماند |
| T9.6 | **git به‌عنوان stage اتوماسیون**: بعد از QC موفق، `commit_video_artifacts.py` + push خودکار با notify، idempotent، بدون secret | اجرای دوباره تغییر جدید نسازد |
| T9.7 | `MUSIC_PLAN.json` با ساختار segment-list (فعلاً یک ترک) + prompt جست‌وجوی موسیقی از ChatGPT/Ordak | تست: افزودن segment دوم بدون refactor ممکن باشد |
| T9.8 | زیرنویس دقیق از word timestampهای Ajil با margin پایین درست (وقتی روشن باشد) | تست ON/OFF؛ همگامی < ۰٫۱s |
| T9.9 | تست واقعی مرورگر برای **هر** قابلیت جدید Ordak (model select، frame upload، capability inspect، reconcile، download) — نه فقط mock | لاگ + اسکرین‌شات هر قابلیت |

---

## 5. ترتیب اجرا و وابستگی‌ها

```
P0 ──► P1 ──┬──► P2 (Gemini)  ──┐
            └──► P3 (Flow)    ──┼──► P4 (حذف synthetic) ──► P5 ──► P6 ──► P7 ──► P8
                                │
        P5.1/P5.2 مستقل از P2/P3 ┘   (می‌تواند موازی جلو برود)
```

- **P1 قطعاً اول** — بدون آن P2/P3 قابل انجام نیستند.
- P2 و P3 موازی‌پذیرند (دو provider مستقل).
- P4 باید **بعد از** P2/P3 باشد، وگرنه پایپلاین بی‌fallback و بی‌provider سالم می‌ماند.
- P7 به لاگین کاربر گره خورده؛ بقیه بدون آن قابل تکمیل‌اند.

## 6. Definition of Done (سنجش‌پذیر)

- [ ] `grep -rn "allow_synthetic\|synthetic_fallback\|_dummy_" scripts/` = **صفر**
- [ ] هر `provider_receipts/*.json` دارای `model_verified=true` با شاهد UI (`actual_model_label` غیرتکراری با requested)
- [ ] `flow_opening_b.json`: `duration_actual≈4`, `resolution_actual=720p`, `aspect_actual=9:16`, roles = `[character_sheet, first_frame, last_frame]`
- [ ] هیچ receipt/لاگی نقش style در آپلود Flow ندارد + تست اثبات‌کننده
- [ ] blind duplicate Generate = صفر (تست restart)
- [ ] یک Short واقعی end-to-end: ChatGPT → Gemini(Pro) → Flow A/B → ElevenLabs → STT → trim → music → mixed render → QC
- [ ] drift همگام‌سازی هر beat < ۰٫۲۵s با گفتار واقعی
- [ ] تست‌ها: هیچ تست تاتولوژیک؛ پوشش §93-97
- [ ] `check_full_stack.py` بدون مقدار هاردکد و با exit code معنادار
- [ ] ordak + والد push شده، pointer آپدیت، بدون secret

## 7. تصمیم‌های نیازمند تأیید کاربر (بلاک‌کننده در نقطه‌ی خود)

**حل‌شده با دستور 2026-09-03:**
- ✅ ویدیوهای مصنوعی ۰۱۱–۰۱۷ → **حذف** (T0.6)
- ✅ پروکسی → **حذف کامل، اتصال مستقیم** (T0.7)
- ✅ پورت پنل → **4141** (T9.1)
- ✅ استراتژی سینک → تصمیم من، در §3.5 مکتوب شد
- ✅ Clip B ref → `book_design_sheet` جای `character_sheet` (طبق `book.txt`)

**باقی‌مانده:**
1. **۳ تصویر منبع دیگر (§2/§47)** — فقط `character_sheet` موجود است. اگر نفرستید،
   `book_design_sheet` را با Gemini از توصیف قفل‌شده‌ی `book.txt` می‌سازم و برای تأیید بصری
   به شما نشان می‌دهم (T2.6). بلاک‌کننده نیست.
2. **لاگین سه provider (T7.1)** — الان `logged_in: false` برای ChatGPT/Gemini/Flow.
   نیاز به ورود دستی شما در noVNC (پورت 4143). تا آن زمان P7/T9.9 معلق است؛
   P0–P6 و بخش‌های ساختاری P9 بدون آن کامل می‌شوند.
3. **سقف مصرف credit در Flow** — پیشنهاد: حداکثر ۲ جاب واقعی per clip در پذیرش اولیه.


## 8. دستورات تأیید وضعیت

```bash
cd /opt/YT_Video_Generation_Pipeline
# تست‌ها
PYTHONPATH=.venv/lib/python3.12/site-packages:scripts services/ordak/.venv/bin/python -m pytest tests/ -q
# وضعیت git
git status --porcelain=v2 --branch; git -C services/ordak status --short
# سلامت سرویس‌ها و providerها
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/diagnostics | python3 -m json.tool | head -40
python3 scripts/check_full_stack.py
# شاهد مصنوعی‌بودن خروجی‌های فعلی
grep -l FALLBACK_SYNTHETIC videos/*/pipeline/QH_RUNTIME_STATE.json
```

---

*این پلن مرجع اجراست. هر تسک انجام‌شده را با شاهد (خروجی دستور/تست) در همین فایل تیک بزنید.*

---

## 9. گزارش پیشرفت (به‌روزشده 2026-09-03)

### ✅ P0 — تثبیت پایه: کامل
| تسک | شاهد |
|-----|------|
| T0.1 | ordak commit `16217d7` + push به `AliBalash/ordak:yt-video-pipeline` ✅ |
| T0.2 | pointer آپدیت شد، parent commit `4bea092`؛ **push والد ناموفق** (پایین) ⚠️ |
| T0.3 | ۱۲ کلید به `.env` اضافه شد؛ `ordak-api` restart و health=ok ✅ |
| T0.4 | ۲۰ عضو جدید `ErrorCode` (FLOW_*/MODEL_*/INVALID_VIDEO_OUTPUT)؛ ۴۳ عضو = ۴۳ descriptor ✅ |
| T0.5 | policy یکی شد در `scripts/flow_reference_policy.py`؛ `content_projects` فقط re-export ✅ |
| T0.6 | ۷ ویدیوی مصنوعی (011–017) و ۵ job record پاک شدند ✅ |
| T0.7 | proxy از `deploy/remote-ordak/ordak-api.service` حذف؛ `YT_TELEGRAM_PROXY_ENABLED=false`؛ Chrome بدون `--proxy-server` ✅ |
| T0.8 | `book.txt` → `prompts/reference/book_transition_reference_prompt.txt`؛ prompt 09 بازنویسی شد ✅ |

### ✅ P1 — قرارداد انتقال پارامتر: کامل
| تسک | شاهد |
|-----|------|
| T1.1 | `GenerationOptions` + `ReferenceSpec` + `GenerationReceipt` در `app/schemas.py`؛ ۳ ستون DB + migration `20260716_0004` ✅ |
| T1.2 | `main.py` فیلد `role` per-upload می‌پذیرد؛ رد HTTP 422 برای style role / نقش نامشخص / عدم تطابق تعداد ✅ |
| T1.3 | `job_manager.create_job(references=, generation=)` + `_attach_generation_receipt` ✅ |
| T1.4 | hack `[MODEL:...]` از Ordak حذف شد؛ مدل از `job.generation.model` می‌آید ✅ |
| T1.5 | `scripts/ordak_jobs.py` (client تایپ‌دار: submit/wait/run/download + نقشه‌ی error→state) ✅ |

**تأیید زنده:** `generation` و `references` در `GET /api/jobs/<id>` persist می‌شوند
(`duration_seconds: 6`, `role: character_sheet`), و سه مسیر رد policy با HTTP 422 پاسخ می‌دهند.

### ✅ P2 (بخشی) — انتخاب مدل Gemini
`_select_gemini_image_model` بازنویسی شد: خواندن label از **خودِ کنترل مدل** (نه
`body.innerText`)، مقایسه‌ی نرمال‌شده، تأیید پس از انتخاب با ۴ بار تلاش،
و خطای ساختاری `MODEL_NOT_AVAILABLE`/`MODEL_SELECTION_FAILED` **بدون swallow**.
تست واحد: `Nano Banana Pro`→`nano_banana_pro`, `Nano Banana 2`→`nano_banana_2`,
`2.5 Flash`→`None` (هرگز به‌عنوان Nano Banana خوانده نمی‌شود).

### ⚠️ دو بلاکر که نیاز به اقدام شما دارد

1. **push والد رد شد** — حساب `gh` روی این سرور `AliBalash` است و به
   `M2002HR/YT_Video_Generation_Pipeline` دسترسی write ندارد:
   `remote: Permission to M2002HR/... denied to AliBalash` (HTTP 403).
   کامیت‌ها **لوکال محفوظ‌اند** (`4bea092`, `4aae51f`). برای اتوماسیون push والد یکی از این دو:
   - `AliBalash` را collaborator مخزن والد کنید، یا
   - یک token با دسترسی write برای `M2002HR` بدهید.
   (push ordak کار می‌کند و انجام شد.)

2. **لاگین provider‌ها تأیید نشده** — `/api/diagnostics` برای هر سه
   (`chatgpt`, `gemini`, `flow`) `logged_in: false` و `open_tabs: []` می‌دهد.
   `require_ready` الان صادقانه آن‌ها را «unverified» گزارش می‌کند (نه «ready»).
   برای هر تولید واقعی، ورود دستی در noVNC لازم است.

### ⏭ مرحله‌ی بعد
P3 (Flow واقعی: capability inspector، verify مدل/aspect/duration/resolution،
آپلود frame با نقش، credit safety، دانلود قطعی) → P4 (حذف synthetic) → P5 (سینک STT)
→ P6 (تست‌ها) → P9 (پنل/تلگرام/منابع).

---

## 10. کشف ساختار واقعی UI فلو (2026-09-03، مرورگر authenticated)

هر سه provider الان `logged_in: true` هستند (پس از باز شدن tab — تشخیص لاگین فقط با tab باز کار می‌کند).
DOM واقعی Flow را بررسی کردم؛ نتیجه، پایه‌ی پیاده‌سازی §18-21 شد:

**همه‌ی تنظیمات در یک منوی Radix پشت یک دکمه‌ی خلاصه‌اند:** `"Video · 720p · 6s crop_16_9 x2"`
(`aria-haspopup="menu"`, `data-state="closed|open"`). داخل آن هر تنظیم یک
`div[role="tablist"]` از `button[role="tab"]` است و گزینه‌ی فعال `aria-selected="true"` دارد
→ **read-back واقعی** برای تأیید، بدون هیچ اتکایی به `body.innerText`.

| گروه | گزینه‌های زنده |
|------|----------------|
| media type | `Image` \| `Video` |
| **reference mode** | `Frames` \| `Ingredients` — **متقابلاً انحصاری** |
| aspect | `9:16` \| `16:9` |
| model (dropdown) | `Omni 1.1 Flash` \| `Veo 3.1 - Lite` \| `Veo 3.1 - Fast` \| `Veo 3.1 - Quality` |
| resolution | `360p` \| `720p` |
| duration | `4s` \| `6s` \| `8s` \| `10s` |
| outputs | `x1` \| `x2` \| `x3` \| `x4` |

منو هزینه را هم نشان می‌دهد: `"Generating will use N credits"`.

### سه یافته‌ی مهم که پلن را تغییر می‌دهد

1. **`Frames` و `Ingredients` انحصاری‌اند.** پس Clip B نمی‌تواند هم‌زمان یک reference sheet
   کانونیکال و first/last frame داشته باشد. انتخاب درست: Clip B در حالت **Frames** با
   `Start = book_spread_frame` و `End = world_keyframe` (کلیک روی Frames، کنترل‌های
   «Start / swap_horiz Swap first and last frames / End» ظاهر می‌شوند). هویت کتاب از قبل
   داخل `book_spread_frame` ترکیب شده است. Clip A در حالت **Ingredients** با `character_sheet`.
   این با escape hatch خود §16 و «NO CHARACTERS» در `book.txt` سازگار است.
2. **`x2` پیش‌فرض است و هزینه را دو برابر می‌کند.** `x1` اجباری شد: هزینه‌ی
   `6s x2` = ۲۰ credit ولی `4s x1` = **۷ credit**.
3. **قابلیت‌ها به مدل وابسته‌اند.** با `Veo 3.1 - Lite` کنترل‌های resolution و duration
   کاملاً از منو **حذف می‌شوند**. این یک واقعیت capability است نه خرابی UI، پس به
   `MODEL_FEATURE_INCOMPATIBLE` نگاشت شد.

### ✅ P3 (بخش تنظیمات) — پیاده و روی UI واقعی تست شد
`services/ordak/app/automation/flow_settings.py` + helperهای CDP در `existing_chrome.py`
(`dispatch_mouse_click`, `dispatch_key`, `insert_text` — چون `element.click()` منوی Radix را
باز نمی‌کند و باید pointer event واقعی فرستاد).

نتیجه‌ی اجرای زنده (بدون هیچ تولید و بدون مصرف credit):
```
APPLY Clip B contract → 9:16, 4s, 720p, Frames, x1
  Flow reference_mode verified: Frames      (از Ingredients)
  Flow aspect_ratio  verified: 9:16         (از 16:9)
  Flow duration      verified: 4s           (از 6s)
  Flow outputs       verified: x1           (از x2)
  confirmed: Omni 1.1 Flash · 720p · 4s · 9:16 · Frames · x1 (credits: 7)   [4.9s]

switch Omni ↔ Veo 3.1 - Lite            → هر دو جهت verify شد
model 'best_available'                   → model_not_available
duration 12s                             → model_feature_incompatible
resolution 1080p                         → model_feature_incompatible
```



