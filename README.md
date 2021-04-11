# Urban Robot

Something in Python!

## Events

### Connect
### Disconnect
Socket.IO handled events for when the client has connected/disconnected to the server.
#
### Identify
A client sent event. This initiates the relationship between Urban Robot and the client. It provides the version the client is currently running. In the future, this would also be where an authorization handshake would take place. Urban Robot sends back a `hello` event with the token to log into Discord with, as well as whether or not the client should immediately start processing user sent commands from Discord.
#
### Ready
A client sent event. This is sent when Discord has sent the READY event, and it signifies that this client has an active connection to Discord. This is useful to know so Urban Robot is aware of which clients are ready and able to start actively processing commands quickly.
#
### Health Check
A client sent event. This is sent as a response to the corresponding command of the same name. It contains the results of a health check. If the health check returns all OK, the client should expect to be given the go ahead to run. If it isn't, the client is expected to shutdown and then Urban Robot will rollback the code to the last functional version it is aware of.
#
### Cache Sync
A bidirectional event. When the sender is the client, the data sent should be the client's cache, usually after being requested. When the sender is Urban Robot, it should be the cache from the client who just sent it's cache. It'll usually send this to every ready client to keep them all in sync with each other.
#
### Coma
A client sent event. This is sent before the client goes into a "coma", meaning it's connected to Discord and ready but not actively processing commands from Discord.
#
### Shutdown
A client sent event. This is sent when the client is preparing to shutdown and stop running entirely. Urban Robot will run cleanup functions on its side as well.
#
### Hello
A server sent event. This is sent in response to an `identify`, with the token to login to Discord with and whether or not the client should actively be processing commands. In the future, this would also be the event where a failed authorization handshake would be ssent.
#
### Command
A server sent event. This is the event that sends commands to a client. Unlike other events, commands are formatted specifically as `{"t": "command", "d": "data"}`. 
The commands are as follows:

#### **`ok`**
This is the go ahead to start processing commands, ONLY sent in response to a `ready` event from the client. It will not be used to awaken a client from coma to start processing commands.

#### **`health_check`**
This is a request to perform a health check. Your client should follow the health check spec and respond with either an OK meaning everything returned good or a percentage of functionality and the cogs that are functional.

#### **`process_commands`**
This is a request to start processing commands. Your client should start validate it's connection to Discord and fire a `ready` event in response.

#### **`coma`**
This is a request to stop processing commands. It'll include a reason and whether or not you're expected to perform a cache sync as part of your cleanup. 

#### **`shutdown`**
This is a request to shutdown. It'll include a reason and whether or not you're expected to perform a cache sync as part of your cleanup.
#
## Health Check Spec
_I need to figure out how this works sooner or later_
