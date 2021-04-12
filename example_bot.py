import socketio
import asyncio
from discord.ext import commands
import logging

__VERSION__ = "0.0.1"

logging.basicConfig(level=logging.INFO)
sio = socketio.AsyncClient()


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_processing_commands = False

    async def on_message(self, message):
        if self.is_processing_commands:
            await self.process_commands(message)


bot = Bot(command_prefix="!")


class UrbanRobotClient(socketio.AsyncClientNamespace):
    """This is the client that handles all the work in connecting to Urban Robot.

    This should be a drop in to your existing discord.py bot."""

    def __init__(self, *args, **kwargs):
        bot = kwargs.pop("bot", None)
        super().__init__(*args, **kwargs)
        self.sid = None
        self.bot_is_running = False
        self.bot = bot
        self.bot.add_listener(self.on_bot_ready, "on_ready")

    @sio.event
    async def on_connect(self):
        logging.info("I've connected!")
        self.sid = sio.sid

    @sio.event
    async def on_disconnect(self):
        logging.info("I've disconnected.")
        if self.bot_is_running:
            await self.bot.close()

    @sio.event
    async def on_hello(self, data):
        logging.info("server has sent the HELLO event")
        self.bot.is_processing_commands = data.get("process_commands")
        logging.info("Received hello with token, logging into Discord...")
        if not self.bot_is_running and not self.bot.is_ready():
            await self.bot.start(data.get("token"))
            self.bot_is_running = True

    @sio.event
    async def on_cmd(self, data):
        logging.info(f"server has sent the CMD event with data {data}")
        try:
            cmd = data["t"]
            data = data["d"]
        except KeyError:
            if self.bot_is_running:
                await self.bot.close()
            await sio.disconnect()
            logging.critical("The server is broken.")
            asyncio.get_event_loop().stop()
            asyncio.get_event_loop().close()

        if cmd == "ok":
            return

        if cmd == "process_commands":
            self.bot.is_processing_commands = True
            if not self.bot_is_running and not self.bot.is_ready():
                logging.info("Received CMD process_commands, logging into Discord...")
                await self.bot.start(data.get("token"))
                self.bot_is_running = True

        if cmd == "health_check":
            await self.do_health_check()

        if cmd == "coma":
            self.bot.is_processing_commands = False

        if cmd == "shutdown":
            self.bot.is_processing_commands = False
            await self.bot.logout()
            self.bot_is_running = False

    async def on_bot_ready(self):
        logging.info("We've logged into Discord!")
        await sio.emit("ready", {})

    async def do_health_check(self):
        await sio.emit(
            "health_check",
            {
                "OK": False,
                "cogs": {"main": True, "modules.utilities": False},
                "percent": 100,
            },
        )


sio.register_namespace(UrbanRobotClient(bot=bot))


@bot.command()
async def version(ctx):
    logging.info("user command called version")
    await ctx.send(__VERSION__)


async def main():
    await sio.connect("http://localhost:8080")
    await sio.call("identify", {"version": __VERSION__})


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    asyncio.get_event_loop().run_forever()
