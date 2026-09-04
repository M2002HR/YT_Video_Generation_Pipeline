# HANDOFF — Question Harvest (برای ادامه از چت جدید)

> تاریخ: 2026-09-04 · branch: `ordak` · آخرین کامیت والد: `d06ac13` · ordak: `b5b417f` (pushed)

---

## پرامپت شروع چت بعدی (کپی کن)

```
ادامه‌ی پیاده‌سازی Question Harvest در /opt/YT_Video_Generation_Pipeline (branch ordak).

اول این سه فایل را کامل بخوان:
1. HANDOFF.md            ← وضعیت فعلی، کارهای مانده، دستورات تأیید
2. IMPLEMENTATION_PLAN.md ← پلن کامل ۴۷ تسک + §3.5 قرارداد ورکفلو + §10 ساختار واقعی UI فلو
3. mater_prompt.md        ← اسپک اصلی ۱۲۰ بخش

CURRENT_STATE.md قدیمی (2026-09-02) و بخش زیادی از آن منقضی است — به آن اعتماد نکن.

قواعد مطلق: تصویر=Gemini فقط، ویدیو=Google Flow فقط، هیچ provider fallback،
هیچ synthetic fallback، هیچ style sheet به Flow، بدون پروکسی (اتصال مستقیم).
هر مرحله‌ای که prompt دارد باید از ChatGPT با Ordak گرفته شود.
گیت را خودت مدیریت کن با پیام‌های کوتاه. سریع و کامل جلو برو.

از P3 ادامه بده: آپلود frame با نقش (Start/End) + credit safety + دانلود قطعی.
```

---

## ۱) چه چیزی درست شد (تأییدشده با اجرا)

| فاز | وضعیت | شاهد |
|-----|-------|------|
| **P0** تثبیت | ✅ | ۲۰ ErrorCode جدید (FLOW_*/MODEL_*)، policy یکی شد، ۷ ویدیوی مصنوعی پاک، پروکسی حذف، ۱۲ کلید env |
| **P1** قرارداد پارامتر | ✅ | `GenerationOptions`+`ReferenceSpec`+`GenerationReceipt`، ۳ ستون DB، migration `20260716_0004`، `main.py` نقش per-upload، `scripts/ordak_jobs.py` |
| **P2** مدل Gemini | ⚠️ نیمه | `_select_gemini_image_model` بازنویسی شد (read-back واقعی + خطای ساختاری). **مسیر Pro مانده** |
| **P3** تنظیمات Flow | ⚠️ نیمه | `app/automation/flow_settings.py` روی UI واقعی تست شد. **frame/credit/download مانده** |

### فایل‌های کلیدی جدید
```
scripts/ordak_jobs.py                              client تایپ‌دار (submit/wait/run/download + error→state)
scripts/flow_reference_policy.py                   تنها منبع policy (parent)
services/ordak/app/flow_policy.py                  enforcement سمت سرور
services/ordak/app/automation/flow_settings.py     خواندن/اعمال/تأیید تنظیمات Flow
services/ordak/app/automation/existing_chrome.py   + dispatch_mouse_click / dispatch_key / insert_text (CDP)
projects/question_harvest/prompts/reference/book_transition_reference_prompt.txt   (= book.txt قدیم)
projects/question_harvest/prompts/pipeline/09_book_transition_video_prompt_writer.md  (بازنویسی کامل)
```

---

## ۲) ساختار واقعی UI فلو (کشف‌شده، پایه‌ی کار)

همه‌ی تنظیمات در **یک منوی Radix** پشت دکمه‌ی `"Video · 720p · 6s crop_16_9 x2"`.
هر تنظیم `div[role="tablist"]` با `button[role="tab"]`، فعال = `aria-selected="true"`.

| گروه | گزینه‌ها |
|------|---------|
| media type | `Image` \| `Video` |
| **reference mode** | `Frames` \| `Ingredients` — **انحصاری** |
| aspect | `9:16` \| `16:9` |
| model | `Omni 1.1 Flash` \| `Veo 3.1 - Lite` \| `Veo 3.1 - Fast` \| `Veo 3.1 - Quality` |
| resolution | `360p` \| `720p` |
| duration | `4s` \| `6s` \| `8s` \| `10s` |
| outputs | `x1` \| `x2` \| `x3` \| `x4` |

**سه قاعده‌ی حاصل:**
1. Clip A = حالت `Ingredients` + `character_sheet` · Clip B = حالت `Frames` + `Start=book_spread_frame` + `End=world_keyframe` (بدون character، طبق book.txt)
2. `outputs=x1` اجباری — `6s x2`=۲۰ credit ولی `4s x1`=**۷ credit**
3. `Veo 3.1 - Lite` کنترل resolution/duration ندارد → `MODEL_FEATURE_INCOMPATIBLE`

**پیام مهم:** `element.click()` منوی Radix را باز نمی‌کند؛ باید `dispatch_mouse_click` (CDP Input) استفاده شود.

---

## ۳) کارهای مانده (به ترتیب)

### P3 — بقیه‌ی Flow (اولویت ۱)
- [ ] `flow_worker.py` را با `flow_settings.apply_settings()` بازنویسی کن (کد فعلی `aspect`/`duration` را هاردکد می‌کند و خطای verify را می‌بلعد — خط ~۴۲۳)
- [ ] آپلود frame: کلیک `Frames` → کنترل‌های `Start` / `End` ظاهر می‌شوند → آپلود با نقش؛ خطای `FLOW_FRAME_UPLOAD_FAILED`
- [ ] credit safety §22: persist fingerprint (`submission_fingerprint()` در `ordak_jobs.py` آماده است) **قبل از** Generate؛ reconcile اجباری قبل از هر retry؛ blind retry = صفر
- [ ] دانلود قطعی: `Browser.setDownloadBehavior` به `<out>/<job_id>/` (کد فعلی هر mp4 با mtime<180s را از `/tmp` برمی‌دارد — ریسک فایل اشتباه)
- [ ] `receipt` واقعی از `AppliedSettings` + ffprobe

### P2 — بقیه‌ی Gemini (اولویت ۲)
- [ ] مسیر Nano Banana Pro: submit → نتیجه‌ی اول → یافتن کنترل «Redo with Pro» → تمایز مثبت نتیجه (node/SHA/dimension) → فقط Pro بپذیر، وگرنه `MODEL_NOT_AVAILABLE`
- [ ] `book_design_sheet.png` کانونیکال با Gemini Pro از هویت قفل‌شده‌ی `book_transition_reference_prompt.txt`
- [ ] validation دانلود §32 + receipt واقعی §8

### P4 — حذف synthetic (اولویت ۳)
- [ ] `grep -rn "allow_synthetic\|_dummy_\|synthetic_fallback" scripts/` باید صفر شود
- [ ] `run_question_harvest_pipeline.py` بازنویسی روی `ordak_jobs.OrdakJobs` + state machine §81
- [ ] حذف جعل STT در `run_full_video_pipeline_qh_wrapper.py:153-156` (`backend="ajil"` دستی ست می‌شود)
- ⚠️ `build_flow_uploads(clip="B", ...)` الان امضایش عوض شده (`book_design_sheet=`) — call site در pipeline خط ~۷۰۹ باید آپدیت شود

### P5 — سینک Ajil
- [ ] script writer → JSON با segment واقعی (`opening_spark`/`book_transition`/`body[]`)
- [ ] `align_beats.py` → `timing/OPENING_TIMING.json` با `spark_end`/`transition_end`
- [ ] `trim_opening_clips.py` از word timing واقعی (الان از **نسبت تعداد کلمه** حساب می‌کند)
- [ ] `build_timeline.py` حذف `scale = remaining/audio_duration` (سینک را خراب می‌کند)
- [ ] `render_video.py` fail-fast اگر ویدیو کوتاه‌تر از duration بیت

### P6 — تست‌ها
- [ ] `test_model_lock.py` تاتولوژیک است (`assert "720p" != "360p"`) → تست رفتار واقعی
- [ ] `check_full_stack.py` مقدار هاردکد `True` دارد
- [ ] integration media (۷ سناریو §97) + resume tests

### P9 — پنل/تلگرام/منابع
- [ ] پنل روی **4141** (nginx از قبل listen دارد) + UI/UX تک‌صفحه‌ای بهتر + status badge provider + tail لاگ
- [ ] notify تلگرام برای همه‌ی stageهای QH (الان QH فقط ۱ نقطه، completion صفر؛ `run_full_video_pipeline.py` ۲۷ نقطه دارد — همان سطح)
- [ ] بودجه‌ی منابع: **سرور فقط ۲ vCPU / ۷GB** → `threads=max(1,round(nproc*0.8))` + `nice`/`ionice` + `RENDER_STATS.json`
- [ ] git به‌عنوان stage اتوماسیون بعد از QC

---

## ۴) بلاکر

**push مخزن والد رد می‌شود** — `gh` روی سرور با حساب `AliBalash` است، به
`M2002HR/YT_Video_Generation_Pipeline` دسترسی write ندارد (HTTP 403).
کامیت‌ها لوکال محفوظ. راه‌حل: `AliBalash` را collaborator کن، یا token با write بده.
(push به `AliBalash/ordak` کار می‌کند و انجام شده.)

---

## ۵) دستورات تأیید

```bash
cd /opt/YT_Video_Generation_Pipeline

# تست‌ها (باید ۶۵ pass)
PYTHONPATH=.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -q

# سلامت + لاگین provider (هر سه باید logged_in=True؛ اگر نه، tab باز کن)
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/diagnostics | python3 -c "
import json,sys
for p,s in (json.load(sys.stdin).get('provider_sessions') or {}).items():
    print(p, s.get('logged_in'), s.get('login_state'), len(s.get('open_tabs') or []))"

# اگر tab نبود:
curl -s 'http://127.0.0.1:9222/json/new?https://gemini.google.com/app'
curl -s 'http://127.0.0.1:9222/json/new?https://labs.google/fx/tools/flow'

# خواندن capability زنده‌ی Flow (بدون مصرف credit)
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.flow_settings as fs
i=[t for t in list_google_chrome_tabs() if 'flow/project/' in (getattr(t,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(i,'window_id',0), tab_id=getattr(i,'tab_id',0), target_id=getattr(i,'target_id',None))
print(json.dumps(fs.read_capabilities(r).to_dict(), indent=1)); fs.close_settings_menu(r)
PY

# گیت
git log --oneline -6; git -C services/ordak log --oneline -3
```

**نکته:** برای Flow باید یک tab روی `flow/project/<id>` باز باشد (نه صفحه‌ی لیست پروژه‌ها).
یک پروژه‌ی موجود: `https://labs.google/fx/tools/flow/project/36400b0f-605e-484b-95c5-48e727479dfc`

---

## ۶) یادآوری قواعد که نباید نقض شوند

- تصویر = **Gemini فقط** · ویدیو = **Google Flow فقط** · متن = **ChatGPT فقط** (همه با Ordak)
- **هیچ** provider fallback · **هیچ** model fallback · **هیچ** synthetic fallback
- به Flow **هیچ style sheet** نمی‌رود (`world_style_anchor`, `home_style`, `mood_board`, …)
- `book_spread_frame` و `world_keyframe` مجازند چون **frame input** صحنه‌اند نه style sheet
- Gemini **می‌تواند** style reference بگیرد (§30) — این محدودیت فقط برای Flow است
- بدون پروکسی، اتصال مستقیم
- blind duplicate Generate = **صفر** (credit مصرف می‌شود)
- هیچ ادعای «کامل شد» بدون تست واقعی مرورگر
