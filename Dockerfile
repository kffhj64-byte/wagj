# استخدام بيئة بايثون رسمية من مايكروسوفت تدعم متصفحات Playwright
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# إعداد مجلد العمل
WORKDIR /app

# نسخ ملف المكاتب وتثبيته
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح كروم الوهمي
RUN playwright install chromium

# نسخ باقي ملفات المشروع
COPY . .

# تشغيل ملف البوت
CMD ["python", "bot.py"]
