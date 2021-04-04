import sys
import time
import socketio
import aiohttp
from subprocess import Popen, PIPE, STDOUT
import datetime
from aiohttp import web
import os
from dotenv import load_dotenv
import logging

# Load env from .env if possible.
load_dotenv(verbose=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HELIUM_PATH = os.environ.get("HELIUM_PATH")

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
        interval = kwargs.pop("interval", 30)
        token = kwargs.pop("token", BOT_TOKEN)
        helium_path = kwargs.pop("helium_path", HELIUM_PATH)
        super().__init__(*args, **kwargs)
        self.vital_cogs = vital_cogs
        self.healthy_percentage = healthy_percentage
        self.shutdown_if_outdated = shutdown_if_outdated
        self.interval = interval
        self.token = token
        self.helium_path = helium_path
        self.clients = {}
        self.ready_clients = {}
        self.running_client = {}
        self.cache = {}
        self.cache_age = time.perf_counter()
        self.is_sane = True
        self.last_known_good_hash = (
            Popen(["git", "rev-parse", "HEAD"], stdout=PIPE)
            .communicate()[0]
            .decode("utf-8")
            .strip("\n")
        )
        logging.debug(f"set last_known_good_hash to {self.last_known_good_hash}")

    async def on_connect(self, sid, eviron):
        """This deals with clients that have just connected."""
        logging.debug(f"client {sid} has connected")

    async def on_disconnect(self, sid, environ):
        """This deals with clients that have disconnected."""
        logging.debug(f"client {sid} has disconnected")
        self.clients.pop(sid, None)
        self.ready_clients.pop(sid, None)
        if self.running_client["sid"] == sid:
            self.running_client = {}
        logging.warning("Bot is assumed dead.")
        if self.is_sane:
            logging.info("Attempting to restart bot...")
            self.spawn_process("example_bot")
        else:
            logging.critical("The bot is not running, and the code is not functional.")
            logging.critical("Developer intervention is required.")

    async def on_try_again(self, sid, data):
        """This handles the try_again event.

        This event is to only be used by a developer, in the case of
        a failed rollback or otherwise event that would case `is_sane` to
        become false."""
        logging.debug(f"client {sid} has sent the TRY_AGAIN event with data {data}")
        self.is_sane = True
        self.spawn_process("example_bot")

    async def on_heartbeat(self, sid, data):
        logging.debug(f"client {sid} has sent the HEARTBEAT event with data {data}")
        since_last_beat = time.perf_counter()
        self.clients[sid]["_since_last_beat"] = since_last_beat
        data = {"t": "heartbeat_ack", "d": {"since_last_beat": since_last_beat}}
        logging.debug(f"emitting event HEARTBEAT_ACK to client {sid} with data {data}")
        await sio.emit("heartbeat_ack", data, to=sid)

    async def on_hello(self, sid, data):
        """This handles the first contact between the client and the gateway."""
        logging.debug(f"client {sid} has sent the HELLO event with data {data}")
        logging.info(f"Initiating relationship with client {sid}")
        data = data.get("d")
        self.clients[sid] = {
            "version": data.get("version"),
            "_since_last_beat": time.perf_counter(),
        }
        if self.running_client:
            data = {
                "t": "ack",
                "d": {
                    "interval": self.interval,
                    "token": self.token,
                    "process_commands": False,
                },
            }
        else:
            data = {"t": "ack", "d": {"token": self.token, "process_commands": True}}

        logging.debug(f"emitting event HELLO to client {sid} with data {data}")
        await sio.emit("hello", data, to=sid)

    async def on_ready(self, sid, data):
        """This handles the ready event sent from the client."""
        logging.debug(f"client {sid} has sent the READY event with data {data}")
        self.ready_clients[sid] = self.clients[sid]
        data = data.get("d")

        if self.running_client and sid == self.running_client[sid]:
            logging.debug("emitting event COMMAND")
            logging.debug(f"dispatching command ok with no data to client {sid}")
            logging.info(f"Client {sid} is up and running!")
            await sio.emit("command", {"t": "ok", "d": {}}, to=sid)
            return

        outdated = self.clients[sid]["version"] <= self.running_client["version"]

        if not outdated:
            logging.info(f"Starting up client {sid} with command health_check")
            logging.debug("emitting event COMMAND")
            logging.debug(
                f"dispatching command health_check with no data to client {sid}"
            )
            await sio.emit("command", {"t": "health_check", "d": {}}, to=sid)

        return

    async def on_health_check(self, sid, data):
        """Handles the response to the health check.

        This health check events is expected to be called only prior to startup."""
        logging.debug(f"client {sid} has sent the HEALTH_CHECK event with data {data}")
        data = data.get("d")
        results = f"client {sid} health check: "
        if not data.get("OK"):
            cogs = data.get("cogs")
            for cog in cogs:
                if not cogs[cog] and cog in self.vital_cogs:
                    results = results + f"vital cog {cog} failed to load."
                    logging.debug(results)
                    logging.warning(f"Client {sid} FAILED health check.")
                    await self.shutdown(sid, "vital_cog_failed")
                    return
            if data.get("percent") < self.percent_to_start:
                results = results + f"{data.get('percent')}% is too low to start."
                logging.debug(results)
                logging.warning(f"Client {sid} FAILED health check.")
                await self.shutdown(sid, "health_check_failure")
                return

        self.last_known_good_hash = (
            Popen(["git", "rev-parse", "HEAD"], stdout=PIPE)
            .communicate()[0]
            .decode("utf-8")
            .strip("\n")
            if data.get("OK")
            else self.last_known_good_hash
        )
        logging.debug(f"set last_known_good_hash to {self.last_known_good_hash}")
        await self.start_bot(sid, data.get("reason"))

    async def on_cache_sync(self, sid, data):
        logging.debug(f"client {sid} has sent the CACHE_SYNC event with data {data}")
        """Sync the data between clients."""
        target = []
        if self.running_client["sid"] != sid:
            target.append(self.running_client["sid"])
        else:
            for client in self.ready_clients:
                if client["sid"] != sid:
                    target.append(client["sid"])

        for target in target:
            logging.debug(
                f"emitting event CACHE_SYNC to client {target} with data {data}"
            )
            await sio.emit(
                "cache_sync", {"t": "cache_sync_recv", "d": data.get("d")}, to=target
            )

    async def on_coma(self, sid, data):
        """Handles the client being put into a 'coma' state.

        The coma state is defined by the client not processing commands sent by users."""
        logging.debug(f"client {sid} has sent the COMA event with data {data}")

    async def on_shutdown(self, sid, data):
        """Handles the shutdown of a client."""
        logging.debug(f"client {sid} has sent the SHUTDOWN event with data {data}")
        if sid == self.running_client["sid"]:
            logging.warning(f"Running client {sid} has disconnected from Discord.")
        else:
            logging.info(f"Client {sid} has disconnected from discord")
        if self.ready_clients.get(sid):
            self.ready_clients.pop(sid, None)

    async def coma(self, sid, reason):
        """This functions tells a given client to stop processing commands."""
        if self.running["sid"] == sid:
            await self.force_cache_sync(self.running_client["sid"])
            self.running = None
        d = {"stop": True}
        logging.debug("emitting event COMMAND")
        logging.debug(
            f"dispatching command process_commands with data {d} to client {sid}"
        )
        await sio.emit("command", {"t": "process_commands", "d": d}, to=sid)

    async def shutdown(self, sid, reason):
        """This function tells a given client to shutdown."""
        logging.debug(f"shutdown function for {sid} has been called")
        if self.running["sid"] == sid:
            await self.force_cache_sync(self.running_client["sid"])
            self.running = None
        if reason == "health_check_fail":
            await self.do_rollback()
        d = {"reason": reason}
        logging.debug("emitting event COMMAND")
        logging.debug(f"dispatching command shutdown with data {d} to client {sid}")
        await sio.emit("command", {"t": "shutdown", "d": d}, to=sid)

    async def start(self, sid, reason, kill_running=False):
        """This function tells a given client to start."""
        logging.debug(f"start function for {sid} has been called")
        if self.running_client:
            cache = await self.do_cache_sync(self.running_client["sid"])
            d = {"reason": reason}
            if kill_running:
                logging.debug("emitting event COMMAND")
                logging.debug(
                    f"dispatching command shutdown with data {d} to client {self.running_client['sid']}"
                )
                await sio.emit(
                    "command",
                    {"t": "shutdown", "d": d},
                    to=self.running_client["sid"],
                )
            else:
                logging.debug("emitting event COMMAND")
                logging.debug(
                    f"dispatching command coma with data {d} to client {self.running_client['sid']}"
                )
                await sio.emit(
                    "command",
                    {"t": "coma", "d": d},
                    to=self.running_client["sid"],
                )
        self.running_client = self.ready_clients[sid]
        d = {"stop": False, "cache": cache}
        logging.debug("emitting event COMMAND")
        logging.debug(
            f"dispatching command process_commands with data {d} to client {sid}"
        )
        await sio.emit(
            "command",
            {"t": "process_commands", "d": d},
            to=sid,
        )

    async def do_cache_sync(self, sid):
        """Syncs the cache between clients."""
        logging.debug(f"running cache sync, target {sid}")

        async def handle_response(sid, data):
            """Handles the response to the cache sync."""
            logging.debug(
                f"client {sid} has sent the CACHE_SYNC event with data {data}"
            )
            self.cache = data.get("d").get("cache")
            self.cache_age = time.perf_counter()

        sio.on("cache_sync", handler=handle_response)
        logging.debug(f"calling event CACHE_SYNC to client {sid}")
        await sio.call("cache_sync", {"t": "cache_sync", "d": {}}, to=sid)
        return self.cache

    async def do_rollback(self):
        logging.info("Rolling back previous update...")
        res = (
            Popen(["git", "reset", "--hard", self.last_known_good_hash], stdout=PIPE)
            .communicate[0]
            .decode("utf-8")
        )
        res_list = res.split(" ")
        if res_list[0] != "HEAD":
            self.is_sane = False
            logging.critical(
                "Rollback failure! Urban Robot is no longer in a sane state."
            )
            logging.critical("Developer intervention is required.")
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
    def spawn_process(cls, process_path, log_file="log/helium"):
        """This spawns a new python process."""
        logging.debug(f"spawning process {process_path}")
        file_name = (
            log_file + f"-{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"
        )
        f = open(file_name, "a")
        Popen([sys.executable, process_path], stdout=f, stderr=STDOUT)


sio = socketio.AsyncServer()
sio.register_namespace(UrbanRobot("/"))
routes = web.RouteTableDef()


@routes.post("/payload")
async def payload(request):
    data = await request.json()
    if data.get("ref") == "refs/heads/main":
        for commit in data["commits"]:
            if commit["message"].startswith("[DEPLOY]"):
                logging.info("Deploying new update with git pull...")
                Popen(["git", "pull"])
                UrbanRobot.spawn_process(HELIUM_PATH)
                break
    return web.Response(text="OK")


app = web.Application()
sio.attach(app)
UrbanRobot.spawn_process(HELIUM_PATH)


if __name__ == "__main__":
    web.run_app(app)
