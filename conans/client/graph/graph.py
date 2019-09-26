import uuid

from conans.model.ref import PackageReference


RECIPE_DOWNLOADED = "Downloaded"
RECIPE_INCACHE = "Cache"  # The previously installed recipe in cache is being used
RECIPE_UPDATED = "Updated"
RECIPE_NEWER = "Newer"  # The local recipe is  modified and newer timestamp than server
RECIPE_NOT_IN_REMOTE = "Not in remote"
RECIPE_UPDATEABLE = "Update available"  # The update of recipe is available (only in conan info)
RECIPE_NO_REMOTE = "No remote"
RECIPE_EDITABLE = "Editable"
RECIPE_CONSUMER = "Consumer"  # A conanfile from the user
RECIPE_VIRTUAL = "Virtual"  # A virtual conanfile (dynamic in memory conanfile)

BINARY_CACHE = "Cache"
BINARY_DOWNLOAD = "Download"
BINARY_UPDATE = "Update"
BINARY_BUILD = "Build"
BINARY_MISSING = "Missing"
BINARY_SKIP = "Skip"
BINARY_EDITABLE = "Editable"


class Node(object):
    def __init__(self, ref, conanfile, recipe=None):
        self.ref = ref
        self._package_id = None
        self.prev = None
        self.conanfile = conanfile
        self.dependencies = []  # Ordered Edges
        self.dependants = set()  # Edges
        self.binary = None
        self.recipe = recipe
        self.remote = None
        self.binary_remote = None
        self.build_require = False
        self.private = False
        self.revision_pinned = False  # The revision has been specified by the user

        # A subset of the graph that will conflict by package name
        self.public_deps = None  # {ref.name: Node}
        # all the public deps only in the closure of this node
        # The dependencies that will be part of deps_cpp_info, can't conflict
        self.public_closure = None  # {ref.name: Node}
        self.inverse_closure = set()  # set of nodes that have this one in their public
        self.ancestors = None  # set{ref.name}
        self._id = None  # Unique ID (uuid at the moment) of a node in the graph
        self.graph_lock_node = None  # the locking information can be None

    @property
    def id(self):
        if self._id is None:
            self._id = str(uuid.uuid1())
        return self._id

    @id.setter
    def id(self, id_):
        self._id = id_

    @property
    def package_id(self):
        return self._package_id

    @package_id.setter
    def package_id(self, pkg_id):
        assert self._package_id is None, "Trying to override an existing package_id"
        self._package_id = pkg_id

    @property
    def name(self):
        return self.ref.name if self.ref else None

    @property
    def pref(self):
        assert self.ref is not None and self.package_id is not None, "Node %s" % self.recipe
        return PackageReference(self.ref, self.package_id, self.prev)

    def partial_copy(self):
        # Used for collapse_graph
        result = Node(self.ref, self.conanfile)
        result.dependants = set()
        result.dependencies = []
        result.binary = self.binary
        result.recipe = self.recipe
        result.remote = self.remote
        result.binary_remote = self.binary_remote
        result.build_require = self.build_require
        return result

    def add_edge(self, edge):
        if edge.src == self:
            if edge not in self.dependencies:
                self.dependencies.append(edge)
        else:
            self.dependants.add(edge)

    def neighbors(self):
        return [edge.dst for edge in self.dependencies]

    def private_neighbors(self):
        return [edge.dst for edge in self.dependencies if edge.private]

    def make_public(self):
        self.private = False
        for edge in self.dependencies:
            if not edge.private:
                edge.dst.make_public()

    def connect_closure(self, other_node):
        # When 2 nodes of the graph become connected, their closures information has
        # has to remain consistent. This method manages this.
        name = other_node.name
        self.public_closure[name] = other_node
        self.public_deps[name] = other_node
        other_node.inverse_closure.add(self)

    def inverse_neighbors(self):
        return [edge.src for edge in self.dependants]

    def __eq__(self, other):
        return (self.ref == other.ref and
                self.conanfile == other.conanfile)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.ref, self.conanfile))

    def __repr__(self):
        return repr(self.conanfile)

    def __cmp__(self, other):
        if other is None:
            return -1
        elif self.ref is None:
            return 0 if other.ref is None else -1
        elif other.ref is None:
            return 1

        if self.ref == other.ref:
            return 0

        # Cannot compare None with str
        if self.ref.revision is None and other.ref.revision is not None:
            return 1

        if self.ref.revision is not None and other.ref.revision is None:
            return -1

        if self.recipe in (RECIPE_CONSUMER, RECIPE_VIRTUAL):
            return 1
        if other.recipe in (RECIPE_CONSUMER, RECIPE_VIRTUAL):
            return -1
        if self.ref < other.ref:
            return -1

        return 1

    def __gt__(self, other):
        return self.__cmp__(other) == 1

    def __lt__(self, other):
        return self.__cmp__(other) == -1

    def __le__(self, other):
        return self.__cmp__(other) in [0, -1]

    def __ge__(self, other):
        return self.__cmp__(other) in [0, 1]


class Edge(object):
    def __init__(self, src, dst, require):
        self.src = src
        self.dst = dst
        self.require = require

    @property
    def private(self):
        return self.require.private

    @property
    def build_require(self):
        return self.require.build_require

    def __eq__(self, other):
        return self.src == self.src and self.dst == other.dst

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.src, self.dst))


class DepsGraph(object):
    def __init__(self):
        self.nodes = set()
        self.root = None
        self.aliased = {}
        # These are the nodes with pref (not including PREV) that have been evaluated
        self.evaluated = {}  # {pref: [nodes]}

    def add_node(self, node):
        if not self.nodes:
            self.root = node
        self.nodes.add(node)

    def add_edge(self, src, dst, require):
        assert src in self.nodes and dst in self.nodes
        edge = Edge(src, dst, require)
        src.add_edge(edge)
        dst.add_edge(edge)

    def ordered_iterate(self):
        ordered = self.by_levels()
        for level in ordered:
            for node in level:
                yield node

    def _inverse_closure(self, references):
        closure = set()
        current = [n for n in self.nodes if str(n.ref) in references or "ALL" in references]
        closure.update(current)
        while current:
            new_current = set()
            for n in current:
                closure.add(n)
                new_neighs = n.inverse_neighbors()
                to_add = set(new_neighs).difference(current)
                new_current.update(to_add)
            current = new_current
        return closure

    def collapse_graph(self):
        """Computes and return a new graph, that doesn't have duplicated nodes with the same
        PackageReference. This is the case for build_requires and private requirements
        """
        result = DepsGraph()
        result.add_node(self.root.partial_copy())
        unique_nodes = {}  # {PackageReference: Node (result, unique)}
        nodes_map = {self.root: result.root}  # {Origin Node: Result Node}
        # Add the nodes, without repetition. THe "node.partial_copy()" copies the nodes
        # without Edges
        for node in self.nodes:
            if node.recipe in (RECIPE_CONSUMER, RECIPE_VIRTUAL):
                continue
            pref = PackageReference(node.ref, node.package_id)
            if pref not in unique_nodes:
                result_node = node.partial_copy()
                result.add_node(result_node)
                unique_nodes[pref] = result_node
            else:
                result_node = unique_nodes[pref]
            nodes_map[node] = result_node

        # Compute the new edges of the graph
        for node in self.nodes:
            result_node = nodes_map[node]
            for dep in node.dependencies:
                src = result_node
                dst = nodes_map[dep.dst]
                result.add_edge(src, dst, dep.require)
            for dep in node.dependants:
                src = nodes_map[dep.src]
                dst = result_node
                result.add_edge(src, dst, dep.require)

        return result

    def new_build_order(self):
        """ returns an ordered list of lists, with tuples (node_id, pref)
        of the nodes of the graph to be built. Duplicates of pref will be ommitted
        It will return all the nodes with BINARY_BUILD status, i.e. those that have
        been processed according to rules like --build=missing and really need re-building
        """
        levels = self.inverse_levels()
        result = []
        total_prefs = set()  # to remove duplicates, same pref shouldn't build twice
        for level in reversed(levels):
            new_level = []
            for n in level:
                if n.binary == BINARY_BUILD and n.pref not in total_prefs:
                    new_level.append((n.id, repr(n.pref)))
                    total_prefs.add(n.pref)
            if new_level:
                result.append(new_level)
        return result

    def build_order(self, references):
        new_graph = self.collapse_graph()
        levels = new_graph.inverse_levels()
        closure = new_graph._inverse_closure(references)
        result = []
        for level in reversed(levels):
            new_level = [n.ref for n in level
                         if (n in closure and n.recipe not in (RECIPE_CONSUMER, RECIPE_VIRTUAL))]
            if new_level:
                result.append(new_level)
        return result

    def nodes_to_build(self):
        ret = []
        for node in self.ordered_iterate():
            if node.binary == BINARY_BUILD:
                if node.ref.copy_clear_rev() not in ret:
                    ret.append(node.ref.copy_clear_rev())
        return ret

    def by_levels(self):
        return self._order_levels(True)

    def inverse_levels(self):
        return self._order_levels(False)

    def _order_levels(self, direct):
        """ order by node degree. The first level will be the one which nodes dont have
        dependencies. Second level will be with nodes that only have dependencies to
        first level nodes, and so on
        return [[node1, node34], [node3], [node23, node8],...]
        """
        result = []
        opened = self.nodes
        while opened:
            current_level = []
            for o in opened:
                o_neighs = o.neighbors() if direct else o.inverse_neighbors()
                if not any(n in opened for n in o_neighs):
                    current_level.append(o)

            current_level.sort()
            result.append(current_level)
            # now initialize new level
            opened = opened.difference(current_level)

        return result
