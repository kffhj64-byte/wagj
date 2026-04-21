import asyncio
import os
import random
import re
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# --- الإعدادات الأساسية ---
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
MY_TELEGRAM_ID = int(os.environ.get('MY_TELEGRAM_ID', 8435344041))
PORT = int(os.environ.get('PORT', 3000))

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# --- إدارة حالات المحادثة (FSM) ---
class FormSteps(StatesGroup):
    get_manual_code = State()
    get_phone = State()
    get_email = State()
    get_message = State()
    confirm = State()

# --- الواجهات والأزرار ---
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text='🚀 إرسال طلب دعم جديد'), KeyboardButton(text='📊 حالة السيرفر')],
        [KeyboardButton(text='❌ إلغاء العملية')]
    ],
    resize_keyboard=True
)

country_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text='🇾🇪 اليمن (+967)', callback_data='set_code_+967'), InlineKeyboardButton(text='🇸🇦 السعودية (+966)', callback_data='set_code_+966')],
        [InlineKeyboardButton(text='🇪🇬 مصر (+20)', callback_data='set_code_+20'), InlineKeyboardButton(text='🌐 رمز آخر (يدوي)', callback_data='set_code_manual')],
        [InlineKeyboardButton(text='🚫 إلغاء', callback_data='cancel_task')]
    ]
)

# --- فلتر حماية: السماح للمدير فقط ---
@dp.message.outer_middleware()
async def auth_middleware(handler, event, data):
    if event.from_user.id != MY_TELEGRAM_ID:
        return
    return await handler(event, data)

@dp.callback_query.outer_middleware()
async def auth_callback_middleware(handler, event, data):
    if event.from_user.id != MY_TELEGRAM_ID:
        return
    return await handler(event, data)

# --- أوامر البوت الأساسية ---
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>مرحباً بك سيدي في لوحة التحكم VIP 👑</b>\n\n<i>النظام مبني على Python وجاهز للعمل على Render.</i>",
        reply_markup=main_menu
    )

@dp.message(F.text == '📊 حالة السيرفر')
async def server_status(message: Message):
    await message.answer("<b>📊 حالة النظام:</b>\nالمتصفح: مستعد للعمل 🟢\nالخادم (Render): متصل 🟢")

@dp.message(F.text == '❌ إلغاء العملية')
async def cancel_process(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ تم تنظيف الجلسة والعودة للقائمة الرئيسية.", reply_markup=main_menu)

@dp.message(F.text == '🚀 إرسال طلب دعم جديد')
async def new_request(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>🌍 الخطوة 1:</b> اختر الدولة المستهدفة:", reply_markup=country_menu)

# --- استقبال رمز الدولة ---
@dp.callback_query(F.data.startswith('set_code_'))
async def process_country(callback: CallbackQuery, state: FSMContext):
    code = callback.data.replace('set_code_', '')
    if code == 'manual':
        await state.set_state(FormSteps.get_manual_code)
        await callback.message.edit_text("📝 أرسل رمز الدولة فقط (مثال: +967):")
    else:
        await state.update_data(country_code=code)
        await state.set_state(FormSteps.get_phone)
        await callback.message.edit_text(f"✅ تم اختيار الرمز ({code})\n\n<b>الآن أرسل رقم الهاتف المحلي فقط (بدون رمز الدولة):</b>")
    await callback.answer()

@dp.callback_query(F.data == 'cancel_task')
async def cancel_inline(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ تم إلغاء العملية بنجاح.")
    await callback.answer()

# --- استقبال البيانات النصية ---
@dp.message(FormSteps.get_manual_code)
async def process_manual_code(message: Message, state: FSMContext):
    code = message.text.strip()
    code = code if code.startswith('+') else f"+{code}"
    await state.update_data(country_code=code)
    await state.set_state(FormSteps.get_phone)
    await message.answer(f"✅ تم استلام الرمز ({code})\n\n<b>الآن أرسل رقم الهاتف المحلي فقط:</b>")

@dp.message(FormSteps.get_phone)
async def process_phone(message: Message, state: FSMContext):
    local_phone = message.text.strip().replace('+', '')
    await state.update_data(local_phone=local_phone)
    await state.set_state(FormSteps.get_email)
    await message.answer("<b>📧 الخطوة 2:</b> أرسل البريد الإلكتروني:")

@dp.message(FormSteps.get_email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return await message.answer("⚠️ إيميل غير صحيح، حاول مجدداً:")
    await state.update_data(email=email)
    await state.set_state(FormSteps.get_message)
    await message.answer("<b>📝 الخطوة 3:</b> أرسل نص الرسالة لواتساب:")

@dp.message(FormSteps.get_message)
async def process_message(message: Message, state: FSMContext):
    data = await state.get_data()
    custom_msg = message.text.strip()
    await state.update_data(custom_message=custom_msg)
    
    summary = (
        f"<b>👑 مراجعة الطلب النهائي (VIP - Python)</b>\n\n"
        f"🌍 <b>رمز الدولة:</b> <code>{data.get('country_code')}</code>\n"
        f"📱 <b>الرقم المحلي:</b> <code>{data.get('local_phone')}</code>\n"
        f"📧 <b>الإيميل:</b> <code>{data.get('email')}</code>\n\n"
        f"<b>هل تريد التنفيذ الآن؟</b>"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🚀 نعم، أرسل الآن', callback_data='start_task')],
        [InlineKeyboardButton(text='❌ إلغاء', callback_data='cancel_task')]
    ])
    await message.answer(summary, reply_markup=markup)
    await state.set_state(FormSteps.confirm)

# --- بدء عملية المحرك ---
@dp.callback_query(F.data == 'start_task')
async def start_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        return await callback.answer("⚠️ الجلسة منتهية، ابدأ من جديد.", show_alert=True)
    
    await callback.message.edit_text("🔄 <b>جاري تشغيل محرك بايثون وإرسال الطلب... الرجاء الانتظار قليلاً⏳</b>")
    
    # تشغيل المتصفح في الخلفية حتى لا يتوقف البوت
    asyncio.create_task(run_playwright_task(data, callback.message))
    await state.clear()
    await callback.answer()

# --- محرك Playwright المتطور ---
async def run_playwright_task(data, message_obj):
    country_code = data['country_code']
    local_phone = data['local_phone']
    email = data['email']
    custom_msg = data['custom_message']
    full_phone = f"{country_code}{local_phone}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        
        # إجبار المتصفح على استخدام اللغة الإنجليزية وضبط حجم نافذة مناسب للقطات الشاشة
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={'width': 1280, 'height': 900}
        )
        page = await context.new_page()
        await stealth_async(page) # تفعيل التخفي

        # تم إزالة stylesheet من هنا لكي لا يتشوه التصميم وتختفي العناصر وتسبب Timeout
        async def intercept(route):
            if route.request.resource_type in ["image", "font", "media"]:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", intercept)

        try:
            # إضافة ?lang=en في الرابط لإجبار واتساب على فتح الصفحة بالإنجليزية
            await page.goto('https://www.whatsapp.com/contact/noclient/?lang=en', wait_until='networkidle', timeout=60000)
            
            # انتظار ظهور الحقل
            await page.wait_for_selector('input[name="phone_number"]', timeout=30000)

            # تغيير رمز الدولة برمجياً
            js_code = f"""
            (cCode) => {{
                const cleanCode = cCode.replace('+', '');
                const selects = Array.from(document.querySelectorAll('select'));
                const countrySelect = selects.find(s => s.name.includes('country') || s.className.includes('country'));
                if (countrySelect) {{
                    for (let option of countrySelect.options) {{
                        if (option.value.includes(cleanCode) || option.text.includes(cCode)) {{
                            countrySelect.value = option.value;
                            countrySelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            break;
                        }}
                    }}
                }}
            }}
            """
            await page.evaluate(js_code, country_code)
            await asyncio.sleep(1)

            # إدخال البيانات
            await page.fill('input[name="phone_number"]', "")
            await page.type('input[name="phone_number"]', local_phone, delay=random.randint(40, 90))
            
            await page.type('input[name="email"]', email, delay=random.randint(40, 90))
            if await page.locator('input[name="email_confirm"]').count() > 0:
                await page.type('input[name="email_confirm"]', email, delay=random.randint(40, 90))

            await page.evaluate('() => { const r = document.querySelector(\'input[type="radio"][value="android"]\') || document.querySelector(\'input[type="radio"]\'); if(r) r.click(); }')
            
            await page.type('#message, textarea[name="message"]', custom_msg, delay=random.randint(20, 50))
            
            # الإرسال (البحث عن الزر بناءً على الكلمات الإنجليزية لضمان الدقة)
            submit_button = page.locator('button[type="submit"], button:has-text("Next Step")').first
            await submit_button.click()
            await asyncio.sleep(4)
            
            # التأكد من عدم وجود خطوة تأكيد ثانية (Send Question)
            final_send_button = page.locator('button:has-text("Send Question")').first
            if await final_send_button.count() > 0 and await final_send_button.is_visible():
                await final_send_button.click()
                await asyncio.sleep(4)

            # التقاط شاشة كاملة للنجاح
            success_screenshot = f"success_{random.randint(1000,9999)}.png"
            await page.screenshot(path=success_screenshot, full_page=True)
            photo = FSInputFile(success_screenshot)
            await message_obj.answer_photo(photo, caption=f"✅ <b>تم الإرسال بنجاح سيدي!</b>\n\n📱 الرقم المستهدف: <code>{full_phone}</code>")
            os.remove(success_screenshot)

        except Exception as e:
            print(f"Error: {e}")
            screenshot_path = f"error_{random.randint(1000,9999)}.png"
            try:
                # التقاط شاشة كاملة عند الفشل (full_page=True)
                await page.screenshot(path=screenshot_path, full_page=True)
                photo = FSInputFile(screenshot_path)
                await message_obj.answer_photo(photo, caption=f"❌ فشل الإرسال.\nالخطأ التقني: <code>{str(e)[:150]}</code>")
                os.remove(screenshot_path)
            except Exception as pic_error:
                await message_obj.answer(f"❌ فشل الإرسال ولم أتمكن من التقاط صورة.\nالخطأ: {str(e)[:100]}")
        finally:
            await browser.close()

# --- خادم الويب الخاص بـ Render ---
async def web_handler(request):
    return web.Response(text="🟢 الخادم يعمل والبوت متصل!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌐 خادم الويب يعمل على المنفذ {PORT}")

# --- نقطة البداية ---
async def main():
    await start_web_server()
    print("🤖 جاري تشغيل بوت التليجرام...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
