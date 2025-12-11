import os
import json
import logging
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Union 

# --- Import Library (Eksplisit untuk menghindari NameError) ---
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, CallbackContext, ConversationHandler, CallbackQueryHandler
)
# Pastikan library Firebase terinstal
try:
    import firebase_admin 
    from firebase_admin import credentials, firestore 
    FIREBASE_INSTALLED = True
except ImportError:
    print("❌ ERROR: Library Firebase tidak ditemukan.")
    FIREBASE_INSTALLED = False

# ==========================================
# 1. SETUP & INISIALISASI
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FIREBASE_JSON = os.environ.get("FIREBASE_ADMIN_CREDENTIALS")

# Konfigurasi Database
DB_ISOLATION_MODE = True  
db = None 

# State Conversation
(GET_PHOTO, ASK_ADD_PHOTO, GET_NAME, GET_DOB, GET_HEIGHT, GET_GENDER, GET_BIO, GET_LOCATION) = range(8)

# ==========================================
# 2. FUNGSI DATABASE UTILITY & KONEKSI
# ==========================================

def initialize_firebase_db():
    """Mencoba menginisialisasi Firebase Firestore saat runtime."""
    global db, DB_ISOLATION_MODE

    if not FIREBASE_INSTALLED:
        logger.error("Database tidak dapat diinisialisasi: Firebase tidak terinstal.")
        DB_ISOLATION_MODE = True
        return False
    
    if db is not None and not DB_ISOLATION_MODE:
        return True

    # Coba inisialisasi total
    try:
        if FIREBASE_JSON:
            creds_dict = json.loads(FIREBASE_JSON)
            cred = credentials.Certificate(creds_dict)
            
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            
            db = firestore.client()
            DB_ISOLATION_MODE = False
            logger.info("✅ Koneksi Firebase Firestore Berhasil! Isolasi: False")
            return True
    except Exception as e:
        logger.error(f"❌ Gagal menginisialisasi Firebase saat runtime: {e}")
        DB_ISOLATION_MODE = True 
        return False

def get_user_profile(user_id: int):
    """Mengambil profil dari Firestore."""
    if db is None or DB_ISOLATION_MODE:
        initialize_firebase_db() 
        if db is None or DB_ISOLATION_MODE: return None 

    try:
        doc = db.collection("profiles").document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Gagal mengambil profil dari DB (Fatal Error): {e}")
        return None 

def update_user_profile(user_id: int, data: dict):
    """Menyimpan atau memperbarui profil di Firestore."""
    if db is None or DB_ISOLATION_MODE:
        initialize_firebase_db()
        if db is None or DB_ISOLATION_MODE: return False

    try:
        db.collection("profiles").document(str(user_id)).set(data, merge=True)
        return True
    except Exception as e:
        logger.error(f"Gagal menyimpan profil ke DB (Fatal Error): {e}")
        return False

# ==========================================
# 3. UI & HOME MENU
# ==========================================

async def handle_home_callbacks(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "go_home":
        return await show_home(update, context)
    else:
        await query.edit_message_text(
            text=f"Anda menekan menu **{data.title()}**.\n"
                 "Tekan HOME untuk kembali.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 HOME", callback_data="go_home")]])
        )


async def show_home(update: Update, context: CallbackContext):
    effective_message = update.effective_message if update.effective_message else update.callback_query.message
    user_id = update.effective_user.id
    p = get_user_profile(user_id) 

    if not p or not p.get("profile_complete"):
        await effective_message.reply_text("Profil tidak ditemukan atau gagal dimuat.")
        return await start_command(update, context) 

    keyboard = [
        [InlineKeyboardButton("▶️ SWIPE", callback_data="swipe"), InlineKeyboardButton("💌 MATCH", callback_data="match")],
        [InlineKeyboardButton("💎 STORE", callback_data="store"), InlineKeyboardButton("✨ PREMIUM", callback_data="premium")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await effective_message.reply_text(
        f"Selamat datang, **{p.get('nama', 'Pengguna')}**!\n"
        "Anda sudah masuk. Pilih menu di bawah ini:",
        reply_markup=reply_markup
    )
    return 

# ==========================================
# 4. FLOW PENDAFTARAN (CONVERSATION)
# ==========================================

async def start_command(update: Update, context: CallbackContext) -> None:
    if db is None:
        initialize_firebase_db()

    user_id = update.effective_user.id
    profile = get_user_profile(user_id) 
    
    try:
        if update.message:
            await update.message.reply_text("Memuat...", reply_markup=ReplyKeyboardRemove())
        else:
            await update.callback_query.message.reply_text("Memuat...", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.warning(f"Gagal mengirim ReplyKeyboardRemove: {e}")

    if profile and profile.get("profile_complete"):
        await show_home(update, context)
        return 
    else:
        keyboard = [[InlineKeyboardButton("Buat Profil", callback_data="start_reg")]] 
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.effective_message.reply_text(
            "Selamat datang di **Cari Teman Sekitar**!\n"
            "Silakan lengkapi profil terlebih dahulu.",
            reply_markup=reply_markup,
        )
        return

async def start_registration_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data["temp"] = {"photos": []} 
    
    await query.edit_message_text("(A) Foto Profil\nSilakan kirim foto pertama kamu.")
    
    return GET_PHOTO 


async def end_conversation(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Pembuatan profil dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def handle_photo(update: Update, context: CallbackContext):
    if not update.message.photo:
        if update.message and update.message.text:
            if update.message.text == "/cancel":
                return await end_conversation(update, context)
            await update.message.reply_text("Saat ini saya menunggu FOTO. Kirimkan file foto.")
        else:
            await update.message.reply_text("Silakan kirimkan file foto.")
        return GET_PHOTO 

    try:
        photo_info = update.message.photo[-1]
        
        logger.info(f"File ID berhasil diambil: {photo_info.file_id[:10]}... ")
        
        context.user_data["temp"]["photos"].append(photo_info.file_id)
        
        if len(context.user_data["temp"]["photos"]) >= 3:
            await update.message.reply_text("Foto lengkap (3 foto). Lanjut ke langkah berikutnya.")
            return await next_step_name(update, context)
        
        kbd = [[InlineKeyboardButton("Tambah Lagi", callback_data="add_pic"), InlineKeyboardButton("Lanjut", callback_data="skip_pic")]]
        await update.message.reply_text("Foto diterima. Mau tambah lagi?", reply_markup=InlineKeyboardMarkup(kbd))
        return ASK_ADD_PHOTO
        
    except Exception as e:
        logger.error(f"FATAL ERROR di handle_photo: {e}")
        await update.message.reply_text("Terjadi kesalahan kritis saat memproses foto. Coba kirim ulang.")
        return GET_PHOTO 


async def handle_ask_photo(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_pic":
        await query.edit_message_text("Silakan kirim foto berikutnya.")
        return GET_PHOTO
    else: 
        return await next_step_name(query, context)


async def next_step_name(update: Union[Update, CallbackContext], context: CallbackContext):
    if isinstance(update, Update):
        target = update.message
        await target.reply_text("(B) Nama\nMasukkan nama kamu.")
    else:
        target = update.callback_query.message
        await target.edit_text("(B) Nama\nMasukkan nama kamu.")
    return GET_NAME

async def handle_name(update: Update, context: CallbackContext):
    context.user_data["temp"]["nama"] = update.message.text
    await update.message.reply_text("(C) Tanggal Lahir\nMasukkan format DD-MM-YYYY (Cth: 31-12-1995).")
    return GET_DOB

async def handle_dob(update: Update, context: CallbackContext):
    try:
        dob = datetime.strptime(update.message.text, "%d-%m-%Y")
        age = relativedelta(datetime.now(), dob).years
        
        if age < 18 or age > 99:
            await update.message.reply_text("Usia harus 18-99 tahun. Format DD-MM-YYYY.")
            return GET_DOB
            
        context.user_data["temp"]["usia"] = age
        await update.message.reply_text(f"Usia kamu {age} tahun.\n\n(D) Tinggi Badan\nMasukkan tinggi badan (cm, cth: 175).")
        return GET_HEIGHT
    except:
        await update.message.reply_text("Format salah! Gunakan DD-MM-YYYY.")
        return GET_DOB

async def handle_height(update: Update, context: CallbackContext):
    try:
        height = int(update.message.text)
        if height < 100 or height > 250:
            await update.message.reply_text("Tinggi badan harus dalam cm (100-250).")
            return GET_HEIGHT
            
        context.user_data["temp"]["tinggi"] = height
        await update.message.reply_text("(E) Bio\nMasukkan deskripsi singkat tentang diri kamu.")
        return GET_BIO
    except ValueError:
        await update.message.reply_text("Tinggi badan harus angka saja.")
        return GET_HEIGHT

async def handle_bio(update: Update, context: CallbackContext):
    bio = update.message.text
    if len(bio) > 500:
        await update.message.reply_text("Bio terlalu panjang. Maksimal 500 karakter.")
        return GET_BIO
        
    context.user_data["temp"]["bio"] = bio
    kbd = [[KeyboardButton("Kirim Lokasi", request_location=True)]]
    await update.message.reply_text("(F) Lokasi\nLangkah terakhir: Kirim lokasi kamu.", reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True, one_time_keyboard=True))
    return GET_LOCATION

async def handle_loc(update: Update, context: CallbackContext):
    loc = update.message.location
    if not loc:
        await update.message.reply_text("Harap gunakan tombol 'Kirim Lokasi'.")
        return GET_LOCATION
        
    user_id = update.effective_user.id
    p_data = context.user_data["temp"]
    
    p_data.update({
        "latitude": loc.latitude, "longitude": loc.longitude,
        "diamond_count": 1, "profile_complete": True,
        "is_premium": False, "is_ghost_mode_on": False,
        "match_count": 0, 
        "telegram_username": update.effective_user.username if update.effective_user.username else None
    })
    
    if not update_user_profile(user_id, p_data):
         await update.message.reply_text("⚠ Gagal menyimpan profil (Database Mati/Gagal Koneksi). Anda tetap bisa melanjutkan namun data tidak tersimpan.")
         
    await update.message.reply_text("✅ Profil Disimpan!", reply_markup=ReplyKeyboardRemove())
    return await show_home(update, context)

async def handle_text(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
        
    if context.user_data.get('temp') is None:
        await update.message.reply_text(
            "Saya tidak mengenali perintah itu. Silakan gunakan /start untuk memulai."
        )


# ==========================================
# 5. MAIN RUNNER
# ==========================================

def main():
    if not TOKEN: 
        logger.error("❌ ERROR: TELEGRAM_BOT_TOKEN TIDAK ADA DI SECRETS. Bot berhenti.")
        return

    # 🚨 PENTING: Panggil inisialisasi di sini untuk memaksa koneksi
    logger.info("Mencoba Inisialisasi Database Sebelum Bot Polling...")
    initialize_firebase_db() 
    
    print("--- [DIAGNOSIS RUNTIME] ---")
    print(f"TELEGRAM_BOT_TOKEN ditemukan: {'✅' if os.environ.get('TELEGRAM_BOT_TOKEN') else '❌'}")
    print(f"FIREBASE_ADMIN_CREDENTIALS ditemukan: {'✅' if os.environ.get('FIREBASE_ADMIN_CREDENTIALS') else '❌'}")
    print(f"DB Isolation Mode (Awal Polling): {DB_ISOLATION_MODE}")
    print("---------------------------")


    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_registration_handler, pattern="^start_reg$")], 
        states={
            GET_PHOTO: [MessageHandler(filters.ALL & ~filters.COMMAND, handle_photo)], 
            ASK_ADD_PHOTO: [CallbackQueryHandler(handle_ask_photo, pattern="^(add_pic|skip_pic)$")], 
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            GET_DOB: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dob)],
            GET_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_height)],
            GET_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bio)],
            GET_LOCATION: [MessageHandler(filters.LOCATION, handle_loc)],
        },
        fallbacks=[CommandHandler("cancel", end_conversation)],
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_home_callbacks, pattern="^(swipe|match|store|premium|go_home)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("🚀 Bot Siap Menerima Koneksi...")
    app.run_polling()

if __name__ == "__main__":
    main()
