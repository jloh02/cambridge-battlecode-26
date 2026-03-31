from cambc import Controller
import sys


class Logger:
    def __init__(self, ct: Controller):
        self.entity_type = str(ct.get_entity_type().value)
        self.entity_id = str(ct.get_id())

    def log(self, message: str):
        print("[{}:{}] {}".format(self.entity_type, self.entity_id, message))

    # prints to stderr instead of stdout, so it doesn't get truncated by the game engine
    def print(self, message: str):
        msg = "[{}:{}] {}".format(self.entity_type, self.entity_id, message)
        print(
            msg,
            file=sys.stderr,
        )
        print(msg)
