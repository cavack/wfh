# نصب WaterfallHunter Project Sources v2 در ChatGPT

این فولدر عمداً متن کامل Skillها را کپی نمی‌کند. منبع اصلی و همیشه به‌روز Skillها GitHub مخزن `cavack/wfh` است و این بسته فقط Router/Catalog/Capability Map/Audit Summary/Project Instructions را نگه می‌دارد.

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

پاسخ صحیح باید Router v2 را مبنا قرار دهد، `engineering-orchestrator → skill-system-curator → verification-regression` را تشخیص دهد و قبل از تحلیل، Skillهای canonical را از GitHub فعلی بخواند.

## صحت بسته

`PROJECT-SOURCE-MANIFEST.json` فهرست Skillهای canonical و SHA-256 تمام فایل‌های overlay را نگه می‌دارد. نبودن Skill body در Drive عمدی است و از drift بین Drive و GitHub جلوگیری می‌کند.
