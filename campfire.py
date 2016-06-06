import logging
import sys

from errbot.backends.base import Message, Room, Identifier
from errbot.errBot import ErrBot
from errbot.rendering import text
from errbot.rendering.ansiext import enable_format, TEXT_CHRS

from threading import Condition

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
    rooms = {}  # keep track of joined room so we can send messages directly to them

    def join_room(self, name, msg_callback, error_callback):
        room = self.get_room_by_name(name)
        room.join()
        stream = room.get_stream(error_callback=error_callback)
        stream.attach(msg_callback).start()
        self.rooms[name] = (room, stream)


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
    def __init__(self, bot, room):
        self.conn = bot.conn
        self.room = self.conn.get_room_by_name(room)
        self.bot_identifier = bot.bot_identifier
        self.bot = bot

    def join(self, username=None, password=None):
        log.debug("Joining room {}".format(self.room))
        self.conn.join_room(self.room.name, self.msg_callback, self.error_callback)

    def msg_callback(self, message):
        log.debug('Incoming message [%s]' % message)
        user = ""
        if message.user:
            user = message.user.name
        if message.is_text():
            msg = Message(message.body)  # it is always a groupchat in campfire
            msg.frm = CampfireIdentifier(user)
            msg.to = self.bot_identifier  # assume it is for me
            self.bot.callback_message(msg)

    def error_callback(self, error, room):
        log.error("Stream STOPPED due to ERROR: %s in room %s" % (error, room))
        self.exit_lock.acquire()
        self.exit_lock.notify()
        self.exit_lock.release()

class CampfireBackend(ErrBot):
    exit_lock = Condition()

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
        log.debug("Sending message {}".format(mess))
        try:
            self.room.speak(body)  # Basic text support for the moment
        except Exception:
            log.excetion(
                "An exception occurred while trying to send the following message "
                "to %s: %s" % (mess.to.id, mess.body)
            )
            raise

    def serve_forever(self):
        self.exit_lock.acquire()
        self.connect()  # be sure we are "connected" before the first command
        self.connect_callback()  # notify that the connection occured
        try:
            log.info("Campfire connected.")
            self.exit_lock.wait()
        except KeyboardInterrupt:
            self.exit_lock.release()
            self.disconnect_callback()
            self.shutdown()

    def connect(self):
        if not self.conn:
            self.conn = CampfireConnection(self.subdomain, self.username, self.password, self.ssl)
            self.bot_identifier = self.build_identifier(self.username)
            self.room = self.conn.get_room_by_name(self.chatroom)
            self.room.join()
            # put us by default in the first room
            # resource emulates the XMPP behavior in chatrooms
        return self.conn

    def build_message(self, text):
        return Message(text)  # it is always a groupchat in campfire

    def shutdown(self):
        super(CampfireBackend, self).shutdown()

    def msg_callback(self, message):
        log.debug('Incoming message [%s]' % message)
        user = ""
        if message.user:
            user = message.user.name
        if message.is_text():
            msg = Message(message.body, type_='groupchat')  # it is always a groupchat in campfire
            msg.frm = CampfireIdentifier(user)
            msg.to = self.bot_identifier  # assume it is for me
            self.callback_message(msg)

    def build_identifier(self, strrep):
        return CampfireIdentifier(strrep)

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

    def query_room(self, room):
        log.debug("query_room: I have no idea what I am doing")
        return CampfireRoom(self, room)

    def change_presence(self):
        log.debug("I have no idea what I am doing")
        pass

    def build_reply(self, mess, text=None, private=False):
        log.debug("build_reply: I have no idea what I am doing")
        response = self.build_message(text)
        response.frm = self.bot_identifier
        response.to = mess.frm
        return response
