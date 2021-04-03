import sys
import time
import socketio
import asyncio
import aiohttp
import subprocess
import datetime
from aiohttp import web

API_BASE_URL = "https://discord.com/api/v8"
CREATE_DM_URL = API_BASE_URL + "/users/@me/channels"
CREATE_MESSAGE_URL = API_BASE_URL + "/channels/{}/messages"


class GatewayError(Exception):
    pass


class NoRunningClient(GatewayError):
    pass


class UrbanRobot(socketio.AsyncNamespace):
    """Urban Robot is a simple Python script to manage Helium bot processes."""

    def __init__(self, *args, **kwargs):
        vital_cogs = kwargs.pop("vital_cogs", ["modules.utilities"])
        healthy_percentage = kwargs.pop("healthy_percentage", 100)
        shutdown_if_outdated = kwargs.pop("shutdown_if_outdated", False)
        interval = kwargs.pop("interval", 30)
        token = kwargs.pop("token", "token")
        super().__init__(*args, **kwargs)
        self.vital_cogs = vital_cogs
        self.healthy_percentage = healthy_percentage
        self.shutdown_if_outdated = shutdown_if_outdated
        self.interval = interval
        self.token = token
        self.clients = {}
        self.ready_clients = {}
        self.running_client = {}
        self.cache = {}
        self.cache_age = time.perf_counter()
        self.is_sane = True

    async def on_connect(self, sid, eviron):
        """This deals with clients that have just connected."""
        print(f"client {sid} has connected")

    async def on_disconnect(self, sid, environ):
        """This deals with clients that have disconnected."""
        print(f"client {sid} has disconnected")
        self.clients.pop(sid, None)
        self.ready_clients.pop(sid, None)
        if self.running_client["sid"] == sid:
            self.running_client = {}
        print("bot is assumed dead")
        if self.is_sane:
            print("attempting to restart bot")
            self.spawn_process("example_bot")
        else:
            print("the bot is not running, and the code is not functional.")
            print("developer intervention is required.")

    async def on_try_again(self, sid, data):
        """This handles the try_again event.

        This event is to only be used by a developer, in the case of
        a failed rollback or otherwise event that would case `is_sane` to
        become false."""
        self.is_sane = True
        self.spawn_process("example_bot")

    async def on_heartbeat(self, sid, data):
        since_last_beat = time.perf_counter()
        self.clients[sid]["_since_last_beat"] = since_last_beat
        await sio.emit(
            "heartbeat_ack",
            {"t": "heartbeat_ack", "d": {"since_last_beat": since_last_beat}},
        )
        print(f"client {sid} is alive")

    async def on_hello(self, sid, data):
        """This handles the first contact between the client and the gateway."""
        print(f"client {sid} has sent the HELLO event")
        data = data.get("d")
        self.clients[sid] = {
            "version": data.get("version"),
            "_since_last_beat": time.perf_counter(),
        }
        if self.running_client:
            await sio.emit(
                "hello",
                {
                    "t": "ack",
                    "d": {
                        "interval": self.interval,
                        "token": self.token,
                        "process_commands": False,
                    },
                },
            )
        else:
            await sio.emit(
                "hello",
                {"t": "ack", "d": {"token": self.token, "process_commands": True}},
            )

    async def on_ready(self, sid, data):
        """This handles the ready event sent from the client."""
        print(f"client {sid} has sent the READY event")
        self.ready_clients[sid] = self.clients[sid]
        data = data.get("d")

        if self.running_client and sid == self.running_client[sid]:
            await sio.emit("command", {"t": "OK", "d": {}})
            return

        outdated = self.clients[sid]["version"] <= self.running_client["version"]

        if not outdated:
            await sio.emit("command", {"t": "health_check", "d": {}})

        return

    async def on_health_check(self, sid, data):
        """Handles the response to the health check.

        This health check events is expected to be called only prior to startup."""
        data = data.get("d")
        if not data.get("OK"):
            cogs = data.get("cogs")
            for cog in cogs:
                if not cogs[cog] and cog in self.vital_cogs:
                    await self.shutdown(sid, "vital_cog_failed")
                    return
            if data.get("percent") < self.percent_to_start:
                await self.shutdown(sid, "health_check_failure")
                return

        await self.start_bot(sid, data.get("reason"))

    async def on_cache_sync(self, sid, data):
        """Sync the data between clients."""
        target = []
        if self.running_client["sid"] != sid:
            target.append(self.running_client["sid"])
        else:
            for client in self.ready_clients:
                if client["sid"] != sid:
                    target.append(client["sid"])

        for target in target:
            await sio.emit(
                "cache_sync", {"t": "cache_sync_recv", "d": data.get("d")}, to=target
            )

    async def on_coma(self, sid, data):
        """Handles the client being put into a 'coma' state.

        The coma state is defined by the client not processing commands sent by users."""
        print(
            f"client {sid} has stopped processing commands, but is still connected to discord"
        )

    async def on_shutdown(self, sid, data):
        """Handles the shutdown of a client."""
        print(f"client {sid} has disconnected from discord")
        if self.ready_clients.get(sid):
            self.ready_clients.pop(sid, None)

    async def coma(self, sid, reason):
        """This functions tells a given client to stop processing commands."""
        if self.running["sid"] == sid:
            await self.force_cache_sync(self.running_client["sid"])
            self.running = None
        await sio.emit("command", {"t": "process_commands", "d": {"stop": True}})

    async def shutdown(self, sid, reason):
        """This function tells a given client to shutdown."""
        if self.running["sid"] == sid:
            await self.force_cache_sync(self.running_client["sid"])
            self.running = None
        if reason == "health_check_fail":
            await self.do_rollback()
        await sio.emit("command", {"t": "shutdown", "d": {"reason": reason}}, to=sid)

    async def start(self, sid, reason, kill_running=False):
        """This function tells a given client to start."""
        if self.running_client:
            cache = await self.do_cache_sync(self.running_client["sid"])
            if kill_running:
                await sio.emit(
                    "command",
                    {"t": "shutdown", "d": {"reason": reason}},
                    to=self.running_client["sid"],
                )
            else:
                await sio.emit(
                    "command",
                    {"t": "coma", "d": {"reason": reason}},
                    to=self.running_client["sid"],
                )
        self.running_client = self.ready_clients[sid]
        await sio.emit(
            "command",
            {"t": "process_commands", "d": {"stop": False, "cache": cache}},
            to=sid,
        )

    async def do_cache_sync(self, sid):
        """Syncs the cache between clients."""

        async def handle_response(sid, data):
            """Handles the response to the cache sync."""
            self.cache = data.get("d").get("cache")
            self.cache_age = time.perf_counter()

        sio.on("cache_sync", handler=handle_response)
        await sio.call("cache_sync", {"t": "cache_sync", "d": {}}, to=sid)
        return self.cache

    @classmethod
    async def do_rollback(cls):
        raise NotImplementedError
        print("Rolling back previous update...")
        # TODO: do rollback & handle any potential error
        print("rollback successful.")

    @classmethod
    async def do_update_check(cls):
        raise NotImplementedError
        while True:
            print("Checking for updates...")
            # TODO: do git pull here
            update_found = "shrug"
            if update_found:
                print("Found update! Client has updated, starting new client.")
                cls.spawn_process("example_bot")
            else:
                print("No new update.")
            asyncio.sleep(250)

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
        file_name = (
            log_file + f"-{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"
        )
        f = open(file_name, "a")
        subprocess.Popen(
            [sys.executable, process_path], stdout=f, stderr=subprocess.STDOUT
        )


sio = socketio.AsyncServer()


def main():
    sio.register_namespace(UrbanRobot("/"))
    sio.start_background_task(UrbanRobot.do_update_check)
    app = web.Application()
    sio.attach(app)
    UrbanRobot.spawn_process("example")
    web.run_app(app)


if __name__ == "__main__":
    main()
