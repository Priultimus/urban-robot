import sys
import socketio
import aiohttp
from subprocess import Popen, PIPE, STDOUT
import datetime
from aiohttp import web
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.DEBUG)

# Load env from .env if possible.
PRODUCTION = True
if os.environ.get("MODE") != "production":
    load_dotenv(verbose=True)
    PRODUCTION = True

BOT_TOKEN = os.environ.get("BOT_TOKEN")
LOGGING_CHANNEL = os.environ.get("LOGGING_CHANNEL")
DISCORD_LOG_LEVEL = int(os.environ.get("DISCORD_LOG_LEVEL"))
HELIUM_PATH = os.environ.get("HELIUM_PATH")
print(HELIUM_PATH)

API_BASE_URL = "https://discord.com/api/v8"
CREATE_DM_URL = API_BASE_URL + "/users/@me/channels"
CREATE_MESSAGE_URL = API_BASE_URL + "/channels/{}/messages"


class GatewayError(Exception):
    pass


class NoRunningClient(GatewayError):
    pass


class RollbackFailure(GatewayError):
    pass


class UrbanRobot(socketio.AsyncNamespace):
    """Urban Robot is a simple Python script to manage Helium bot processes."""

    def __init__(self, *args, **kwargs):
        vital_cogs = kwargs.pop("vital_cogs", ["modules.utilities"])
        healthy_percentage = kwargs.pop("healthy_percentage", 100)
        shutdown_if_outdated = kwargs.pop("shutdown_if_outdated", False)
        token = kwargs.pop("token", BOT_TOKEN)
        super().__init__(*args, **kwargs)
        self.vital_cogs = vital_cogs
        self.healthy_percentage = healthy_percentage
        self.shutdown_if_outdated = shutdown_if_outdated
        self.token = token
        self.clients = {}
        self.ready_clients = {}
        self.running_client = {}
        self.is_sane = True
        self.last_known_good_hash = (
            Popen(["git", "rev-parse", "HEAD"], stdout=PIPE, cwd=HELIUM_PATH)
            .communicate()[0]
            .decode("utf-8")
            .strip("\n")
        )
        logging.debug(f"set last_known_good_hash to {self.last_known_good_hash}")

    async def on_connect(self, sid, environ):
        """This deals with clients that have just connected."""
        await self.log(f"client {sid} has connected", log_level=logging.DEBUG)

    async def on_disconnect(self, sid):
        """This deals with clients that have disconnected."""
        await self.log(f"client {sid} has disconnected", log_level=logging.DEBUG)
        self.clients.pop(sid, None)
        self.ready_clients.pop(sid, None)
        if self.running_client["sid"] == sid:
            self.running_client = {}
            await self.log("Bot is assumed dead.", log_level=logging.WARNING)
            if self.is_sane and PRODUCTION:
                self.spawn_process(HELIUM_PATH)
            else:
                await self.log(
                    "The bot is not running, and the code is not functional. "
                    "Developer intervention is required.",
                    log_level=logging.CRITICAL,
                )

    async def on_try_again(self, sid, data):
        """This handles the try_again event.

        This event is to only be used by a developer, in the case of
        a failed rollback or otherwise event that would case `is_sane` to
        become false."""
        await self.log(
            f"client {sid} has sent the TRY_AGAIN event with data {data}",
            log_level=logging.DEBUG,
        )
        self.is_sane = True
        self.spawn_process(HELIUM_PATH)

    async def on_identify(self, sid, data):
        """This handles the first contact between the client and the gateway."""
        await self.log(
            f"client {sid} has sent the IDENTIFY event with data {data}",
            log_level=logging.DEBUG,
        )
        await self.log(f"Initiating relationship with client {sid}")
        self.clients[sid] = {
            "version": data.get("version"),
            "sid": sid,
        }
        if self.running_client:
            data = {
                "token": self.token,
                "process_commands": False,
            }
        else:
            data = {
                "token": self.token,
                "process_commands": True,
            }
            self.running_client = self.clients[sid]

        await self.log(
            f"emitting event HELLO to client {sid} with data {data}",
            log_level=logging.DEBUG,
        )
        await sio.emit("hello", data, to=sid)

    async def on_ready(self, sid, data):
        """This handles the ready event sent from the client."""
        await self.log(
            f"client {sid} has sent the READY event with data {data}",
            log_level=logging.DEBUG,
        )
        self.ready_clients[sid] = self.clients[sid]
        version = self.clients[sid]["version"]

        if self.running_client and sid == self.running_client["sid"]:
            await self.log("emitting event CMD", log_level=logging.DEBUG)
            await self.log(
                f"dispatching cmd ok with no data to client {sid}",
                log_level=logging.DEBUG,
            )
            await self.log(f"Client {sid} is up and running!")
            await sio.emit("cmd", {"t": "ok", "d": {}}, to=sid)
            return

        outdated = version <= self.running_client["version"]

        if not outdated:
            await self.log(f"Starting up client {sid} with cmd health_check")
            await self.log("emitting event CMD", log_level=logging.DEBUG)
            await self.log(
                f"dispatching cmd health_check with no data to client {sid}",
                log_level=logging.DEBUG,
            )
            await sio.emit("cmd", {"t": "health_check", "d": {}}, to=sid)
            return

        await self.log(
            f"client {sid}'s version ({version}) is not newer than running client. not doing anything."
        )

        return

    async def on_health_check(self, sid, data):
        """Handles the response to the health check.

        This health check events is expected to be called only prior to startup."""
        await self.log(
            f"client {sid} has sent the HEALTH_CHECK event with data {data}",
            log_level=logging.DEBUG,
        )
        results = f"client {sid} health check: "
        if not data.get("OK"):
            cogs = data.get("cogs")
            for cog in cogs:
                if not cogs.get(cog) and cog in self.vital_cogs:
                    results = results + f"vital cog {cog} failed to load."
                    await self.log(results, log_level=logging.DEBUG)
                    await self.log(
                        f"Client {sid} FAILED health check.", log_level=logging.WARNING
                    )
                    await self.shutdown(sid, "vital_cog_failure")
                    return
            if data.get("percent") < self.percent_to_start:
                results = results + f"{data.get('percent')}% is too low to start."
                await self.log(results, log_level=logging.DEBUG)
                await self.log(
                    f"Client {sid} FAILED health check.", log_level=logging.WARNING
                )
                await self.shutdown(sid, "health_check_failure")
                return

        self.last_known_good_hash = (
            Popen(["git", "rev-parse", "HEAD"], stdout=PIPE, cwd=HELIUM_PATH)
            .communicate()[0]
            .decode("utf-8")
            .strip("\n")
            if data.get("OK")
            else self.last_known_good_hash
        )
        await self.log(
            f"set last_known_good_hash to {self.last_known_good_hash}",
            log_level=logging.DEBUG,
        )
        await self.start_bot(sid, data.get("reason"))

    async def on_coma(self, sid, data):
        """Handles the client being put into a 'coma' state.

        The coma state is defined by the client not processing commands sent by users."""
        await self.log(
            f"client {sid} has sent the COMA event with data {data}",
            log_level=logging.DEBUG,
        )

    async def on_shutdown(self, sid, data):
        """Handles the shutdown of a client."""
        await self.log(
            f"client {sid} has sent the SHUTDOWN event with data {data}",
            log_level=logging.DEBUG,
        )
        if sid == self.running_client["sid"]:
            await self.log(
                f"Running client {sid} has disconnected from Discord.",
                log_level=logging.WARNING,
            )
        else:
            await self.log(f"Client {sid} has disconnected from discord")
        if self.ready_clients.get(sid):
            self.ready_clients.pop(sid, None)

    async def coma(self, sid, reason):
        """This functions tells a given client to stop processing commands."""
        d = {"reason": reason}
        if self.running["sid"] == sid:
            self.running_client = {}
        await self.log("emitting event CMD", log_level=logging.DEBUG)
        await self.log(
            f"dispatching cmd process_commands with data {d} to client {sid}",
            log_level=logging.DEBUG,
        )
        await sio.emit("cmd", {"t": "coma", "d": d}, to=sid)

    async def shutdown(self, sid, reason):
        """This function tells a given client to shutdown."""
        await self.log(
            f"shutdown function for {sid} has been called", log_level=logging.DEBUG
        )
        d = {"reason": reason}

        if self.running_client["sid"] == sid:
            self.running_client = {}

        if reason in ["health_check_failure", "vital_cog_failure"]:
            await self.log("shutting down and rolling back client, failed health check")
            if PRODUCTION:
                await self.do_rollback()

        await self.log("emitting event CMD", log_level=logging.DEBUG)
        await self.log(
            f"dispatching command shutdown with data {d} to client {sid}",
            log_level=logging.DEBUG,
        )
        await self.log("running shutdown")
        await sio.emit("cmd", {"t": "shutdown", "d": d}, to=sid)

    async def start_bot(self, sid, reason, kill_running=False):
        """This function tells a given client to start."""
        await self.log(
            f"start function for {sid} has been called", log_level=logging.DEBUG
        )
        if self.running_client:
            d = {"reason": reason}
            if kill_running:
                await self.log("emitting event CMD", log_level=logging.DEBUG)
                await self.log(
                    f"dispatching command shutdown with data {d} to client {self.running_client['sid']}",
                    log_level=logging.DEBUG,
                )
                await sio.emit(
                    "cmd",
                    {"t": "shutdown", "d": d},
                    to=self.running_client["sid"],
                )
            else:
                await self.log("emitting event CMD", log_level=logging.DEBUG)
                await self.log(
                    f"dispatching command coma with data {d} to client {self.running_client['sid']}",
                    log_level=logging.DEBUG,
                )
                await sio.emit(
                    "cmd",
                    {"t": "coma", "d": d},
                    to=self.running_client["sid"],
                )
        self.running_client = self.ready_clients[sid]
        d = {"token": self.token}
        await self.log("emitting event CMD", log_level=logging.DEBUG)
        await self.log(
            f"dispatching command process_commands with data {d} to client {sid}",
            log_level=logging.DEBUG,
        )
        await sio.emit(
            "cmd",
            {"t": "process_commands", "d": d},
            to=sid,
        )

    async def do_rollback(self):
        await self.log("Rolling back previous update...")
        res = (
            Popen(
                [
                    "git",
                    "reset",
                    "--hard",
                    self.last_known_good_hash,
                ],
                cwd=HELIUM_PATH,
                stdout=PIPE,
            )
            .communicate()[0]
            .decode("utf-8")
        )
        res_list = res.split(" ")
        if res_list[0] != "HEAD":
            self.is_sane = False
            await self.log(
                "The bot is not running, and the code is not functional. "
                "Developer intervention is required.",
                log_level=logging.CRITICAL,
            )

            raise RollbackFailure(res)
        print(f"rollback successful.\n{res}")

    @classmethod
    async def discord_send(cls, destination: int, message: str, token: str, dm=False):
        """This makes an API request to Discord to send a message somewhere"""
        headers = {"Authorization": f"Bot {token}"}
        async with aiohttp.ClientSession() as session:
            if dm:
                async with session.post(
                    CREATE_DM_URL, headers=headers, json={"recipient_id": destination}
                ) as response:
                    if response.status >= 300:
                        return
                    destination = (await response.json())["id"]
            async with session.post(
                CREATE_MESSAGE_URL.format(destination),
                headers=headers,
                json={"content": message},
            ) as response:
                return await response.text()

    @classmethod
    async def log(
        cls,
        message: str,
        logging_channel_id=LOGGING_CHANNEL,
        token=BOT_TOKEN,
        log_level=logging.INFO,
    ):
        logging.log(log_level, message)
        if DISCORD_LOG_LEVEL < log_level:
            await cls.discord_send(logging_channel_id, message, token)

    @classmethod
    def spawn_process(cls, process_path, main_file="main.py", log_file="log/helium"):
        """This spawns a new python process."""
        logging.debug(f"spawning process {process_path}")
        file_name = (
            log_file + f"-{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"
        )
        f = open(file_name, "a")
        process = process_path + main_file
        Popen([sys.executable, process], stdout=f, stderr=STDOUT, cwd=process_path)


sio = socketio.AsyncServer()
sio.register_namespace(UrbanRobot("/"))
routes = web.RouteTableDef()


@routes.post("/payload")
async def payload(request):
    data = await request.json()
    if data.get("ref") == "refs/heads/main":
        for commit in data["commits"]:
            if commit["message"].startswith("[DEPLOY]"):
                await UrbanRobot.log("Deploying new update with git pull...")
                Popen(["git", "pull"], cwd=HELIUM_PATH)
                await sio.sleep(2)
                UrbanRobot.spawn_process(HELIUM_PATH)
                break
    return web.Response(text="OK")


app = web.Application()
app.add_routes(routes)
sio.attach(app)
# UrbanRobot.spawn_process(HELIUM_PATH)


if __name__ == "__main__":
    web.run_app(app)
