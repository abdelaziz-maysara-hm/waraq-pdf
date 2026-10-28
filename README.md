# ورق PDF — Waraq PDF

<div dir="rtl">

**ورق** برنامج مجاني لملفات PDF على ويندوز. يعمل بدون إنترنت، ولا يرفع ملفاتك لأي مكان، ولا يضع علامة مائية. واجهته عربية أولًا، ويمكن تحويلها إلى الإنجليزية بزر واحد.

## الأدوات

| الأداة | ماذا تفعل |
|---|---|
| دمج | دمج عدة ملفات PDF في ملف واحد بالترتيب الذي تختاره |
| تقسيم | كل صفحة في ملف، أو كل N صفحات، أو حسب نطاقات مثل `1-3, 5, 8-10`، أو استخراج صفحات في ملف واحد |
| ترتيب الصفحات | صور مصغّرة للصفحات: تدوير، حذف، تقديم وتأخير |
| صور ⇄ PDF | تحويل صور (JPG/PNG/…) إلى PDF، وتصدير صفحات PDF كصور |
| ضغط | ثلاث درجات: خفيف، متوازن، قوي |
| PDF إلى Word / نص | استخراج النص العربي **بالترتيب الصحيح** (بدون حروف مقلوبة أو مقطّعة)، مع معاينة قبل الحفظ |
| التعرّف الضوئي (OCR) | قراءة الملفات الممسوحة ضوئيًا: محرّك ويندوز المدمج أو Tesseract |
| توقيع / ختم | إضافة صورة توقيع أو ختم أو نص في موضع تختاره، مع إزالة الخلفية البيضاء |
| كلمة المرور | إضافة كلمة مرور، أو إزالتها **إذا كنت تعرفها** (البرنامج لا يكسر كلمات المرور) |

## التشغيل

- حمّل `WaraqPDF.exe` وشغّله. لا يحتاج إلى تثبيت.
- البرنامج غير موقّع رقميًا حتى الآن، لذلك قد يعرض ويندوز رسالة SmartScreen. اضغط «مزيد من المعلومات» ثم «تشغيل على أي حال».
- الدليل الكامل في [MANUAL.md](MANUAL.md).

</div>

---

**Waraq** ("paper") is a free, offline, Arabic-first PDF toolbox for Windows.
It does not upload anything, adds no watermark, and has an Arabic/English UI with
right-to-left layout.

**Tools:** merge · split (each / every N / ranges / extract) · organize pages with
thumbnails (rotate, delete, reorder) · images ⇄ PDF · compress (3 presets) ·
Arabic-safe PDF → Word/TXT with a preview · OCR (Windows built-in OCR or
Tesseract) · signature / stamp · add or remove a password (known password only).
All tools are also available from the command line: `WaraqPDF.exe --help`.

### Why the Arabic extraction is different

Most PDF tools return Arabic in *visual* order. Words come out reversed,
letters come out in presentation forms (ﻣﺮﺣﺒﺎ), and harakat or spaces end up in
the wrong place. Waraq rebuilds the logical text from glyph positions. It
converts presentation forms back to normal letters, attaches marks
geometrically, and applies the bidi algorithm in reverse per line. The Word
file it writes has right-to-left paragraphs. Measured results are in
[docs/benchmark.md](docs/benchmark.md). On the test files, every line matches
the source once harakat are ignored. On a real MS-Word PDF, 98.4% of words
are found in the reference vocabulary, against 96.0% for pypdf and 4.4% for
pdfminer.

### Build from source

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m waraq                 # GUI
python -m waraq --help          # CLI
python tests/make_fixtures.py && python -m pytest -q tests
pyinstaller --onefile --windowed --name WaraqPDF --collect-all customtkinter ^
  --collect-all pypdfium2 --collect-submodules winrt --add-data "waraq/assets;waraq/assets" waraq_app.py
```

The GitHub Actions workflow `.github/workflows/build-windows.yml` runs the
tests on `windows-latest` and uploads `WaraqPDF.exe` as an artifact.

### Status

Version 0.1.0, MVP. See [MANUAL.md](MANUAL.md#limitations) for known
limitations. Licence: **not chosen yet**, see [LICENSE-NOTE.md](LICENSE-NOTE.md).
