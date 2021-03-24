import websockets
import json
import asyncio
import aiohttp
import traceback 
import subprocess

API_BASE_URL = "https://discord.com/api/v8"
CREATE_DM_URL = API_BASE_URL + '/users/@me/channels'
CREATE_MESSAGE_URL = API_BASE_URL + '/channels/{}/messages'

class UrbanRobot:
    """Urban Robot is a simple Python script to manage Helium bot processes."""

    def __init__(self):
        self.clients = {}

    @classmethod
    async def discord_send(cls, destination: int, message: str, token: str, dm=False):
        """This makes an API request to Discord to send a message somewhere"""
        headers = {"Authorization": f"Bot {token}"}
        async with aiohttp.ClientSession() as session:
            if dm:
                async with session.post(CREATE_DM_URL, 
                                        headers=headers,
                                        json={'recipient_id': destination}) as response:
                    if response.status >= 300:
                        return
                    destination = (await response.json())['id']
            async with session.post(CREATE_MESSAGE_URL.format(destination), 
                                    headers=headers, 
                                    json={'content': message}) as response:
                return (await response.text())
