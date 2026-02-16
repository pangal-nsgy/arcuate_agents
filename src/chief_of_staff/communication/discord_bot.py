"""Discord bot interface — routes messages to the right agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import anthropic
import discord

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)

# Fallback triage prompt — used only if agent config has no triage_prompt set
_DEFAULT_TRIAGE_PROMPT = """Message in #{channel} from {author}: "{message}"

Context: {context}

You are Angie, the AI chief of staff. Should you respond? YES or NO only.

YES if the message contains: angie, agent, agent1, chief of staff, cos, bot — OR asks a question — OR discusses business topics where you could add useful context.
NO only for pure casual chat, single-word reactions, or messages clearly not needing any response."""

_DEFAULT_TRIGGER_WORDS = {"angie", "agent1", "agent 1", "chief of staff", "cos,", "hey bot", "hey agent"}
_PROGRESS_MIN_SEND_INTERVAL_SECONDS = 8.0
_PROGRESS_HEARTBEAT_SECONDS = 25.0


class ChiefOfStaffBot(discord.Client):
    """Discord bot that routes messages to the appropriate agent."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        super().__init__(intents=intents)
        self._agents: dict[str, Any] = {}  # agent_name -> Agent instance (cache)
        self._triage_client = None

    def _get_agent(self, name: str = "chief_of_staff"):
        """Get a cached agent by name. Falls back to COS if not found."""
        if name not in self._agents:
            from chief_of_staff.agent.core import get_agent, get_agent_by_name
            if name == "chief_of_staff":
                self._agents[name] = get_agent()
            else:
                agent = get_agent_by_name(name)
                if agent is None:
                    logger.warning(f"Agent '{name}' not found, falling back to chief_of_staff")
                    return self._get_agent("chief_of_staff")
                self._agents[name] = agent
        return self._agents[name]

    def _get_triage_client(self):
        if self._triage_client is None:
            self._triage_client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=30.0,
            )
        return self._triage_client

    async def on_ready(self):
        logger.info(f"Discord bot connected as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} server(s)")
        for guild in self.guilds:
            channels = [c.name for c in guild.text_channels]
            logger.info(f"  Server: {guild.name} — channels: {channels}")

    def _get_triage_config(self) -> tuple[set[str], str]:
        """Load merged trigger words from all agents, and triage prompt from COS."""
        from chief_of_staff.agent.router import get_all_trigger_words
        from chief_of_staff.agent.registry import get_registry

        # Merged trigger words from ALL agents
        trigger_words = get_all_trigger_words()
        if not trigger_words:
            trigger_words = _DEFAULT_TRIGGER_WORDS

        # Triage prompt from COS config
        registry = get_registry()
        config = registry.get("chief_of_staff")
        if config and config.triage_prompt:
            triage_prompt = config.triage_prompt
        else:
            triage_prompt = _DEFAULT_TRIAGE_PROMPT

        return trigger_words, triage_prompt

    async def _should_respond(self, message: discord.Message, context: str) -> bool:
        """Decide if the bot should respond. Fast keyword check first, then LLM triage."""
        trigger_words, triage_prompt = self._get_triage_config()
        msg_lower = message.content.lower()

        # Fast path: keyword match — always respond
        for trigger in trigger_words:
            if trigger in msg_lower:
                logger.info(f"Keyword trigger '{trigger}' in #{getattr(message.channel, 'name', 'DM')} from {message.author}")
                return True

        # Also trigger on "agent" as a standalone word (not "agents" or "reagent")
        import re
        if re.search(r'\bagent\b', msg_lower):
            logger.info(f"Keyword trigger 'agent' in #{getattr(message.channel, 'name', 'DM')} from {message.author}")
            return True

        # LLM triage for everything else
        try:
            client = self._get_triage_client()
            prompt = triage_prompt.format(
                channel=getattr(message.channel, "name", "DM"),
                author=message.author.display_name,
                message=message.content[:500],
                context=context[:1000],
            )
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = response.content[0].text.strip().upper()
            logger.info(f"Triage for #{getattr(message.channel, 'name', 'DM')} from {message.author}: {answer}")
            return answer.startswith("YES")
        except Exception as e:
            logger.error(f"Triage call failed: {e}")
            return False

    async def on_message(self, message: discord.Message):
        # Don't respond to ourselves
        if message.author == self.user:
            return

        # Don't respond to other bots
        if message.author.bot:
            return

        content = message.content
        if not content:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user in message.mentions
        channel_name = getattr(message.channel, "name", "")

        # Strip the bot mention from the message if present
        if is_mentioned:
            content = content.replace(f"<@{self.user.id}>", "").strip()

        if not content:
            return

        # Always respond to DMs and @mentions
        # For all other channel messages, use triage to decide
        should_respond = is_dm or is_mentioned
        if not should_respond:
            # Build context for triage
            context_lines = []
            async for msg in message.channel.history(limit=5):
                if msg.id != message.id:
                    context_lines.append(f"{msg.author.display_name}: {msg.content[:200]}")
            context = "\n".join(context_lines) if context_lines else "(no recent messages)"
            should_respond = await self._should_respond(message, context)

        if not should_respond:
            return

        # Route to the right agent
        from chief_of_staff.agent.router import resolve_agent
        agent_name = resolve_agent(content, is_dm=is_dm)

        logger.info(f"Discord message from {message.author} in #{channel_name} → {agent_name}: {content[:100]}...")

        # Log incoming message
        from chief_of_staff.agent.activity import log_activity, MESSAGE_RECEIVED, MESSAGE_SENT, ERROR
        log_activity(
            agent_name=agent_name,
            action_type=MESSAGE_RECEIVED,
            action_detail=content[:500],
            channel="discord",
            user_id=f"{message.author.display_name} ({message.author.id})",
            metadata={"channel_name": channel_name, "is_dm": is_dm, "is_mention": is_mentioned},
        )

        progress_queue: asyncio.Queue[str] = asyncio.Queue()
        progress_done = asyncio.Event()
        last_enqueued_msg = ""

        # Queue progress updates; a background worker sends them at safe intervals.
        async def _progress(msg: str) -> None:
            nonlocal last_enqueued_msg
            clean = (msg or "").strip()
            if not clean:
                return
            if clean == last_enqueued_msg:
                return
            last_enqueued_msg = clean
            await progress_queue.put(clean)

        async def _progress_worker() -> None:
            last_sent_at = 0.0
            loop = asyncio.get_running_loop()
            while True:
                if progress_done.is_set() and progress_queue.empty():
                    break
                try:
                    msg = await asyncio.wait_for(progress_queue.get(), timeout=_PROGRESS_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    if progress_done.is_set():
                        break
                    msg = "Still working on this..."

                now = loop.time()
                wait_for = _PROGRESS_MIN_SEND_INTERVAL_SECONDS - (now - last_sent_at)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)

                try:
                    await message.channel.send(msg)
                    last_sent_at = loop.time()
                except Exception as e:
                    logger.warning(f"Failed to send progress update in Discord: {e}")

        # Show typing indicator while processing
        progress_task = asyncio.create_task(_progress_worker())
        async with message.channel.typing():
            try:
                agent = self._get_agent(agent_name)
                # Build conversation history from recent channel messages
                history = await self._build_history(message.channel)

                response = await agent.respond(
                    user_message=content,
                    conversation_history=history,
                    channel="discord",
                    user_id=f"discord:{message.author.id}",
                    progress_callback=_progress,
                )

                # Log outgoing response
                log_activity(
                    agent_name=agent_name,
                    action_type=MESSAGE_SENT,
                    action_detail=response[:500],
                    channel="discord",
                    user_id=f"{message.author.display_name} ({message.author.id})",
                )

                # Discord has a 2000 char limit per message
                if len(response) <= 2000:
                    await message.reply(response)
                else:
                    # Split into chunks at newlines
                    chunks = _split_message(response)
                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await message.reply(chunk)
                        else:
                            await message.channel.send(chunk)

            except Exception as e:
                logger.error(f"Error processing Discord message: {e}", exc_info=True)
                log_activity(
                    agent_name=agent_name,
                    action_type=ERROR,
                    action_detail=f"Discord message processing failed: {e}",
                    channel="discord",
                    user_id=f"discord:{message.author.id}",
                )
                # Report error to #bot-errors channel
                try:
                    from chief_of_staff.communication.error_reporter import report_error
                    await report_error(
                        bot=self,
                        error_msg=str(e),
                        context=f"#{channel_name} from {message.author.display_name}",
                        user_msg=content[:200],
                    )
                except Exception:
                    logger.error("Failed to report error to #bot-errors", exc_info=True)
                await message.reply("Something went wrong processing your message. Please try again.")
            finally:
                progress_done.set()
                try:
                    await asyncio.wait_for(progress_task, timeout=2.0)
                except Exception:
                    progress_task.cancel()

    async def _build_history(self, channel, limit: int = 10) -> list[dict[str, Any]]:
        """Build conversation history from recent messages in the channel."""
        history = []
        messages = []

        async for msg in channel.history(limit=limit + 1):  # +1 to skip current
            messages.append(msg)

        # Reverse to chronological order, skip the current message
        for msg in reversed(messages[1:]):
            if msg.author == self.user:
                history.append({"role": "assistant", "content": msg.content})
            elif not msg.author.bot:
                content = msg.content.replace(f"<@{self.user.id}>", "").strip()
                if content:
                    history.append({"role": "user", "content": content})

        return history


def _split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split a long message into chunks respecting Discord's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


_bot: ChiefOfStaffBot | None = None


def get_discord_bot() -> ChiefOfStaffBot:
    """Get the singleton Discord bot instance."""
    global _bot
    if _bot is None:
        _bot = ChiefOfStaffBot()
    return _bot


async def send_to_channel(channel_name: str, message: str) -> bool:
    """Send a message to a named Discord channel. Splits at 2000 char limit."""
    try:
        bot = get_discord_bot()
    except RuntimeError:
        logger.warning(f"Discord bot not initialized — cannot send to #{channel_name}")
        return False

    for guild in bot.guilds:
        for ch in guild.text_channels:
            if ch.name == channel_name:
                try:
                    for chunk in _split_message(message):
                        await ch.send(chunk)
                    return True
                except Exception as e:
                    logger.error(f"Failed to send to #{channel_name}: {e}")
                    return False

    logger.warning(f"Discord channel #{channel_name} not found")
    return False


async def start_discord_bot():
    """Start the Discord bot (runs forever)."""
    token = settings.discord_bot_token
    if not token:
        logger.warning("DISCORD_BOT_TOKEN not set — Discord bot disabled")
        return

    bot = get_discord_bot()
    logger.info("Starting Discord bot...")
    await bot.start(token)
