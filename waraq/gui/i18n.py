"""UI strings (English / Arabic) and Arabic display handling.

Tk on Windows hands text to GDI/Uniscribe, which shapes and orders Arabic
itself.  Tk on Linux/X11 does not, so there we pre-shape strings with
arabic-reshaper + python-bidi.  ``WARAQ_UI_SHAPING=1/0`` (or the setting in
the app) overrides the automatic choice.
"""
from __future__ import annotations

import os
import sys

from ..core.arabic import has_arabic, shape_for_display

S = {
    "app_title": ("Waraq PDF", "ورق PDF"),
    "tagline": ("Free • Offline • No watermark", "مجاني • بدون إنترنت • بدون علامة مائية"),
    "lang_toggle": ("العربية", "English"),
    "theme": ("Theme", "المظهر"),
    "tool_merge": ("Merge PDFs", "دمج ملفات PDF"),
    "tool_split": ("Split PDF", "تقسيم PDF"),
    "tool_organize": ("Organize pages", "ترتيب الصفحات"),
    "tool_images": ("Images ⇄ PDF", "صور ⇄ PDF"),
    "tool_compress": ("Compress PDF", "ضغط PDF"),
    "tool_convert": ("PDF to Word / Text", "PDF إلى Word / نص"),
    "tool_ocr": ("Scanned PDF (OCR)", "ملف ممسوح ضوئيا (OCR)"),
    "tool_sign": ("Signature / stamp", "توقيع / ختم"),
    "tool_security": ("Password", "كلمة المرور"),
    "pdf_file": ("PDF file", "ملف PDF"),
    "browse": ("Browse…", "استعراض…"),
    "add_files": ("Add files…", "إضافة ملفات…"),
    "remove": ("Remove", "حذف"),
    "up": ("Up", "لأعلى"),
    "down": ("Down", "لأسفل"),
    "clear": ("Clear", "مسح الكل"),
    "pages_opt": ("Pages (empty = all)", "الصفحات (فارغ = الكل)"),
    "pages_hint": ("e.g. 1-3, 5, 8-", "مثال: 1-3، 5، 8-"),
    "run_merge": ("Merge and save…", "دمج وحفظ…"),
    "run_split": ("Split…", "تقسيم…"),
    "split_each": ("Every page alone", "كل صفحة في ملف"),
    "split_every": ("Every N pages", "كل N صفحات"),
    "split_ranges": ("By ranges (one file each)", "حسب النطاقات (ملف لكل نطاق)"),
    "split_extract": ("Extract pages to one file", "استخراج صفحات في ملف واحد"),
    "n_pages": ("N", "N"),
    "ranges": ("Ranges", "النطاقات"),
    "load_pages": ("Load pages", "عرض الصفحات"),
    "rot_left": ("⟲ Rotate left", "⟲ تدوير لليسار"),
    "rot_right": ("⟳ Rotate right", "⟳ تدوير لليمين"),
    "del_page": ("Delete", "حذف"),
    "move_prev": ("Move earlier", "تقديم"),
    "move_next": ("Move later", "تأخير"),
    "select_all": ("Select all", "تحديد الكل"),
    "save_as": ("Save as…", "حفظ باسم…"),
    "deleted": ("deleted", "محذوفة"),
    "page_n": ("Page {n}", "صفحة {n}"),
    "img_to_pdf": ("Images → PDF", "صور ← PDF"),
    "pdf_to_img": ("PDF → images", "PDF ← صور"),
    "add_images": ("Add images…", "إضافة صور…"),
    "page_size": ("Page size", "حجم الصفحة"),
    "size_fit": ("Same as image", "مثل الصورة"),
    "margin": ("Margin (mm)", "الهامش (مم)"),
    "make_pdf": ("Create PDF…", "إنشاء PDF…"),
    "dpi": ("Quality (DPI)", "الجودة (DPI)"),
    "format": ("Format", "الصيغة"),
    "export_images": ("Export images…", "تصدير الصور…"),
    "preset": ("Compression level", "مستوى الضغط"),
    "p_light": ("Light (best quality)", "خفيف (أفضل جودة)"),
    "p_balanced": ("Balanced", "متوازن"),
    "p_strong": ("Strong (smallest)", "قوي (أصغر حجم)"),
    "run_compress": ("Compress and save…", "ضغط وحفظ…"),
    "compress_result": ("{before} → {after}  (saved {pct}%)", "{before} ← {after}  (توفير {pct}%)"),
    "compress_none": ("This file cannot be made smaller; the original was kept.",
                      "لا يمكن تصغير هذا الملف أكثر؛ تم الإبقاء على الأصل."),
    "ocr_mode": ("Scanned pages", "الصفحات الممسوحة"),
    "ocr_auto": ("OCR automatically", "تعرف تلقائي (OCR)"),
    "ocr_no": ("Text layer only", "النص الموجود فقط"),
    "ocr_force": ("OCR every page", "OCR لكل الصفحات"),
    "extract": ("Extract and preview", "استخراج ومعاينة"),
    "preview": ("Preview (check before saving)", "معاينة (راجع النص قبل الحفظ)"),
    "save_docx": ("Save Word (.docx)…", "حفظ Word ‏(.docx)…"),
    "save_txt": ("Save text (.txt)…", "حفظ نص (.txt)…"),
    "layout": ("Layout", "التنسيق"),
    "layout_par": ("Paragraphs", "فقرات"),
    "layout_lines": ("Keep lines", "حفظ الأسطر"),
    "ocr_engine": ("OCR engine", "محرك التعرف"),
    "ocr_status_ok": ("Ready: {name}", "جاهز: {name}"),
    "ocr_status_missing": ("No Arabic OCR found. Install the Windows Arabic language pack or Tesseract (see manual).",
                           "لا يوجد محرك OCR عربي. ثبّت حزمة اللغة العربية في ويندوز أو Tesseract (راجع الدليل)."),
    "run_ocr": ("Recognize text", "تعرّف على النص"),
    "searchable": ("Make searchable PDF…", "إنشاء PDF قابل للبحث…"),
    "sig_image": ("Signature / stamp image", "صورة التوقيع / الختم"),
    "sig_text": ("Or text", "أو نص"),
    "sig_pages": ("Pages", "الصفحات"),
    "pg_last": ("Last page", "آخر صفحة"),
    "pg_first": ("First page", "أول صفحة"),
    "pg_all": ("All pages", "كل الصفحات"),
    "position": ("Position", "الموضع"),
    "pos_bottom-right": ("Bottom right", "أسفل اليمين"),
    "pos_bottom-left": ("Bottom left", "أسفل اليسار"),
    "pos_bottom-center": ("Bottom center", "أسفل الوسط"),
    "pos_top-right": ("Top right", "أعلى اليمين"),
    "pos_top-left": ("Top left", "أعلى اليسار"),
    "pos_top-center": ("Top center", "أعلى الوسط"),
    "pos_center": ("Center", "الوسط"),
    "width_pt": ("Width", "العرض"),
    "remove_white": ("Make white background transparent", "إزالة الخلفية البيضاء"),
    "preview_btn": ("Preview", "معاينة"),
    "run_sign": ("Sign and save…", "توقيع وحفظ…"),
    "add_pw": ("Add password", "إضافة كلمة مرور"),
    "remove_pw": ("Remove password", "إزالة كلمة المرور"),
    "new_pw": ("New password", "كلمة المرور الجديدة"),
    "confirm_pw": ("Confirm password", "تأكيد كلمة المرور"),
    "current_pw": ("Current password", "كلمة المرور الحالية"),
    "allow_print": ("Allow printing", "السماح بالطباعة"),
    "allow_copy": ("Allow copying text", "السماح بنسخ النص"),
    "run_protect": ("Protect and save…", "حماية وحفظ…"),
    "run_unlock": ("Unlock and save…", "فك الحماية وحفظ…"),
    "pw_note": ("Waraq only removes passwords you know. It does not crack passwords.",
                "ورق يزيل فقط كلمة مرور تعرفها، ولا يكسر كلمات المرور."),
    "pw_mismatch": ("Passwords do not match", "كلمتا المرور غير متطابقتين"),
    "ask_pw_title": ("Password needed", "مطلوب كلمة مرور"),
    "ask_pw": ("“{name}” is protected. Enter its password:", "الملف «{name}» محمي. أدخل كلمة المرور:"),
    "ok": ("OK", "موافق"),
    "cancel": ("Cancel", "إلغاء"),
    "working": ("Working…", "جاري العمل…"),
    "done": ("Done ✓", "تم ✓"),
    "saved_to": ("Saved:{path}", "تم الحفظ:{path}"),
    "open_folder": ("Open folder", "فتح المجلد"),
    "need_file": ("Choose a PDF file first", "اختر ملف PDF أولا"),
    "need_two": ("Add at least one file", "أضف ملفًا واحدًا على الأقل"),
    "drop_hint": ("Choose files with the button", "اختر الملفات بالزر"),
    "err_bad_pdf": ("This is not a valid PDF file.", "هذا ليس ملف PDF صالحًا."),
    "err_not_found": ("File not found.", "الملف غير موجود."),
    "err_needs_password": ("This file is password protected.", "هذا الملف محمي بكلمة مرور."),
    "err_wrong_password": ("Wrong password.", "كلمة المرور غير صحيحة."),
    "err_bad_range": ("Page numbers are not valid.", "أرقام الصفحات غير صحيحة."),
    "err_no_pages": ("The result would have no pages.", "الناتج لن يحتوي على أي صفحة."),
    "err_not_encrypted": ("This file has no password.", "هذا الملف ليس له كلمة مرور."),
    "err_ocr_missing": ("No Arabic OCR engine found (see manual).", "لا يوجد محرك OCR عربي (راجع الدليل)."),
    "err_generic": ("Error: {msg}", "خطأ: {msg}"),
    "scanned_note": ("{n} scanned page(s) were read with OCR - please review.",
                     "تمت قراءة {n} صفحة ممسوحة بالتعرف الضوئي - راجعها من فضلك."),
    "scanned_no_ocr": ("{n} page(s) look scanned and have no text. Use OCR.",
                       "{n} صفحة تبدو ممسوحة ضوئيا ولا تحتوي نصًا. استخدم OCR."),
    "files_n": ("{n} file(s), {p} page(s)", "{n} ملف، {p} صفحة"),
    "settings_shaping": ("Fix Arabic display", "إصلاح عرض العربية"),
    "about": ("Version {v} - all processing happens on this computer.",
              "الإصدار {v} - كل المعالجة تتم على جهازك."),
}

from .strings_viewer import VIEWER as _VIEWER  # noqa: E402

S.update(_VIEWER)

_LANG = "ar"
_FORCE_SHAPING = None  # None = automatic


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "ar" if lang == "ar" else "en"


def lang() -> str:
    return _LANG


def is_rtl() -> bool:
    return _LANG == "ar"


def set_shaping(value) -> None:
    global _FORCE_SHAPING
    _FORCE_SHAPING = value


def shaping_enabled() -> bool:
    env = os.environ.get("WARAQ_UI_SHAPING")
    if env in ("0", "1"):
        return env == "1"
    if _FORCE_SHAPING is not None:
        return bool(_FORCE_SHAPING)
    return sys.platform != "win32"


def ui(text: str) -> str:
    """Prepare any (logical-order) string for a Tk widget."""
    if not text or not has_arabic(text):
        return text
    if shaping_enabled():
        return shape_for_display(text, base_dir="R")
    # Windows: GDI shapes; a leading RLM makes the paragraph right-to-left
    return "\u200f" + text


def with_icon(icon: str, text: str) -> str:
    """Icon at the reading start: left in English, right in Arabic."""
    if not is_rtl():
        return f"{icon}  {ui(text)}"
    if shaping_enabled():
        return shape_for_display(text, base_dir="R") + "  " + icon
    return "\u200f" + icon + "  " + text


def t(key: str, **kw) -> str:
    en, ar = S[key]
    s = ar if _LANG == "ar" else en
    if kw:
        s = s.format(**kw)
    return ui(s)


def raw(key: str, **kw) -> str:
    en, ar = S[key]
    s = ar if _LANG == "ar" else en
    return s.format(**kw) if kw else s


def error_text(exc) -> str:
    code = getattr(exc, "code", None)
    key = f"err_{code}"
    if code and key in S:
        return t(key)
    return t("err_generic", msg=str(exc))
