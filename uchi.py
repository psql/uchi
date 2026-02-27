#!/usr/bin/env python3
"""うち (Uchi) — natural language smart home bot"""
import logging
import subprocess
import sys
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)

from config import cfg
from llm import interpret
from plugins import registry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(name)-14s  %(levelname)s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('uchi')

# ── Auth guard ─────────────────────────────────────────────────────────────────
def allowed(update: Update) -> bool:
    if not cfg.ALLOWED_USERS:
        return True   # open to anyone if not configured
    user = update.effective_user
    return str(user.id) in cfg.ALLOWED_USERS or user.username in cfg.ALLOWED_USERS

async def _guard(update: Update) -> bool:
    if not allowed(update):
        await update.message.reply_text('ごめんなさい — 立入禁止 🚫')
        return False
    return True

# ── Commands ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return
    name = update.effective_user.first_name or 'friend'
    await update.message.reply_text(
        f"こんにちは、{name}さん！ 👋\n\n"
        f"私は *Uchi* (うち) — your smart home assistant.\n\n"
        f"Just talk to me naturally:\n"
        f"• _\"turn off the lights\"_\n"
        f"• _\"make it cozy for a movie\"_\n"
        f"• _\"purple party mode\"_\n"
        f"• _\"good morning\"_ → sunrise wake-up\n\n"
        f"よろしくお願いします！ 🏠✨",
        parse_mode='Markdown',
    )

async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return
    await update.message.reply_text(
        "🏠 *Uchi — 使い方 (How to use)*\n\n"
        "*照明 Lights*\n"
        "  Colors: _red, blue, purple, warm, cool…_\n"
        "  Effects: _party, rainbow, breathe, candle, strobe, alert_\n"
        "  Presets: _relax, romance, chill, sunset, rave…_\n"
        "  Modes: _movie, night, reading, zen, focus_\n"
        "  Timed: _wake up (sunrise), good night (sleep)_\n"
        "  _fade in / fade out / blackout_\n\n"
        "*Commands*\n"
        "  /status — ステータス system status\n"
        "  /panel  — web panel URL\n"
        "  /lights — list lights\n\n"
        "_Powered by Llama + Philips Hue 🤖💡_",
        parse_mode='Markdown',
    )

async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            d = (await c.get(f'http://localhost:{cfg.VIBEDJ_PORT}/api/status')).json()
        fx       = d.get('activeEffect') or 'なし (none)'
        reachable = len(d.get('reachable', []))
        await update.message.reply_text(
            f"📊 *ステータス*\n\n"
            f"💡 Reachable lights: `{reachable}`\n"
            f"✨ Effect: `{fx}`\n"
            f"🥁 BPM: `{d.get('bpm', 120)}`\n"
            f"🤖 LLM: `{cfg.OLLAMA_MODEL} @ {cfg.OLLAMA_URL}`",
            parse_mode='Markdown',
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ VibeDJ offline:\n`{e}`", parse_mode='Markdown')

async def cmd_panel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return
    try:
        ip = subprocess.check_output(['ipconfig', 'getifaddr', 'en12'], text=True).strip()
    except Exception:
        ip = 'your-mac-ip'
    await update.message.reply_text(
        f"🖥️ *VibeDJ Panel*\n\n"
        f"Local: `http://localhost:{cfg.VIBEDJ_PORT}`\n"
        f"Network: `http://{ip}:{cfg.VIBEDJ_PORT}`",
        parse_mode='Markdown',
    )

async def cmd_lights(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            lights = (await c.get(f'http://localhost:{cfg.VIBEDJ_PORT}/api/lights')).json()
        reachable = {i: l for i, l in lights.items() if l['state'].get('reachable')}
        lines = [f"💡 *照明リスト* ({len(lights)} lights, {len(reachable)} reachable)\n"]
        for i, l in sorted(lights.items(), key=lambda x: int(x[0])):
            r = l['state'].get('reachable')
            on = l['state'].get('on')
            dot = '🟢' if (r and on) else ('🔴' if r else '⚫')
            lines.append(f"{dot} `{i:>2}` {l['name']}")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"⚠️ `{e}`", parse_mode='Markdown')

# ── Main message handler ──────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update): return

    text = update.message.text
    await ctx.bot.send_chat_action(update.effective_chat.id, 'typing')

    try:
        intent      = await interpret(text)
        plugin_name = intent.get('plugin')
        action      = intent.get('action', 'chat')
        params      = intent.get('params', {})
        response    = intent.get('response', 'わかった...')

        if plugin_name:
            plugin = registry.get(plugin_name)
            if plugin:
                await plugin.execute(action, params)

        await update.message.reply_text(response)

    except Exception as e:
        log.error(f'handle_message error: {e}', exc_info=True)
        await update.message.reply_text(
            f"ごめんなさい 🙏 Something broke:\n`{e}`", parse_mode='Markdown'
        )

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    if not cfg.TELEGRAM_TOKEN:
        print('❌  Set TELEGRAM_TOKEN in ~/uchi/.env and restart.')
        sys.exit(1)

    log.info('🏠  Uchi starting…')

    app = Application.builder().token(cfg.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start',  cmd_start))
    app.add_handler(CommandHandler('help',   cmd_help))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('panel',  cmd_panel))
    app.add_handler(CommandHandler('lights', cmd_lights))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info('Bot polling… よろしく！')
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
