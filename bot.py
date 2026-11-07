import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
APP_URL = "https://xrt-vault.onrender.com"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton(
            "🚀 Open XRT Vault",
            web_app=WebAppInfo(url=APP_URL)
        )
    ]]

    await update.message.reply_text(
        "💙 Welcome to XRT Vault!\n\n"
        "Something Big Is Coming.\n"
        "Explore the Unknown. Unlock the Future.\n\n"
        "⚡ Be Early. Stay Ahead.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💎 XRT VAULT\n\n"
        "Use /start to open XRT Vault.\n"
        "Stay curious. Stay ahead!"
    )

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing!")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    print("XRT Vault Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
