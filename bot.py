import asyncio
import os
import random
import re
import logging
from functools import lru_cache
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async
import google.generativeai as genai

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_activity.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- الإعدادات الأساسية ---
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
MY_TELEGRAM_ID = int(os.environ.get('MY_TELEGRAM_ID', 8435344041))
PORT = int(os.environ.get('PORT', 3000))
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# إعداد الذكاء الاصطناعي
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-pro')
else:
    logger.warning("لم يتم العثور على مفتاح GEMINI_API_KEY. سيعمل البوت بدون تحسين النصوص.")

# --- التخزين المؤقت (Caching) لتحسين الأداء ---
# استخدام ذاكرة التخزين المؤقت لتقليل استهلاك API وتسريع الاستجابة للرسائل المتكررة
@lru_cache(maxsize=100)
def get_cached_ai_translation(raw_msg: str) -> str:
    if not GEMINI_API_KEY:
        return raw_msg
    try:
        prompt = f"ترجم هذه المشكلة إلى الإنجليزية الرسمية واجعلها تبدو كرسالة احترافية لدعم فني واتساب لفك حظر الرقم أو حل المشكلة، بدون أي إضافات أو مقدمات منك، فقط نص الرسالة الجاهز للإرسال: '{raw_msg}'"
        response = ai_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"خطأ في الاتصال بـ Gemini API: {e}")
        return raw_msg

# دالة مساعدة لتشغيل Caching المتزامن في بيئة غير متزامنة
async def process_text_with_ai(raw_msg: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_cached_ai_translation, raw_msg)

# --- إدارة حالات المحادثة ---
class FormSteps(StatesGroup):
    get_manual_code = State()
    get_phone = State()
    get_email = State()
    get_message = State()
    confirm = State()

# --- الواجهات ---
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text='🚀 إرسال طلب دعم جديد'), KeyboardButton(text='📊 حالة السيرفر')],
        [KeyboardButton(text='❌ إلغاء العملية')]
    ],
    resize_keyboard=True
)

country_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='🇾🇪 اليمن (+967)', callback_data='set_code_+967'), InlineKeyboardButton(text='🇸🇦 السعودية (+966)', callback_data='set_code_+966')],
    [InlineKeyboardButton(text='🇪🇬 مصر (+20)', callback_data='set_code_+20'), InlineKeyboardButton(text='🌐 رمز آخر (يدوي)', callback_data='set_code_manual')],
    [InlineKeyboardButton(text='🚫 إلغاء', callback_data='cancel_task')]
])

# --- فلتر حماية ---
@dp.message.outer_middleware()
async def auth_middleware(handler, event, data):
    if event.from_user.id != MY_TELEGRAM_ID:
        logger.warning(f"محاولة وصول غير مصرح بها من المستخدم: {event.from_user.id}")
        return
    return await handler(event, data)

@dp.callback_query.outer_middleware()
async def auth_callback_middleware(handler, event, data):
    if event.from_user.id != MY_TELEGRAM_ID:
        return
    return await handler(event, data)

# --- الأوامر ---
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>مرحباً بك سيدي في لوحة التحكم VIP 👑</b>\n<i>النظام مدعوم بالذكاء الاصطناعي وجاهز للعمل.</i>", reply_markup=main_menu)

@dp.message(F.text == '📊 حالة السيرفر')
async def server_status(message: Message):
    ai_status = "متصل 🟢" if GEMINI_API_KEY else "غير مفعل 🔴"
    await message.answer(f"<b>📊 حالة النظام:</b>\nالمتصفح: مستعد للعمل 🟢\nالذكاء الاصطناعي: {ai_status}\nالخادم: متصل 🟢")

@dp.message(F.text == '❌ إلغاء العملية')
async def cancel_process(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ تم الإلغاء.", reply_markup=main_menu)

@dp.message(F.text == '🚀 إرسال طلب دعم جديد')
async def new_request(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>🌍 الخطوة 1:</b> اختر الدولة المستهدفة:", reply_markup=country_menu)

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
    await callback.message.edit_text("❌ تم الإلغاء.")
    await callback.answer()

@dp.message(FormSteps.get_manual_code)
async def process_manual_code(message: Message, state: FSMContext):
    # التحقق من صحة رمز الدولة
    code_match = re.match(r"^\+?\d{1,4}$", message.text.strip())
    if not code_match:
        return await message.answer("⚠️ رمز غير صحيح، يرجى إرسال أرقام فقط مع أو بدون (+):")
    
    code = f"+{message.text.strip().replace('+', '')}"
    await state.update_data(country_code=code)
    await state.set_state(FormSteps.get_phone)
    await message.answer(f"✅ تم استلام الرمز ({code})\n\n<b>أرسل رقم الهاتف المحلي فقط:</b>")

@dp.message(FormSteps.get_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace('+', '')
    if not phone.isdigit():
         return await message.answer("⚠️ يجب أن يحتوي رقم الهاتف على أرقام فقط. حاول مجدداً:")
         
    await state.update_data(local_phone=phone)
    await state.set_state(FormSteps.get_email)
    await message.answer("<b>📧 الخطوة 2:</b> أرسل البريد الإلكتروني:")

@dp.message(FormSteps.get_email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip()
    if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
        return await message.answer("⚠️ إيميل غير صحيح، تأكد من الصيغة وحاول مجدداً:")
        
    await state.update_data(email=email)
    await state.set_state(FormSteps.get_message)
    await message.answer("<b>📝 الخطوة 3:</b> اشرح المشكلة باختصار (وسيقوم الذكاء الاصطناعي بصياغتها):")

@dp.message(FormSteps.get_message)
async def process_message(message: Message, state: FSMContext):
    raw_msg = message.text.strip()
    processing_msg = await message.answer("⏳ جاري صياغة الرسالة باستخدام الذكاء الاصطناعي...")
    
    final_msg = await process_text_with_ai(raw_msg)
    
    await processing_msg.delete()
    await state.update_data(custom_message=final_msg)
    data = await state.get_data()
    
    summary = (
        f"<b>👑 مراجعة الطلب (الذكاء الاصطناعي 🧠)</b>\n\n"
        f"📱 <b>الرقم:</b> <code>{data.get('country_code')}{data.get('local_phone')}</code>\n"
        f"📧 <b>الإيميل:</b> <code>{data.get('email')}</code>\n\n"
        f"📄 <b>الرسالة النهائية:</b>\n<i>{final_msg}</i>\n\n"
        f"<b>هل تريد التنفيذ؟</b>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🚀 نعم، أرسل الآن', callback_data='start_task')],
        [InlineKeyboardButton(text='❌ إلغاء', callback_data='cancel_task')]
    ])
    await message.answer(summary, reply_markup=markup)
    await state.set_state(FormSteps.confirm)

@dp.callback_query(F.data == 'start_task')
async def start_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.message.edit_text("🔄 <b>جاري تشغيل محرك بايثون لتخطي الحماية وإرسال الطلب... ⏳</b>")
    # التشغيل غير المتزامن كـ Task منفصل لعدم إيقاف البوت
    asyncio.create_task(run_playwright_task(data, callback.message))
    await state.clear()
    await callback.answer()

# --- محرك Playwright المعزز ---
async def run_playwright_task(data, message_obj):
    country_code = data['country_code']
    local_phone = data['local_phone']
    email = data['email']
    custom_msg = data['custom_message']

    logger.info(f"بدء مهمة Playwright للرقم: {country_code}{local_phone}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled', '--disable-infobars',
                '--window-size=1280,900'
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={'width': 1280, 'height': 900},
            java_script_enabled=True
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            # 1. تجميع ملفات تعريف الارتباط
            await page.goto('https://www.whatsapp.com/?lang=en', wait_until='networkidle', timeout=40000)
            await asyncio.sleep(random.uniform(2.0, 4.5))
            
            # 2. الانتقال لصفحة الدعم الفني
            await page.goto('https://www.whatsapp.com/contact/noclient/?lang=en', wait_until='domcontentloaded', timeout=40000)
            await asyncio.sleep(3)

            # 3. التحقق الذكي من حقول الإدخال
            try:
                phone_input = page.locator('input[name="phone_number"], input[type="tel"]').first
                await phone_input.wait_for(state='visible', timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("لم يتم العثور على حقل الهاتف، محاولة التحديث الذكي...")
                await page.reload(wait_until='domcontentloaded')
                await asyncio.sleep(4)
                await phone_input.wait_for(state='visible', timeout=15000)

            # تعديل رمز الدولة برمجياً لتجنب مشاكل القوائم المنسدلة المعقدة
            js_code = f"""
            (cCode) => {{
                const cleanCode = cCode.replace('+', '');
                const selects = Array.from(document.querySelectorAll('select'));
                const countrySelect = selects.find(s => s.name.includes('country') || s.className.includes('country'));
                if (countrySelect) {{
                    for (let option of countrySelect.options) {{
                        if (option.value.includes(cleanCode) || option.text.includes(cCode)) {{
                            countrySelect.value = option.value;
                            countrySelect.dispatchEvent(new Event('change', {{ bubbles: true }})); break;
                        }}
                    }}
                }}
            }}
            """
            await page.evaluate(js_code, country_code)
            await asyncio.sleep(1)

            # محاكاة الكتابة البشرية (Human Typing Simulation)
            await phone_input.fill("")
            await phone_input.type(local_phone, delay=random.randint(40, 120))
            
            email_input = page.locator('input[name="email"], input[type="email"]').first
            await email_input.type(email, delay=random.randint(30, 90))
            
            email_confirm = page.locator('input[name="email_confirm"]')
            if await email_confirm.count() > 0:
                await email_confirm.type(email, delay=random.randint(30, 90))

            # اختيار نظام التشغيل
            await page.evaluate('() => { const r = document.querySelector(\'input[type="radio"][value="android"]\') || document.querySelector(\'input[type="radio"]\'); if(r) r.click(); }')
            
            msg_box = page.locator('#message, textarea[name="message"]').first
            await msg_box.type(custom_msg, delay=random.randint(5, 25))
            
            # الضغط على زر الخطوة التالية
            submit_button = page.locator('button[type="submit"], button:has-text("Next Step")').first
            await submit_button.scroll_into_view_if_needed()
            await submit_button.click()
            await asyncio.sleep(random.uniform(2.5, 4.0))
            
            # إرسال الطلب النهائي
            final_send_button = page.locator('button:has-text("Send Question")').first
            if await final_send_button.count() > 0 and await final_send_button.is_visible():
                await final_send_button.click()
                await asyncio.sleep(4)

            # التحقق من النجاح والتقاط صورة
            success_screenshot = f"success_{random.randint(1000,9999)}.png"
            await page.screenshot(path=success_screenshot, full_page=True)
            await message_obj.answer_photo(FSInputFile(success_screenshot), caption=f"✅ <b>تم الإرسال بنجاح!</b>\n📱 الرقم: <code>{country_code}{local_phone}</code>")
            os.remove(success_screenshot)
            logger.info(f"تم إرسال الطلب بنجاح للرقم: {country_code}{local_phone}")

        except Exception as e:
            logger.error(f"فشل في إرسال الطلب عبر Playwright: {e}")
            screenshot_path = f"error_{random.randint(1000,9999)}.png"
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                await message_obj.answer_photo(FSInputFile(screenshot_path), caption=f"❌ فشل الإرسال (حماية النظام).\nتم تسجيل الخطأ في اللوج الخاص بالخادم.")
                os.remove(screenshot_path)
            except:
                await message_obj.answer(f"❌ فشل الإرسال وتعذر التقاط صورة للخطأ.")
        finally:
            await browser.close()

# --- خادم الويب الخاص بـ Render ---
async def web_handler(request): return web.Response(text="🟢 Enterprise Bot is running!")
async def start_web_server():
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    logger.info("جاري تشغيل البوت...")
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
