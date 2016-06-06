import logging
import sys
from time import sleep

from errbot.backends.base import Message, Room, Identifier
from errbot.errBot import ErrBot
from errbot.rendering import text
from errbot.rendering.ansiext import enable_format, TEXT_CHRS

log = logging.getLogger(u'errbot.backends.campfire')

try:
    import pyfire
except ImportError:
    log.exception("Could not start the campfire backend")
    log.fatal("""
    If you intend to use the campfire backend please install pyfire:
    pip install pyfire
    """)
    sys.exit(-1)


class CampfireConnection(pyfire.Campfire):

    rooms = {}
    def join_room(self, room, msg_callback, error_callback):
        room.join()
        stream = room.get_stream(error_callback=error_callback)
        stream.attach(msg_callback).start()
        self.rooms[room.name] = (room, stream)
        log.debug("CampfireConnection:join_room(): {}".format(self.rooms))

    def is_streaming(self, name):
        stream = self.rooms[name][1]
        return stream.is_streaming()

ENCODING_INPUT = sys.stdin.encoding

class CampfireIdentifier(Identifier):
    def __init__(self, user):
        self._user = user   # it is just one room for the moment

    @property
    def user(self):
        return self._user

    @property
    def person(self):
        return self._user

class CampfireRoom(Room):
    def __init__(self, bot, roomname):
        self.conn = bot.conn
        self.room = self.conn.get_room_by_name(roomname)
        self.bot = bot

    def join(self, username=None, password=None):
        log.debug("Joining room {}".format(self.room.name))
        self.conn.join_room(self.room, self.bot._msg_callback, self.bot._error_callback)

class CampfireBackend(ErrBot):

    def __init__(self, config):
        super(CampfireBackend, self).__init__(config)
        identity = config.BOT_IDENTITY
        self.conn = None
        self.subdomain = identity['subdomain']
        self.username = identity['username']
        self.password = identity['password']
        if not hasattr(config, 'CHATROOM_PRESENCE') or len(config.CHATROOM_PRESENCE) < 1:
            raise Exception('Your bot needs to join at least one room, please set'
                            ' CHATROOM_PRESENCE with at least a room in your config')
        self.chatroom = config.CHATROOM_PRESENCE[0]
        self.room = None
        self.ssl = identity['ssl'] if 'ssl' in identity else True
        self.bot_identifier = None
        compact = config.COMPACT_OUTPUT if hasattr(config, 'COMPACT_OUTPUT') else False
        self.md_converter = text()

    def send_message(self, mess):
        super(CampfireBackend, self).send_message(mess)
        body = self.md_converter.convert(mess.body)
        try:
            self.room.speak(body)  # Basic text support for the moment
        except Exception:
            log.exception(
                "An exception occurred while trying to send the following message "
                "to %s: %s" % (mess.to, mess.body)
            )
            raise

    def serve_forever(self):
        log.info("Initializing Campfire connection")
        self.connect()  # be sure we are "connected" before the first command
        self.connect_callback()  # notify that the connection occured
        log.info("Campfire connected.")
        try:
            while True:
                if self.conn.is_streaming(self.chatroom):
                    sleep(1)
                else:
                    log.error("Default Campfire room {} is not connected, retrying...".format(self.chatroom))
        except KeyboardInterrupt:
            log.info("Interrupt received, disconnecting...")
        finally:
            log.debug("Triggering disconnect callback")
            self.disconnect_callback()
            self.shutdown()

    def connect(self):
        self.bot_identifier = self.build_identifier(self.username)
        if not self.conn:
            self.conn = CampfireConnection(self.subdomain, self.username, self.password, self.ssl)
        return self.conn

    def build_message(self, text):
        return Message(text)

    def shutdown(self):
        super(CampfireBackend, self).shutdown()

    def build_identifier(self, txtrep):
        return CampfireIdentifier(txtrep)

    def send_simple_reply(self, mess, text, private=False):
        """Total hack to avoid stripping of rooms"""
        log.debug("send_simple_reply: {} {}".format(mess, text))
        self.send_message(self.build_reply(mess, text, True))

    @property
    def mode(self):
        return 'campfire'

    def prefix_groupchat_reply(self, message, identifier):
        message.body = '@{0} {1}'.format(identifier.nick, message.body)

    def rooms(self):
        log.debug("I have no idea what I am doing")
        pass

    def query_room(self, roomname):
        log.debug("query_room: querying room {} for info".format(roomname))
        return CampfireRoom(self, roomname)

    def change_presence(self):
        log.debug("I have no idea what I am doing")
        pass

    def build_reply(self, mess, text=None, private=False):
        response = self.build_message(text)
        response.frm = self.bot_identifier
        response.to = mess.frm
        return response

    def _msg_callback(self, message):
        user = ""
        if message.user:
            user = message.user.name
        self.room = message.room # message.room will be always set in Campfire
        #message.is_by_current_user() lead to weird race conditions :\
        if message.is_text():
            msg = Message(message.body)
            msg.frm = CampfireIdentifier(user)
            msg.to = self.bot_identifier  # assume it is for me
            self.callback_message(msg)

    def _error_callback(self, error, room):
        log.error("Stream STOPPED due to ERROR: %s in room %s" % (error, room.name))
