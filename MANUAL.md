# دليل الاستخدام — Waraq PDF Manual

<div dir="rtl">

## البداية
شغّل `WaraqPDF.exe`. الأدوات في القائمة الجانبية. زر **English/عربي** في الأسفل يغيّر لغة الواجهة، وزر ☀/☾ يغيّر بين الوضع الفاتح والداكن. البرنامج يحفظ اختياراتك في `%APPDATA%\Waraq\settings.json`.

كل أداة تعمل بنفس الطريقة: اختر الملف ← اضبط الخيارات ← اضغط الزر ← اختر مكان الحفظ. البرنامج لا يكتب فوق الملف الأصلي أبدًا. إذا كان الملف محميًا بكلمة مرور، يطلبها البرنامج مرة واحدة ويتذكّرها حتى تغلقه.

- **دمج:** أضف الملفات، ورتّبها بزرَّي ▲ و▼، ثم اضغط «دمج وحفظ».
- **تقسيم:** اختر «كل صفحة في ملف»، أو «كل N صفحات»، أو «حسب النطاقات» (مثال `1-3, 5, 8-10`، وكل نطاق يصبح ملفًا منفصلًا)، أو «استخراج صفحات في ملف واحد».
- **ترتيب الصفحات:** اضغط «عرض الصفحات». اضغط على صورة الصفحة لتحديدها أو إلغاء تحديدها، ويمكنك تحديد أكثر من صفحة. بعدها دوّر أو احذف أو قدّم أو أخّر، ثم اضغط «حفظ باسم».
- **صور ⇄ PDF:** في تبويب «صور إلى PDF» يمكن جعل حجم الصفحة على قدر الصورة، أو A4، أو Letter، مع هامش. في تبويب «PDF إلى صور» تختار الدقة (DPI) والصيغة PNG أو JPG.
- **ضغط:** «خفيف» يحافظ على الجودة، و«متوازن» مناسب لمعظم الملفات، و«قوي» ينتج أصغر حجم. البرنامج يعرض الحجم قبل الضغط وبعده. إذا لم يقلّ الحجم، يبقى الملف الأصلي كما هو.
- **PDF إلى Word / نص:** اضغط «استخراج ومعاينة» وراجع النص، ثم احفظه كـ docx أو txt. اختر طريقة التنسيق: «فقرات» تدمج الأسطر في فقرات، و«حفظ الأسطر» تُبقي كل سطر كما هو. خيار الصفحات الممسوحة:
  - «تلقائي»: يستخدم OCR للصفحات التي لا تحتوي على نص.
  - «إجباري»: يستخدم OCR لكل الصفحات. استعمله عندما يظهر النص المستخرج حروفًا غريبة، لأن خط الملف تالف.
  - «بدون».
- **OCR:** يستخرج النص من ملف ممسوح ضوئيًا، أو ينشئ PDF قابلًا للبحث (هذه الخاصية تحتاج Tesseract).
- **توقيع / ختم:** اختر صورة التوقيع أو اكتب نصًا، ثم حدّد الصفحات (الأولى، أو الأخيرة، أو الكل، أو أرقام صفحات) والموضع والعرض. «إزالة الخلفية البيضاء» تجعل خلفية الصورة شفافة. اضغط «معاينة» قبل الحفظ.
- **كلمة المرور:** «إضافة» تشفّر الملف بـ AES-256، ويمكنك منع الطباعة أو النسخ. «إزالة» تحتاج كلمة المرور الصحيحة، فالبرنامج **لا** يكسر كلمات المرور.

## تفعيل التعرّف الضوئي (OCR) للعربية
يختار البرنامج أول محرّك متاح:
1. **OCR المدمج في ويندوز 10/11:** افتح الإعدادات ← الوقت واللغة ← اللغة والمنطقة ← أضف «العربية»، وتأكد أن «التعرّف الضوئي/الكتابة اليدوية» ضمن مكوّنات اللغة.
2. **Tesseract** (دقته أعلى غالبًا، ويدعم إنشاء PDF قابل للبحث): ثبّت Tesseract لويندوز (مثل نسخة UB Mannheim) واختر أثناء التثبيت حزمة اللغة العربية `ara`. يبحث عنه البرنامج في `Program Files` وفي `PATH`، أو في المسار الذي تضعه في متغيّر البيئة `WARAQ_TESSERACT`.

</div>

## Command line

Every tool is available from the command line: `WaraqPDF.exe <command> --help`
(or `python -m waraq` when running from source). Errors go to stderr as
`error[code]: message` and the exit code is 2.

```
WaraqPDF info file.pdf
WaraqPDF merge a.pdf b.pdf -o out.pdf
WaraqPDF split in.pdf -o outdir --mode ranges --ranges "1-3,5,8-10"
WaraqPDF rotate in.pdf -o out.pdf --angle 90 --pages 1,3
WaraqPDF delete in.pdf -o out.pdf --pages 2-4
WaraqPDF reorder in.pdf -o out.pdf --order 3,1,2
WaraqPDF img2pdf *.jpg -o out.pdf --page-size a4 --margin-mm 10
WaraqPDF pdf2img in.pdf -o outdir --dpi 150 --format png
WaraqPDF compress in.pdf -o out.pdf --preset balanced      # light|balanced|strong
WaraqPDF todocx in.pdf -o out.docx --layout paragraphs --ocr auto
WaraqPDF totext in.pdf -o out.txt
WaraqPDF ocr scan.pdf -o out.txt [--engine windows|tesseract] [--searchable]
WaraqPDF sign in.pdf -o out.pdf --image sig.png --pages last --position bottom-right --width 150 --remove-white
WaraqPDF protect in.pdf -o out.pdf --user-password 1234 [--no-print] [--no-copy]
WaraqPDF unlock in.pdf -o out.pdf --password 1234
```

## Limitations

- **Arabic PDF → Word:** text is rebuilt from glyph positions. Where the PDF
  producer mapped a glyph to the wrong Unicode character, the error is copied.
  The usual case is tanween or other harakat in ligatures, so a line can differ
  from the source in harakat only. The letters still come out right. PDFs with
  broken font encodings produce garbage in every tool. Use *Force OCR* for
  those, because Waraq does not detect garbage text layers on its own yet.
  Tables, columns, images and fonts are not reproduced in the Word file, only
  right-to-left paragraphs of text.
- **OCR:** Tesseract sometimes puts short English or number runs inside
  Arabic lines in the wrong order. Handwriting is not supported. Making a
  searchable PDF needs Tesseract.
- **Compress:** only images are re-encoded (JPEG) and streams recompressed.
  Fonts are not subset. Files that are mostly text shrink less.
- **Password:** only removing a password you know is supported. Certificate
  (public-key) encryption is not supported.
- **Signature:** this is a visual stamp, not a cryptographic digital signature.
- The exe is not code-signed, so SmartScreen will warn the first time it runs.
