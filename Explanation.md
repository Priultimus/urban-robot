
# `class` **`UrbanRobot(socketio.AsyncNamespace)`**:
This class encompasses all the functions of Urban Robot. It inherits from `socketio.AsyncNamespace`, to allow easy integration with socket.io generally. 

## __Arguments__
### `vital_cogs`:
This is the list of modules that are definitely needed for a Helium process to start. This is, by default, `["modules.utilties"]`.
#
### `healthy_percentage`:
This is level of functioning, in percentage, that is minimum to be considered "healthy". By default, it is 100%.
#
### `shutdown_if_outdated`:
This simply designates whether or not a Helium process should shutdown or go comatose if outdated. By default it is `False`.
#
### `interval`:
This is the interval that a Helium process should send a heartbeat. By default, it is every 30 seconds.
#
### `token`:
This is the token used to authorize when connecting to Discord.
#
### `helium_path`:
This is the path of the given helium process, so Urban Robot knows where to spawn Helium processes from.
#
## __Attributes__
### `self.clients`:
The dictionary of all the connected clients.
#
### `self.ready_clients`:
The dictionary of all the clients that have an active connection to Discord.
#
### `self.running_client`:
The client actively processing user commands on Discord. This can be `None`.
#
### `self.cache`:
The cache retrived from a given Helium process.
#
### `self.cache_age`:
The exact time the cache was last updated.
#
### `self.is_sane`:
This is the flag that determines whether or not the code Urban Robot is currently deploying is functional. If this is ever `False`,  Urban Robot will become inactive, as no possible Helium process can be deployed. A manual start will be required.
#
### `self.last_known_good_hash`:
This is the git commit hash that is stored as the last commit that *worked*. Urban Robot will attempt to rollback to this in the event of a git pull failing a health check.
#
## __Events__
### `on_connect`:
This is triggered when a given Helium process connects to the `socketio` server. It prints the `sid`.
#
### `on_disconnect`:
This is triggered when a given Helium process disconnects from the `socketio` server. It assumed to be dead, and is removed from `self.clients`, `self.ready_clients` (if it was there) & if it was the running client, `self.running_client` is set to `{}`. It then calls `self.spawn_process` to attempt to restart the bot.
#
### `on_try_again`:
This is triggered when a developer specifically fixes code that left Urban Robot in an inactive state. It restarts `self.is_sane` to `True` and attempts to start a bot again.
#
### `on_heartbeat`:
This is triggered by a heartbeat event, it sets the last beat to the current second, and then responds with a heartbeat acknowledgement. 
#
### `on_hello`:
This is triggered by the Helium process sending a "hello" event. It writes down a version, and sets the `_since_last_beat` to be the current second. It responds with the token and the heartbeat interval, and if there's a running client, it says not to process commands, otherwise it does.
#
### `on_ready`:
This is triggered by the Helium process sending a "ready" event. Helium has successfully connected to Discord and is presently either waiting for commands from Urban Robot or is processing commands on Discord. In response, Urban Robot writes down the version. If the client that sent the event is processing commands, Urban Robot responds with an OK. Otherwise, it checks if this client is a newer version than the current running client, and if it is, it asks it to run a health check. 
#
### `on_health_check`:
This is triggered by the Helium process responding to a `health_check` command. It gives the results of the health check, and if all is OK, it's given the go ahead to run and start itself up. Otherwise, it checks if vital cogs were OK, and if not, it tells the Helium process to shutdown with the reason of `vital_cog_failed`. Otherwise, if the health percentage is below the specified threshold at `self.healthy_percentage`, then it tells it to shutdown with reason `health_check_failure`. 
#
### `on_cache_sync`:
This is triggered by a Helium process responding to a cache sync command. It receives the cache from a given client and fires the cache out to all the other clients.
#
### `on_coma`:
This is triggered by a client going into a coma. As of right now, I don't really know what I'm supposed to do here, so it just prints that. It exists for the sake of support.
#
### `on_shutdown`:
This is triggered by a client shutting down and disconnecting from Discord. Not to be confused with `on_disconnect`, this client still has a connection to Urban Robot, just not Discord. Urban Robot removes it from the `self.ready_client` dictionary.
#
## __Functions__
### `self.do_rollback()`:
This function reverts a git pull, usually after a failed health check.

#
### `self.do_cache_sync(sid)`:
This function retrieves the cache from a given client and stores it.
#
### `self.start(sid, reason, kill_running=False)`:
This function does a series of things:
- checks if there is a running client, if there is:
  - runs do_cache_sync
  - checks if the flag kill_running is True, if it is, it kills the running client, otherwise it sends the bot into a coma.
- Sets the given Helium process as the running client.
- Tells the given Helium process to start processing commands.
#
### `self.coma(sid, reason)`:
This function puts a given Helium process into a coma. If it's the running Helium process, it also saves the cache.
#
### `self.shutdown(sid, reason)`:
This function shuts down a given Helium process. If it's the running Helium process, it also saves the cache.
#
### `UrbanRobot.discord_send(destination, message, token, DM=False)`:
This is a `classmethod`. It makes an API request to Discord to send a message. If DM is `False`, destination is expected to be a channel ID, if DM is `True`, destination is expected to be a user ID. It will open the DM with the user first, then extract the channel ID from there.
#
### `UrbanRobot.spawn_process(process_path, log_file='log/helium')`:
This is a `classmethod`. It takes the path to a process and runs it. The output is put into the log file, which is by default named `helium-date-time.log`.
#
## __Dictionary__
### `dead`
This means the bot properly shuts down and the process is no longer running.
#
### `coma`
This means the given Helium process is not actively responding to USER commands but is still running and connected to Discord.
#
### `socketio`
The library used to communicate between Urban Robot and given Helium processes
#
### `event`
A socketio event. This is handled by the aforementioned socketio library.
#
### `command`
This can have two meanings, depending on context.
1. It can mean commands sent by users via Discord (e.g "!help")
2. It can mean commands sent by Urban Robot via socketio (e.g "shutdown"). Commands have a particular socketio event from which all commands are sent.
#
### `client`
A given Helium process. You may also see the term "running client". This is simply the Helium process that is actively responding to commands on DIscord.
#
### `cache`
The series of things stored in memory that Helium needs to remember for commands. (Think when to do a reminder, database cache, etc.)
#
### `token`
The authorization string given to Discord to login.
#
### `vital cog`
A vital cog is a cog that is absolutely necessary for a given Helium process to run. 
#
### `health check`
This is the series of checks Helium runs to make sure it is working properly, so broken code isn't deployed to production. This is on top of Travis CI.
