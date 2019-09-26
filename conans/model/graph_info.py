import json
import os

from conans.errors import ConanException
from conans.model.options import OptionsValues
from conans.model.ref import ConanFileReference
from conans.tools import save
from conans.util.files import load
from conans.model.graph_lock import GraphLockFile, LOCKFILE


GRAPH_INFO_FILE = "graph_info.json"


class GraphInfo(object):

    def __init__(self, profile=None, options=None, root_ref=None):
        # This field is a temporary hack, to store dependencies options for the local flow
        self.options = options
        self.root = root_ref
        self.profile = profile
        self.graph_lock = None

    @staticmethod
    def load(path):
        if not path:
            raise IOError("Invalid path")
        p = os.path.join(path, GRAPH_INFO_FILE)
        content = load(p)
        try:
            graph_info = GraphInfo.loads(content)
            return graph_info
        except Exception as e:
            raise ConanException("Error parsing GraphInfo from file '{}': {}".format(p, e))

    @staticmethod
    def loads(text):
        graph_json = json.loads(text)
        try:
            options = graph_json["options"]
        except KeyError:
            options = None
        else:
            options = OptionsValues(options)
        root = graph_json.get("root", {"name": None, "version": None, "user": None, "channel": None})
        root_ref = ConanFileReference(root["name"], root["version"], root["user"], root["channel"],
                                      validate=False)

        return GraphInfo(options=options, root_ref=root_ref)

    def save(self, folder, filename=None):
        filename = filename or GRAPH_INFO_FILE
        p = os.path.join(folder, filename)
        serialized_graph_str = self._dumps()
        save(p, serialized_graph_str)

        # A bit hacky, but to avoid repetition by now
        graph_lock_file = GraphLockFile(self.profile, self.graph_lock)
        graph_lock_file.save(os.path.join(folder, LOCKFILE))

    def save_lock(self, lockfile):
        graph_lock_file = GraphLockFile(self.profile, self.graph_lock)
        graph_lock_file.save(lockfile)

    def _dumps(self):
        result = {}
        if self.options is not None:
            result["options"] = self.options.as_list()
        result["root"] = {"name": self.root.name,
                          "version": self.root.version,
                          "user": self.root.user,
                          "channel": self.root.channel}
        return json.dumps(result, indent=True)
