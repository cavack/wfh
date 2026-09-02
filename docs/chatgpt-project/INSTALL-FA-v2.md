# نصب WaterfallHunter Project Sources v2 در ChatGPT

این فولدر عمداً متن کامل Skillها را کپی نمی‌کند. منبع canonical Skillها GitHub مخزن `cavack/wfh` است. بسته شامل هفت فایل routing/install/provenance زیر است و Skill bodyها را تکرار نمی‌کند.

## محتوای دقیق بسته

- `00-WFH-CHATGPT-ROUTER-v2.md`
- `01-WFH-SKILL-CATALOG-v2.md`
- `02-WFH-CAPABILITY-MAP-v2.md`
- `03-WFH-SKILL-AUDIT-SUMMARY-v2.md`
- `PROJECT-INSTRUCTIONS-v2.txt`
- `INSTALL-FA-v2.md`
- `PROJECT-SOURCE-MANIFEST.json`

## نصب

1. پروژه WaterfallHunter را در ChatGPT باز کن.
2. بخش Sources / Add source را باز کن.
3. Google Drive را انتخاب کن.
4. فولدر `WFH ChatGPT Project Sources v2` را به Project Sources اضافه کن.
5. فایل `PROJECT-INSTRUCTIONS-v2.txt` را باز کن و متن آن را در Project Instructions پروژه قرار بده.
6. مطمئن شو GitHub connector برای همان حساب ChatGPT متصل است.

## تست نصب

در یک چت جدید داخل پروژه بنویس:

`برای ممیزی خود Skillهای WaterfallHunter فقط مسیر Council/Skill لازم را مشخص کن و قبل از نتیجه‌گیری SHA فعلی GitHub را resolve کن.`

پاسخ صحیح باید Router v2 را مبنا قرار دهد، route معتبر `skill_system_audit` را تشخیص دهد، `source_commit_sha` را یک بار از manifest freeze کند و همه Skillهای canonical انتخاب‌شده را از همان SHA در GitHub بخواند.

## صحت بسته

`PROJECT-SOURCE-MANIFEST.json` فهرست Skillهای canonical و SHA-256 تمام فایل‌های overlay را نگه می‌دارد. نبودن Skill body در Drive عمدی است و از drift بین Drive و GitHub جلوگیری می‌کند.

## خروجی byte-exact

برای ساخت بسته‌ی قابل آپلود، در checkout تمیز GitHub اجرا کن:

`python scripts/export_chatgpt_project_sources.py`

Exporter مسیر دلخواه از کاربر نمی‌گیرد و فقط در `.work/chatgpt-project-sources-v2` می‌نویسد. این محدودیت عمدی برای جلوگیری از path traversal و نوشتن خارج از محدوده است. سپس همان هفت فایل را با Google Drive connector در فولدر `WFH ChatGPT Project Sources v2` upload/update کن.

فایل تولیدشده‌ی `PROJECT-SOURCE-MANIFEST.json` علاوه بر SHA-256 فایل‌های overlay، `source_commit_sha`، `source_ref` و `source_worktree_dirty` را ثبت می‌کند. برای certification نهایی، `source_worktree_dirty` باید `false` باشد و SHA ثبت‌شده باید با Git object مورد تأیید یکسان باشد. در هر audit، همان SHA باید برای تمام fetchهای `SKILL.md` استفاده شود و تا پایان audit دوباره از branch متحرک resolve نشود.
